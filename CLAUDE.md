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

# Run the scheduler (processes due jobs)
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
- On startup, the user sends the first message. The agent only proactively mentions reminders that are overdue or due within 24 hours. The scheduler is also spawned fire-and-forget to catch overdue jobs.
- CLI: `--model` (aliases from `models.py`), `--max-iterations`, `--persona` (`default`/`casual`/`detailed`/`minimal`), `--note`, `--resume`.
- Key bindings: `Ctrl+Q`/`Ctrl+C` quit, `Alt+M` switch model, `Alt+N` toggle notes pane, `Alt+H`/`Alt+L` focus chat/notes.
- On quit, spawns a detached background subprocess to save conversation log and summarize into knowledge/tasks.

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

**`src/prompts/memory.py`** — Builds the memory section of the system prompt: injects all knowledge entries and all open tasks into every conversation.

### Memory system

Persistent memory stored under `~/.agent-memories/`:

**`src/memory/__init__.py`** — Core storage layer:
- **Logs:** Full conversation logs as JSONL in `logs/`.
- **Knowledge:** Tagged markdown entries in `knowledge/` with YAML frontmatter (id, tags, conversation_id, created, updated).
- **Tasks:** Task files in `tasks/` with YAML frontmatter (id, tags, owner, created, updated, due, job). A single file can contain multiple checklist items.
- **Archive:** Completed tasks and retired knowledge in `archive/`. Not injected into system prompt but searchable.
- **Jobs:** Scheduled job definitions in `jobs/`.
- Key functions: `save_conversation()`, `load_conversation()`, `list_conversations()`, `create_knowledge()`, `update_knowledge()`, `delete_knowledge()`, `search_knowledge()`, `create_task()`, `update_task()`, `complete_task_item()`, `archive_task()`, `archive_knowledge()`, `search_archive()`, `create_job()`, `list_jobs()`, `toggle_job()`.
- `search_knowledge()` uses hybrid scoring (tag match + embedding similarity + keyword).

**`src/memory/background.py`** — Async summarizer that converts conversations and user notes into knowledge/tasks via LLM:
- `spawn_background()` / `spawn_note_background()` — fire-and-forget detached subprocess.
- `process_conversation()` — classifies conversation content into knowledge/task operations.
- `process_note()` — processes direct user notes (checkboxes, deadlines, facts).
- Can run headlessly as `python -m memory.background <file.json>`.

**`src/memory/embeddings.py`** — Semantic embedding storage:
- SQLite DB at `~/.agent-memories/embeddings.db`.
- Uses OpenRouter embeddings API (`openai/text-embedding-3-small`).
- `compute_embedding()`, `store_embedding()`, `cosine_similarity()`, `backfill_embeddings()`.

### Scheduler

**`src/scheduler.py`** — Headless job runner:
- Entry point: `python -m scheduler`. Processes all due jobs.
- Jobs are stored as `.md` files in `~/.agent-memories/jobs/`.
- Supports cron expressions (`0 9 * * *`) and ISO datetimes (one-shot).
- PID-based lock file to prevent concurrent runs.
- CLI flags: `--install-cron`, `--uninstall-cron`, `--show-cron`.

### Tools

**`src/tools/`** — Tool definitions split into a package:
- `__init__.py`: Aggregates all tools from submodules; exposes `tools`, `TOOL_MAPPING`, and `get_tools(names)`.
- Each module exports `TAG`, `CATEGORY`, `tools` (JSON schemas), and `TOOL_MAPPING`.
- `bash.py`: `bash` — sync. TAG=`shell`. Shell commands with safety blocklist, 30s timeout, output truncation.
- `editor.py`: `text_editor` — sync. TAG=`editor`. File operations: `view`, `create`, `str_replace`, `insert`, `undo`.
- `memory.py`: Memory tools — sync. TAG=`memory`. Knowledge CRUD, task CRUD, archive management, and search.
- `monarch.py`: Monarch Money tools — async. TAG=`monarch`. Read-only financial tools via the `monarchmoney` library.
- `scheduler.py`: Scheduler tools — sync. TAG=`scheduler`. Create, list, delete, and toggle scheduled jobs.

### Adding a new tool

1. Implement the function in a new file under `src/tools/`. Use `async def` for async tools, plain `def` for sync — `execute_tool` handles both.
2. Add `TAG = "mytag"` and `CATEGORY = "description"` constants.
3. Define its JSON schema in a `tools` list and register it in a `TOOL_MAPPING` dict in that file.
4. Import and merge into `src/tools/__init__.py` (add to the `_modules` list).

### Selecting a subset of tools

```python
from tools import get_tools
tools, TOOL_MAPPING = get_tools(["bash"])
```

### Git

Always commit to git after making changes, with a succinct, descriptive message
