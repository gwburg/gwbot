import os
import json

from dotenv import load_dotenv
from openai import OpenAI

import models
from tools import tools, TOOL_MAPPING

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")


def create_client():
    client = OpenAI(
      base_url="https://openrouter.ai/api/v1",
      api_key=OPENROUTER_API_KEY,
    )
    return client


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


def agent_loop(client, model, messages, tools):
    while True:
        # append LLM message to context
        response = call_llm(client, model, messages, tools)
        llm_message = response.choices[0].message
        messages.append(llm_message.to_dict())

        log_step(llm_message)

        # end agentic loop if no tool calls are made
        if not llm_message.tool_calls:
            break

        # run all LLM tool calls
        for tool_call in llm_message.tool_calls:
            tool_output_mssg = execute_tool(tool_call)
            messages.append(tool_output_mssg)

    return messages[-1]


def call_llm(client, model, messages, tools):
    return client.chat.completions.create(
            model=model,
            tools=tools,
            messages=messages)


def execute_tool(tool_call):
    try:
        func = TOOL_MAPPING[tool_call.function.name]
        kwargs = json.loads(tool_call.function.arguments)
        tool_output = func(**kwargs)
    except KeyError:
        tool_output = f'Error: tool {tool_call.name} does not exist'
    except Exception as e:
        tool_output = f'Error calling {tool_call.name}: {e}'

    return {"role": "tool",
            "tool_call_id": tool_call.id,
            "content": str(tool_output)}


if __name__ == "__main__":
    model = models.MINIMAX
    client = create_client()
    task = "Read all the .py files in the current repo and write a .md file summarizing what this repo does"
    messages = [
            {
        "role": "system",
        "content": "You are a helpful assistant."
        },
            {
        "role": "user",
        "content": task,
        }
                ]

    agent_loop(client, model, messages, tools)
