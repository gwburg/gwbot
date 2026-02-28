# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for package management.

```bash
# Launch the TUI (interactive chat)
uv run src/app.py
uv run src/app.py --model SONNET

# Add a dependency
uv add <package>
```

Requires `OPENROUTER_API_KEY` in `.env`. Monarch Money tools also require `MONARCH_TOKEN` in `.env`.

## Architecture

A Textual TUI wrapping an async agentic loop that uses the OpenAI SDK pointed at [OpenRouter](https://openrouter.ai) (which provides a unified API for many LLM providers).

**`src/app.py`** — Textual App entry point:
- `AgentApp`: Main TUI application. Scrollable chat history (`RichLog`), streaming assistant output via a `Static` widget with 50ms flush timer, status bar showing model/tokens/cost/context usage, input box at bottom. Model switching via `Ctrl+N`.
- Runs `agent_loop` in a Textual worker. Agent events are delivered via `post_message(AgentMessage(event))` and routed in `on_agent_message()`.
- On startup, the agent automatically greets the user and surfaces any open TODOs/reminders.
- CLI: `--model` accepts aliases from `models.py`, `--max-iterations`, `--persona`, `--note`.

**`src/agent.py`** — Core agent logic (UI-independent):
- `agent_loop(client, model, messages, tools, max_iterations, on_event)`: Async. Runs the loop, emitting `AgentEvent` dataclasses via the `on_event` callback instead of printing.
- `call_llm()`: Async. Streams the response from OpenRouter, emitting `StreamStart`, `StreamChunk`, `StreamEnd` events. Wrapped with `tenacity` to retry up to 3x on rate limit, connection, and server errors.
- `execute_tool(tool_call)`: Async. Dispatches a tool call by name via `TOOL_MAPPING`. Awaits async tools directly; runs sync tools via `asyncio.to_thread`.
- Event types: `StreamStart`, `StreamChunk`, `StreamEnd`, `ToolCallEvent`, `ToolResultEvent`, `UsageEvent`, `WarningEvent`, `RunEndEvent`.

**`src/widgets.py`** — Custom Textual widgets:
- `StatusBar`: Reactive status line showing model, tokens, cost, and context fill bar.
- `ModelSelector`: Modal screen for switching models at runtime.

**`src/models.py`** — String constants for OpenRouter model IDs (e.g. `SONNET`, `GEMINI`, `MINIMAX`). The CLI builds its `--model` choices dynamically from this module, so adding a constant here automatically exposes it as a CLI option.

**`src/tools/`** — Tool definitions split into a package:
- `__init__.py`: Aggregates all tools and mappings from submodules; exposes `tools`, `TOOL_MAPPING`, `TOOL_TO_TAG`, `CATEGORY_TAGS`, and `get_tools(names)`.
- Each module exports `TAG` (short category key, e.g. `"shell"`), `CATEGORY` (human-readable description), `tools` (JSON schemas), and `TOOL_MAPPING`.
- `bash.py`: `bash` tool — sync. TAG=`shell`. Runs shell commands with a safety blocklist (no sudo, recursive rm, fork bombs, etc.), 30s default timeout, and output truncation.
- `editor.py`: `text_editor` tool — sync. TAG=`editor`. File operations: `view`, `create`, `str_replace`, `insert`, `undo` (in-process undo history per path).
- `memory.py`: Memory tools — sync. TAG=`memory`. Search, read, create, and update persistent memories.
- `monarch.py`: Monarch Money tools — async. TAG=`monarch`. 21 read-only tools wrapping the `monarchmoney` library (accounts, transactions, budgets, cashflow, etc.). Authenticated via `MONARCH_TOKEN` env var using a `Bearer` token extracted from the browser. Uses a lazy singleton `MonarchMoney` instance.

### Adding a new tool

1. Implement the function in a new file under `src/tools/`. Use `async def` for async tools, plain `def` for sync — `execute_tool` handles both.
2. Add `TAG = "mytag"` and `CATEGORY = "description"` constants.
3. Define its JSON schema in a `tools` list and register it in a `TOOL_MAPPING` dict in that file.
4. Import and merge into `src/tools/__init__.py` (add to the `_modules` list).

### Knowledge tier

Memories can have an optional `knowledge_tag` (stored as a separate field in frontmatter) for automatic injection:
- `always` — full content injected into the system prompt at startup via `prompts/memory.py`.
- Tool-category tags (`shell`, `editor`, `memory`, `monarch`) — content prepended to the first tool result from that category per conversation, handled in `agent.py`'s `agent_loop`.

The `knowledge_tag` is separate from descriptive `tags` — a memory can have both `tags: [finance, etrade]` and `knowledge_tag: monarch`.

### Selecting a subset of tools

```python
from tools import get_tools
tools, TOOL_MAPPING = get_tools(["bash"])
```

### Git

Always commit to git after making changes, with a succinct, descriptive message
