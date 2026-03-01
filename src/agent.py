import asyncio
import inspect
import json
import os
from dataclasses import dataclass
from typing import Callable

import openai
import requests
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from memory import get_knowledge
from tools import TOOL_MAPPING, TOOL_TO_TAG

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")


# ---------------------------------------------------------------------------
# Events — emitted by the agent loop for the UI to consume
# ---------------------------------------------------------------------------


@dataclass
class StreamStart:
    pass


@dataclass
class StreamChunk:
    text: str


@dataclass
class StreamEnd:
    content: str | None


@dataclass
class ToolCallEvent:
    name: str
    args: dict


@dataclass
class ToolResultEvent:
    name: str
    call_id: str
    output: str


@dataclass
class UsageEvent:
    prompt_tokens: int
    completion_tokens: int
    total_prompt_tokens: int
    total_completion_tokens: int
    cost_usd: float
    context_pct: float | None


@dataclass
class WarningEvent:
    message: str


@dataclass
class RunEndEvent:
    total_prompt_tokens: int
    total_completion_tokens: int
    cost_usd: float


AgentEvent = StreamStart | StreamChunk | StreamEnd | ToolCallEvent | ToolResultEvent | UsageEvent | WarningEvent | RunEndEvent


# ---------------------------------------------------------------------------
# Client / model info
# ---------------------------------------------------------------------------


def create_client():
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )


def fetch_credits() -> float | None:
    """Return remaining OpenRouter credits in USD, or None on failure."""
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            timeout=5,
        )
        data = resp.json().get("data", {})
        total = data.get("total_credits")
        usage = data.get("total_usage")
        if total is not None and usage is not None:
            return total - usage
    except Exception:
        pass
    return None


def fetch_model_info(model: str) -> dict:
    """Return context_length and per-token pricing for a model from OpenRouter."""
    resp = requests.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
    )
    for m in resp.json().get("data", []):
        if m["id"] == model:
            pricing = m.get("pricing", {})
            return {
                "context_length": m.get("context_length"),
                "prompt_price": float(pricing.get("prompt", 0)),
                "completion_price": float(pricing.get("completion", 0)),
            }
    return {"context_length": None, "prompt_price": 0.0, "completion_price": 0.0}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _calc_cost(prompt_toks: int, completion_toks: int, model_info: dict) -> float:
    return prompt_toks * model_info["prompt_price"] + completion_toks * model_info["completion_price"]


def _fmt_args(args: dict, max_len: int = 60) -> str:
    parts = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > max_len:
            parts.append(f"{k}=<{len(v)} chars>")
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def _emit(on_event: Callable | None, event: AgentEvent):
    if on_event:
        on_event(event)


async def agent_loop(client, model, messages, tools, max_iterations=50, on_event: Callable[[AgentEvent], None] | None = None):
    model_info = await asyncio.to_thread(fetch_model_info, model)
    context_length = model_info["context_length"]

    total_prompt_tokens = 0
    total_completion_tokens = 0

    injected_tags: set[str] = set()

    for _ in range(max_iterations):
        content, tool_calls, usage = await call_llm(client, model, messages, tools, on_event=on_event)

        # Build message dict for history
        llm_msg = {"role": "assistant", "content": content}
        if tool_calls:
            llm_msg["tool_calls"] = tool_calls
        messages.append(llm_msg)

        # Usage tracking
        if usage:
            total_prompt_tokens += usage.prompt_tokens or 0
            total_completion_tokens += usage.completion_tokens or 0
            pct = (usage.prompt_tokens / context_length) if context_length and usage.prompt_tokens else None
            cost = _calc_cost(total_prompt_tokens, total_completion_tokens, model_info)

            _emit(on_event, UsageEvent(
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
                cost_usd=cost,
                context_pct=pct,
            ))

            if pct and pct >= 0.8:
                _emit(on_event, WarningEvent(message=f"context {pct:.0%} full ({usage.prompt_tokens}/{context_length} tokens)"))

        # Emit tool call events
        for tc in (tool_calls or []):
            raw = tc["function"]["arguments"]
            args = json.loads(raw) if raw else {}
            _emit(on_event, ToolCallEvent(name=tc["function"]["name"], args=args))

        if not tool_calls:
            break

        for tc in tool_calls:
            tool_output_msg = await execute_tool(tc)

            # Inject category knowledge on first use of each tag
            tag = TOOL_TO_TAG.get(tc["function"]["name"])
            if tag and tag not in injected_tags:
                injected_tags.add(tag)
                knowledge = await asyncio.to_thread(get_knowledge, tag)
                if knowledge:
                    prefix = f"[Knowledge for {tag} tools]\n"
                    prefix += "\n".join(f"- {m.get('content', '')}" for m in knowledge)
                    tool_output_msg["content"] = prefix + "\n\n" + tool_output_msg["content"]

            messages.append(tool_output_msg)
            _emit(on_event, ToolResultEvent(
                name=tc["function"]["name"],
                call_id=tc["id"],
                output=tool_output_msg["content"],
            ))
    else:
        _emit(on_event, WarningEvent(message=f"reached max iterations ({max_iterations})"))

    cost = _calc_cost(total_prompt_tokens, total_completion_tokens, model_info)
    _emit(on_event, RunEndEvent(
        total_prompt_tokens=total_prompt_tokens,
        total_completion_tokens=total_completion_tokens,
        cost_usd=cost,
    ))

    return messages[-1]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type(
        (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.InternalServerError,
        )
    ),
    reraise=True,
)
async def call_llm(client, model, messages, tools, on_event: Callable[[AgentEvent], None] | None = None):
    content_parts = []
    tool_calls_acc = {}
    usage = None
    stream_started = False

    stream = await client.chat.completions.create(
        model=model,
        tools=tools or None,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            if not stream_started:
                _emit(on_event, StreamStart())
                stream_started = True
            content_parts.append(delta.content)
            _emit(on_event, StreamChunk(text=delta.content))
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                if tc.id:
                    tool_calls_acc[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_calls_acc[idx]["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls_acc[idx]["function"]["arguments"] += tc.function.arguments

    content = "".join(content_parts) or None
    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)] or None

    if stream_started:
        _emit(on_event, StreamEnd(content=content))

    return content, tool_calls, usage


_TOOL_TIMEOUT = 60  # seconds before a tool call is considered hung


async def execute_tool(tool_call: dict) -> dict:
    name = tool_call["function"]["name"]
    try:
        func = TOOL_MAPPING[name]
        raw_args = tool_call["function"]["arguments"]
        kwargs = json.loads(raw_args) if raw_args else {}
        if inspect.iscoroutinefunction(func):
            coro = func(**kwargs)
        else:
            coro = asyncio.to_thread(func, **kwargs)
        tool_output = await asyncio.wait_for(coro, timeout=_TOOL_TIMEOUT)
    except asyncio.TimeoutError:
        tool_output = f"Error: tool '{name}' timed out after {_TOOL_TIMEOUT}s"
    except KeyError:
        tool_output = f"Error: tool '{name}' does not exist"
    except Exception as e:
        tool_output = f"Error calling '{name}': {e}"

    return {
        "role": "tool",
        "tool_call_id": tool_call["id"],
        "content": str(tool_output),
    }
