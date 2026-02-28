"""Background agent that summarizes conversations into high-level memories.

Can be run as a standalone script for detached processing:
    python -m memory.background <conversation_file.json>
"""

import json
import os
import subprocess
import sys
import tempfile

import models
from memory import (
    create_memory,
    get_tags,
    list_all_memories,
    save_conversation,
    update_memory,
)

DEFAULT_MODEL = models.MINIMAX


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences from LLM output."""
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return raw



def _apply_operations(operations: list[dict], conversation_id: str | None = None) -> list[dict]:
    """Process a list of memory operations (create or update) and return results."""
    results = []
    for op in operations:
        if op.get("duplicate_of") and op.get("updated_content"):
            try:
                meta = update_memory(
                    op["duplicate_of"],
                    content=op["updated_content"],
                    tags=op.get("tags"),
                    knowledge_tag=op.get("knowledge_tag") or None,
                )
                meta["action"] = "updated"
                results.append(meta)
                continue
            except FileNotFoundError:
                pass  # Fall through to create

        op_type = op.get("type", "memory")
        kwargs = {
            "content": op["summary"],
            "tags": op.get("tags", []),
            "type": op_type,
        }
        if op.get("owner"):
            kwargs["owner"] = op["owner"]
        if op.get("deadline"):
            kwargs["deadline"] = op["deadline"]
        if op.get("recurring"):
            kwargs["recurring"] = op["recurring"]
        if op.get("knowledge_tag"):
            kwargs["knowledge_tag"] = op["knowledge_tag"]
        if conversation_id and op_type == "memory":
            kwargs["conversation_id"] = conversation_id

        meta = create_memory(**kwargs)
        meta["action"] = "created"
        results.append(meta)

    return results


def _spawn(args: list[str], data: dict) -> None:
    """Write data to a temp file and launch a detached subprocess."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="agent_", delete=False
    )
    json.dump(data, tmp)
    tmp.close()

    subprocess.Popen(
        [sys.executable, "-m", "memory.background"] + args + [tmp.name],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

_SHARED_SCHEMA_RULES = """\
Each element in the array is an operation object with these fields:
{{
  "type": "memory",         // "memory" (default), "todo", or "reminder"
  "summary": "...",         // content; verbatim for short notes, concise summary otherwise
  "tags": ["tag1"],         // descriptive tags; reuse existing ones when possible
  "owner": null,            // "user" or "agent" — for todo/reminder only
  "deadline": null,         // YYYY-MM-DD — for reminder only
  "recurring": false,       // true = hides for today and reappears next session — for reminder only
  "knowledge_tag": null,    // "always"|"shell"|"editor"|"memory"|"monarch" — for memory only; auto-injects content
  "duplicate_of": null,     // ID of existing memory to update instead of creating
  "updated_content": null   // merged content when updating a duplicate
}}

Type guide:
- "memory": a fact, preference, decision, or instruction worth remembering long-term.
- "todo": a task with no deadline. Set owner="user" (remind the user) or owner="agent" (agent's own task).
- "reminder": a time-sensitive item. Requires deadline (YYYY-MM-DD). Use recurring=true for repeating tasks.

Rules:
- Each operation captures ONE distinct topic or fact.
- If content overlaps with an existing memory, set duplicate_of + updated_content to merge; don't create a duplicate.
- Use existing tags when possible; only invent new ones if truly needed.
- Keep summaries concise — one to three sentences each.
- Omit null/false fields (they are optional)."""

def _build_note_prompt(existing_memories: str, tags: str, note: str) -> str:
    return (
        "You are a memory manager. A user has written a note. Process it into memories.\n\n"
        "## Existing memories (for dedup — do NOT create duplicates)\n"
        f"{existing_memories}\n\n"
        "## Known tags\n"
        f"{tags}\n\n"
        "## Note\n"
        f"{note}\n\n"
        "## Instructions\n"
        "If the note is short and self-contained (1-3 sentences), save it verbatim as a single memory.\n"
        "If it's longer or covers multiple topics, split it into separate memories.\n"
        "If it overlaps with an existing memory, update that memory instead.\n"
        "If the note contains a task or reminder, use the appropriate type.\n\n"
        "Respond with a JSON array of memory operations (no markdown fences).\n"
        "Return an empty array `[]` if the note contains nothing worth saving.\n\n"
        + _SHARED_SCHEMA_RULES
    )


def _build_summarize_prompt(existing_memories: str, tags: str, conversation: str) -> str:
    return (
        "You are a memory manager. Given a conversation, decide whether it contains anything worth remembering long-term.\n\n"
        "## Existing memories (for dedup — do NOT create duplicates)\n"
        f"{existing_memories}\n\n"
        "## Known tags\n"
        f"{tags}\n\n"
        "## Conversation\n"
        f"{conversation}\n\n"
        "## Instructions\n"
        "Respond with a JSON array of memory operations (no markdown fences).\n"
        "Return an empty array `[]` if the conversation contains nothing worth saving.\n\n"
        "Only save meaningful, long-term information: preferences, decisions, facts, instructions, tasks, or reminders.\n"
        "Trivial conversations (greetings, one-off questions, simple tool usage) should NOT be saved.\n"
        "If the conversation covers multiple unrelated topics, create separate operations for each.\n"
        "If the user or agent agreed to do something by a deadline, create a reminder. If it's an open-ended task, create a todo.\n\n"
        + _SHARED_SCHEMA_RULES
    )


def _format_existing_memories(memories: list[dict]) -> str:
    if not memories:
        return "(none)"
    lines = []
    for m in memories:
        content = m.get("content", "")
        preview = content[:200] + ("..." if len(content) > 200 else "")
        tags = ", ".join(m.get("tags", []))
        lines.append(f"- [{m.get('id')}] tags=[{tags}]: {preview}")
    return "\n".join(lines)


def _format_conversation(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        if role == "system":
            continue
        content = msg.get("content", "")
        # Truncate tool outputs
        if role == "tool" and len(content) > 500:
            content = content[:500] + "... [truncated]"
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


async def process_conversation(client, conversation_id: str, messages: list[dict], model: str | None = None) -> list[dict]:
    """Save conversation log and create/update high-level memories.

    Returns a list of memory metadata dicts (empty if nothing saved).
    """
    # 1. Always save the full conversation log
    save_conversation(conversation_id, messages)

    # 2. Skip if too short
    non_system = [m for m in messages if m.get("role") != "system"]
    if len(non_system) < 2:
        return []

    # 3. Gather context for dedup
    existing = list_all_memories()
    tags = get_tags()

    # 4. Build prompt and call LLM
    prompt = _build_summarize_prompt(
        existing_memories=_format_existing_memories(existing),
        tags=", ".join(tags) if tags else "(none)",
        conversation=_format_conversation(messages),
    )

    response = await client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = _strip_fences(response.choices[0].message.content.strip())
    operations = json.loads(raw)

    if not isinstance(operations, list) or not operations:
        return []

    return _apply_operations(operations, conversation_id=conversation_id)


async def process_note(client, note_text: str, model: str | None = None) -> list[dict]:
    """Process a user note into memories via LLM.

    Returns a list of memory metadata dicts (empty if nothing saved).
    """
    existing = list_all_memories()
    tags = get_tags()

    prompt = _build_note_prompt(
        existing_memories=_format_existing_memories(existing),
        tags=", ".join(tags) if tags else "(none)",
        note=note_text,
    )

    response = await client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = _strip_fences(response.choices[0].message.content.strip())
    operations = json.loads(raw)

    if not isinstance(operations, list) or not operations:
        return []

    return _apply_operations(operations)


def spawn_note_background(note_text: str) -> None:
    """Fire-and-forget: spawn a detached subprocess to process a note into memories."""
    _spawn(["--note"], {"note": note_text})


def spawn_background(conversation_id: str, messages: list[dict]) -> None:
    """Fire-and-forget: save conversation log and spawn a detached subprocess.

    The raw conversation log is saved synchronously (fast, no network).
    The LLM summarization runs in a detached subprocess that survives
    TUI exit and terminal closure.
    """
    save_conversation(conversation_id, messages)
    _spawn([], {"conversation_id": conversation_id, "messages": messages})


if __name__ == "__main__":
    import argparse as _argparse
    import asyncio
    from dotenv import load_dotenv
    from openai import AsyncOpenAI

    load_dotenv()

    _parser = _argparse.ArgumentParser()
    _parser.add_argument("file", help="Path to temp JSON file")
    _parser.add_argument("--note", action="store_true", help="Process as a note instead of conversation")
    _args = _parser.parse_args()

    try:
        with open(_args.file) as f:
            data = json.load(f)

        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        if _args.note:
            asyncio.run(process_note(client, data["note"]))
        else:
            asyncio.run(
                process_conversation(
                    client, data["conversation_id"], data["messages"]
                )
            )
    finally:
        try:
            os.unlink(_args.file)
        except OSError:
            pass
