import argparse
import asyncio
import json
import os
from datetime import datetime, timezone

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

import models
from tools import TOOL_MAPPING, tools

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")


def create_client():
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )


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
# Logging
# ---------------------------------------------------------------------------


def _log_writer(path: str | None):
    """Return a write_log(type, **data) function. No-op if path is None."""
    if path is None:
        return lambda event_type, **data: None

    fh = open(path, "a")

    def write_log(event_type: str, **data):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, **data}
        fh.write(json.dumps(entry) + "\n")
        fh.flush()

    return write_log


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------


def _fmt_args(args: dict, max_len: int = 60) -> str:
    parts = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > max_len:
            parts.append(f"{k}=<{len(v)} chars>")
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


def log_tool_calls(tool_calls: list | None):
    for tc in tool_calls or []:
        raw = tc["function"]["arguments"]
        args = json.loads(raw) if raw else {}
        print(f"[tool] {tc['function']['name']}({_fmt_args(args)})")


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


async def agent_loop(client, model, messages, tools, max_iterations=50, log_path=None):
    model_info = await asyncio.to_thread(fetch_model_info, model)
    context_length = model_info["context_length"]
    write_log = _log_writer(log_path)

    total_prompt_tokens = 0
    total_completion_tokens = 0

    for _ in range(max_iterations):
        content, tool_calls, usage = await call_llm(client, model, messages, tools)

        # Build message dict for history
        llm_msg = {"role": "assistant", "content": content}
        if tool_calls:
            llm_msg["tool_calls"] = tool_calls
        messages.append(llm_msg)

        # Usage tracking
        if usage:
            total_prompt_tokens += usage.prompt_tokens or 0
            total_completion_tokens += usage.completion_tokens or 0
            if context_length and usage.prompt_tokens:
                pct = usage.prompt_tokens / context_length
                if pct >= 0.8:
                    print(f"[warning] context {pct:.0%} full ({usage.prompt_tokens}/{context_length} tokens)")

        log_tool_calls(tool_calls)
        write_log(
            "llm",
            content=content,
            tool_calls=[
                {"name": tc["function"]["name"], "args": json.loads(tc["function"]["arguments"] or "{}")}
                for tc in (tool_calls or [])
            ],
            usage={"prompt": usage.prompt_tokens, "completion": usage.completion_tokens} if usage else None,
        )

        if not tool_calls:
            break

        for tc in tool_calls:
            tool_output_msg = await execute_tool(tc)
            messages.append(tool_output_msg)
            write_log(
                "tool_result",
                tool=tc["function"]["name"],
                call_id=tc["id"],
                output=tool_output_msg["content"],
            )
    else:
        print(f"[warning] reached max iterations ({max_iterations})")

    cost = total_prompt_tokens * model_info["prompt_price"] + total_completion_tokens * model_info["completion_price"]
    print(f"[usage] prompt={total_prompt_tokens} completion={total_completion_tokens} cost=${cost:.4f}")
    write_log(
        "run_end",
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        cost_usd=cost,
    )

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
async def call_llm(client, model, messages, tools):
    content_parts = []
    tool_calls_acc = {}
    usage = None

    # Characters are queued by the producer and drained at a steady pace by the
    # consumer, smoothing out the irregular burst pattern of token delivery.
    CHAR_DELAY = 0.006  # seconds between characters (~165 chars/sec)
    char_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def producer():
        nonlocal usage
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
                content_parts.append(delta.content)
                for char in delta.content:
                    await char_queue.put(char)
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
        await char_queue.put(None)  # sentinel

    async def consumer():
        printed_prefix = False
        while True:
            char = await char_queue.get()
            if char is None:
                break
            if not printed_prefix:
                print("[assistant] ", end="", flush=True)
                printed_prefix = True
            print(char, end="", flush=True)
            await asyncio.sleep(CHAR_DELAY)
        if printed_prefix:
            print()  # newline after streamed content

    await asyncio.gather(producer(), consumer())

    content = "".join(content_parts) or None
    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)] or None

    return content, tool_calls, usage


async def execute_tool(tool_call: dict) -> dict:
    name = tool_call["function"]["name"]
    try:
        func = TOOL_MAPPING[name]
        kwargs = json.loads(tool_call["function"]["arguments"])
        if asyncio.iscoroutinefunction(func):
            tool_output = await func(**kwargs)
        else:
            tool_output = await asyncio.to_thread(func, **kwargs)
    except KeyError:
        tool_output = f"Error: tool '{name}' does not exist"
    except Exception as e:
        tool_output = f"Error calling '{name}': {e}"

    return {
        "role": "tool",
        "tool_call_id": tool_call["id"],
        "content": str(tool_output),
    }


def chat_input(prefill: str = "") -> str:
    """Read a line of input, optionally pre-filling with text for editing."""
    if prefill:
        try:
            import readline
            readline.set_startup_hook(lambda: readline.insert_text(prefill))
            try:
                return input("[user] ")
            finally:
                readline.set_startup_hook()
        except ImportError:
            pass
    return input("[user] ")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an agent loop")
    parser.add_argument("task", nargs="?", default=None, help="Initial task (omit to be prompted in --chat mode)")
    model_map = {k: v for k, v in vars(models).items() if not k.startswith("_")}
    parser.add_argument("--model", default="MINIMAX", choices=model_map,
                        metavar="MODEL", help=f"Model alias. Choices: {', '.join(model_map)}")
    parser.add_argument("--system-prompt",
                        default="You are a helpful, personal assistant, who can do a variety of general purpose tasks based on the tools provided to you")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--log", metavar="PATH", help="Write a JSONL log to this file")
    parser.add_argument("--chat", action="store_true", help="Interactive chat: prompt for each message, looping until empty input or Ctrl+C")
    args = parser.parse_args()

    client = create_client()
    messages = [{"role": "system", "content": args.system_prompt}]

    async def main():
        if args.chat:
            prefill = args.task or ""
            while True:
                try:
                    user_input = chat_input(prefill)
                    prefill = ""
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not user_input.strip():
                    break
                messages.append({"role": "user", "content": user_input})
                await agent_loop(
                    client,
                    model_map[args.model],
                    messages,
                    tools,
                    max_iterations=args.max_iterations,
                    log_path=args.log,
                )
        else:
            task = args.task or "Tell me about yourself"
            messages.append({"role": "user", "content": task})
            await agent_loop(
                client,
                model_map[args.model],
                messages,
                tools,
                max_iterations=args.max_iterations,
                log_path=args.log,
            )

    asyncio.run(main())
