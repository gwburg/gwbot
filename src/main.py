import argparse
import json
import os
from datetime import datetime, timezone

import openai
import requests
from dotenv import load_dotenv
from openai import OpenAI
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
    return OpenAI(
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


def log_step(llm_message):
    if llm_message.content:
        print(f"[assistant] {llm_message.content}")
    for tool_call in llm_message.tool_calls or []:
        args = json.loads(tool_call.function.arguments)
        print(f"[tool] {tool_call.function.name}({_fmt_args(args)})")


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def agent_loop(client, model, messages, tools, max_iterations=50, log_path=None):
    model_info = fetch_model_info(model)
    context_length = model_info["context_length"]
    write_log = _log_writer(log_path)

    total_prompt_tokens = 0
    total_completion_tokens = 0

    for _ in range(max_iterations):
        response = call_llm(client, model, messages, tools)
        llm_message = response.choices[0].message
        messages.append(llm_message.to_dict())

        # Usage tracking
        usage = response.usage
        if usage:
            total_prompt_tokens += usage.prompt_tokens or 0
            total_completion_tokens += usage.completion_tokens or 0
            if context_length and usage.prompt_tokens:
                pct = usage.prompt_tokens / context_length
                if pct >= 0.8:
                    print(f"[warning] context {pct:.0%} full ({usage.prompt_tokens}/{context_length} tokens)")

        log_step(llm_message)
        write_log(
            "llm",
            content=llm_message.content,
            tool_calls=[
                {"name": tc.function.name, "args": json.loads(tc.function.arguments)}
                for tc in (llm_message.tool_calls or [])
            ],
            usage={"prompt": usage.prompt_tokens, "completion": usage.completion_tokens} if usage else None,
        )

        if not llm_message.tool_calls:
            break

        for tool_call in llm_message.tool_calls:
            tool_output_msg = execute_tool(tool_call)
            messages.append(tool_output_msg)
            write_log(
                "tool_result",
                tool=tool_call.function.name,
                call_id=tool_call.id,
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
def call_llm(client, model, messages, tools):
    return client.chat.completions.create(
        model=model,
        tools=tools,
        messages=messages,
    )


def execute_tool(tool_call):
    name = tool_call.function.name
    try:
        func = TOOL_MAPPING[name]
        kwargs = json.loads(tool_call.function.arguments)
        tool_output = func(**kwargs)
    except KeyError:
        tool_output = f"Error: tool '{name}' does not exist"
    except Exception as e:
        tool_output = f"Error calling '{name}': {e}"

    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": str(tool_output),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an agent loop")
    default_task = (
        "Read all the .py files in the current repo and write a SUMMARY.md file summarizing what this repo does"
    )
    parser.add_argument("task", nargs="?", default=default_task)
    model_map = {k: v for k, v in vars(models).items() if not k.startswith("_")}
    parser.add_argument("--model", default="MINIMAX", choices=model_map,
                        metavar="MODEL", help=f"Model alias. Choices: {', '.join(model_map)}")
    parser.add_argument("--system-prompt", default="You are a helpful assistant.")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--log", metavar="PATH", help="Write a JSONL log to this file")
    args = parser.parse_args()

    client = create_client()
    messages = [
        {"role": "system", "content": args.system_prompt},
        {"role": "user", "content": args.task},
    ]

    agent_loop(
        client,
        model_map[args.model],
        messages,
        tools,
        max_iterations=args.max_iterations,
        log_path=args.log,
    )
