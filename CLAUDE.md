# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for package management.

```bash
# Run the agent (task is optional, defaults to a summarisation task)
uv run src/main.py "your task here"
uv run src/main.py "your task here" --model MINIMAX --log run.jsonl

# Add a dependency
uv add <package>
```

Requires `OPENROUTER_API_KEY` in `.env`. Monarch Money tools also require `MONARCH_TOKEN` in `.env`.

## Architecture

A minimal async agentic loop using the OpenAI SDK pointed at [OpenRouter](https://openrouter.ai) (which provides a unified API for many LLM providers).

**`src/main.py`** — Entry point and core loop:
- `agent_loop(client, model, messages, tools, max_iterations, log_path)`: Async. Runs the loop, stopping when the model makes no tool calls or `max_iterations` is reached. Tracks token usage per call, warns at 80% context fill, and prints total tokens + cost on exit.
- `fetch_model_info(model)`: Fetches `context_length` and per-token pricing from the OpenRouter `/models` endpoint at the start of each run.
- `call_llm()`: Async. Streams the response using a producer-consumer queue — the producer reads chunks from the API and enqueues characters; the consumer drains at a fixed rate (~165 chars/sec) for smooth output. Wrapped with `tenacity` to retry up to 3× on rate limit, connection, and server errors. Returns `(content, tool_calls, usage)`.
- `execute_tool(tool_call)`: Async. Dispatches a tool call by name via `TOOL_MAPPING`. Awaits async tools directly; runs sync tools via `asyncio.to_thread`. Returns a `tool` role message.
- `_log_writer(path)`: Returns a `write_log` function that appends JSONL entries (or a no-op if `path` is None). Logs each LLM turn, tool result, and a final `run_end` summary.
- CLI (`__main__`): `task` positional arg, `--model` accepts aliases from `models.py` (e.g. `SONNET`, `MINIMAX`), `--max-iterations`, `--log`.

**`src/models.py`** — String constants for OpenRouter model IDs (e.g. `SONNET`, `GEMINI`, `MINIMAX`). The CLI builds its `--model` choices dynamically from this module, so adding a constant here automatically exposes it as a CLI option.

**`src/tools/`** — Tool definitions split into a package:
- `__init__.py`: Aggregates all tools and mappings from submodules; exposes `tools`, `TOOL_MAPPING`, and `get_tools(names)` for selecting a subset of tools.
- `bash.py`: `bash` tool — sync. Runs shell commands with a safety blocklist (no sudo, recursive rm, fork bombs, etc.), 30s default timeout, and output truncation.
- `editor.py`: `text_editor` tool — sync. File operations: `view`, `create`, `str_replace`, `insert`, `undo` (in-process undo history per path).
- `monarch.py`: Monarch Money tools — async. 21 read-only tools wrapping the `monarchmoney` library (accounts, transactions, budgets, cashflow, etc.). Authenticated via `MONARCH_TOKEN` env var using a `Bearer` token extracted from the browser. Uses a lazy singleton `MonarchMoney` instance.

### Adding a new tool

1. Implement the function in a new file under `src/tools/`. Use `async def` for async tools, plain `def` for sync — `execute_tool` handles both.
2. Define its JSON schema in a `tools` list and register it in a `TOOL_MAPPING` dict in that file.
3. Import and merge both into `src/tools/__init__.py`.

### Selecting a subset of tools

```python
from tools import get_tools
tools, TOOL_MAPPING = get_tools(["bash"])
```
