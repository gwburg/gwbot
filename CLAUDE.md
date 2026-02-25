# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for package management.

```bash
# Run the agent
uv run src/main.py

# Add a dependency
uv add <package>
```

Requires `OPENROUTER_API_KEY` in `.env`.

## Architecture

A minimal agentic loop using the OpenAI SDK pointed at [OpenRouter](https://openrouter.ai) (which provides a unified API for many LLM providers).

**`src/main.py`** — Entry point and core loop:
- `agent_loop()`: Repeatedly calls the LLM and executes any tool calls until the model returns a response with no tool calls.
- `execute_tool()`: Dispatches a tool call by name using `TOOL_MAPPING`, passes parsed JSON arguments as kwargs, returns a `tool` role message.
- The `__main__` block sets the model, initial messages, and kicks off the loop.

**`src/models.py`** — String constants for OpenRouter model IDs (e.g. `SONNET`, `GEMINI`, `MINIMAX`). Import and pass to `agent_loop`.

**`src/tools/`** — Tool definitions split into a package:
- `__init__.py`: Aggregates all tools and mappings from submodules; exposes `tools`, `TOOL_MAPPING`, and `get_tools(names)` for selecting a subset of tools.
- `bash.py`: `bash` tool — runs shell commands with a safety blocklist (no sudo, recursive rm, fork bombs, etc.) and output truncation.
- `editor.py`: `text_editor` tool — file operations: `view`, `create`, `str_replace`, `insert`, `undo` (in-process undo history per path).

### Adding a new tool

1. Implement the function in a new file under `src/tools/`.
2. Define its JSON schema in a `tools` list and register it in a `TOOL_MAPPING` dict in that file.
3. Import and merge both into `src/tools/__init__.py`.

### Selecting a subset of tools

```python
from tools import get_tools
tools, TOOL_MAPPING = get_tools(["bash"])
```
