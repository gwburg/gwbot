# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for package management.

```bash
# Launch the TUI (interactive chat)
uv run src/app.py
uv run src/app.py --model SONNET

# Resume a previous conversation
uv run src/app.py --resume

# Open with notes pane
uv run src/app.py --note

# Run the scheduler (processes due jobs + daily review)
uv run -m scheduler

# Install/uninstall the cron entry (runs scheduler every 15 min)
uv run -m scheduler --install-cron
uv run -m scheduler --uninstall-cron

# Add a dependency
uv add <package>
```

Requires `OPENROUTER_API_KEY` in `.env`. Monarch Money tools also require `MONARCH_TOKEN` in `.env`.

## Architecture

A Textual TUI wrapping an async agentic loop that uses the OpenAI SDK pointed at [OpenRouter](https://openrouter.ai) (which provides a unified API for many LLM providers).

### TUI layer

**`src/app.py`** — Textual App entry point:
- `AgentApp`: Main TUI application. Scrollable chat history, streaming assistant output via a `Static` widget with 50ms flush timer, status bar, input box at bottom.
- Runs `agent_loop` in a Textual worker. Agent events are delivered via `post_message(AgentMessage(event))` and routed in `on_agent_message()`.
- On startup, the agent automatically greets the user and surfaces any open TODOs/reminders. The scheduler is also spawned fire-and-forget to catch overdue jobs.
- CLI: `--model` (aliases from `models.py`), `--max-iterations`, `--persona` (`default`/`casual`/`detailed`/`minimal`), `--note`, `--resume`.
- Key bindings: `Ctrl+Q`/`Ctrl+C` quit, `Alt+M` switch model, `Alt+N` toggle notes pane, `Alt+H`/`Alt+L` focus chat/notes.
- On quit, spawns a detached background subprocess to save conversation log and summarize into high-level memories.

**`src/widgets.py`** — Custom Textual widgets:
- `StatusBar`: Reactive bar showing model, tokens, cost, and context fill %.
- `ModelSelector`: Modal for runtime model switching.
- `ConversationSelector`: Modal for resuming past conversations with pagination and context-length warnings.
- `SubmittableTextArea`: TextArea that submits on Enter (Shift+Enter for newline).
- `NotesPane`: Side panel with note input; notes are processed async in background via the memory summarizer.

**`src/app.tcss`** — Textual CSS for layout and styling.

### Agent layer

**`src/agent.py`** — Core agent logic (UI-independent):
- `agent_loop(client, model, messages, tools, max_iterations, on_event)`: Async loop emitting `AgentEvent` dataclasses via the `on_event` callback.
- `call_llm()`: Async streaming from OpenRouter. Retries up to 3x on rate limit, connection, and server errors via `tenacity`.
- `execute_tool(tool_call)`: Dispatches by name via `TOOL_MAPPING`. Awaits async tools; runs sync tools via `asyncio.to_thread`.
- Event types: `StreamStart`, `StreamChunk`, `StreamEnd`, `ToolCallEvent`, `ToolResultEvent`, `UsageEvent`, `WarningEvent`, `RunEndEvent`.

**`src/models.py`** — String constants for OpenRouter model IDs (e.g. `SONNET`, `GEMINI`, `MINIMAX`). Adding a constant here automatically exposes it as a CLI option.

### Prompts

**`src/prompts/system.py`** — Generates the full system prompt by composing a persona template + date/time context + tool category list + memory section. Personas: `default`, `casual`, `detailed`, `minimal`.

**`src/prompts/memory.py`** — Builds the memory section of the system prompt: injects open tasks (todos, reminders with overdue labels), always-tagged knowledge, and describes the knowledge tier system.

### Memory system

Two-tier persistent memory stored under `~/.agent-memories/`:

**`src/memory/__init__.py`** — Core storage layer:
- **Low-level:** Full conversation logs as JSONL in `low/`.
- **High-level:** Tagged markdown summaries in `high/` with YAML frontmatter (type, tags, knowledge_tag, owner, deadline, recurring, etc.).
- Memory types: `memory`, `todo`, `reminder`, `job`.
- Key functions: `save_conversation()`, `load_conversation()`, `list_conversations()`, `create_memory()`, `update_memory()`, `delete_memory()`, `search_memories()`, `create_job()`, `list_jobs()`, `toggle_job()`, `update_job_run()`.
- `search_memories()` uses hybrid scoring (tag match + embedding similarity + keyword).

**`src/memory/background.py`** — Async summarizer that converts conversations and user notes into long-term memories via LLM:
- `spawn_background()` / `spawn_note_background()` — fire-and-forget detached subprocess.
- `process_conversation()` — classifies conversation content into memory/todo/reminder operations.
- `process_note()` — processes direct user notes (checkboxes, deadlines, facts).
- Can run headlessly as `python -m memory.background <file.json>`.

**`src/memory/embeddings.py`** — Semantic embedding storage:
- SQLite DB at `~/.agent-memories/embeddings.db`.
- Uses OpenRouter embeddings API (`openai/text-embedding-3-small`).
- `compute_embedding()`, `store_embedding()`, `cosine_similarity()`, `backfill_embeddings()`.

### Scheduler

**`src/scheduler.py`** — Headless job runner:
- Entry point: `python -m scheduler`. Processes all due jobs + daily memory review.
- Supports cron expressions (`0 9 * * *`) and ISO datetimes (one-shot).
- PID-based lock file to prevent concurrent runs.
- Daily review agent checks for contradictions and outdated memories.
- CLI flags: `--install-cron`, `--uninstall-cron`, `--show-cron`.

### Tools

**`src/tools/`** — Tool definitions split into a package:
- `__init__.py`: Aggregates all tools from submodules; exposes `tools`, `TOOL_MAPPING`, `TOOL_TO_TAG`, `CATEGORY_TAGS`, and `get_tools(names)`.
- Each module exports `TAG`, `CATEGORY`, `tools` (JSON schemas), and `TOOL_MAPPING`.
- `bash.py`: `bash` — sync. TAG=`shell`. Shell commands with safety blocklist, 30s timeout, output truncation.
- `editor.py`: `text_editor` — sync. TAG=`editor`. File operations: `view`, `create`, `str_replace`, `insert`, `undo`.
- `memory.py`: Memory tools — sync. TAG=`memory`. Search, read, create, update, and delete persistent memories.
- `monarch.py`: Monarch Money tools — async. TAG=`monarch`. Read-only financial tools via the `monarchmoney` library.
- `scheduler.py`: Scheduler tools — sync. TAG=`scheduler`. Create, list, delete, and toggle scheduled jobs.

### Adding a new tool

1. Implement the function in a new file under `src/tools/`. Use `async def` for async tools, plain `def` for sync — `execute_tool` handles both.
2. Add `TAG = "mytag"` and `CATEGORY = "description"` constants.
3. Define its JSON schema in a `tools` list and register it in a `TOOL_MAPPING` dict in that file.
4. Import and merge into `src/tools/__init__.py` (add to the `_modules` list).

### Knowledge tier

Memories can have an optional `knowledge_tag` (stored as a separate field in frontmatter) for automatic injection:
- `always` — full content injected into the system prompt at startup via `prompts/memory.py`.
- Tool-category tags (`shell`, `editor`, `memory`, `monarch`, `scheduler`) — content prepended to the first tool result from that category per conversation, handled in `agent.py`'s `agent_loop`.

The `knowledge_tag` is separate from descriptive `tags` — a memory can have both `tags: [finance, etrade]` and `knowledge_tag: monarch`.

### Selecting a subset of tools

```python
from tools import get_tools
tools, TOOL_MAPPING = get_tools(["bash"])
```

### Git

Always commit to git after making changes, with a succinct, descriptive message
