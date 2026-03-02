"""Background agent that summarizes conversations into knowledge and tasks.

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
    create_knowledge,
    create_task,
    get_tags,
    list_all_knowledge,
    list_all_tasks,
    save_conversation,
    update_knowledge,
)

DEFAULT_MODEL = models.SONNET


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
                meta = update_knowledge(
                    op["duplicate_of"],
                    content=op["updated_content"],
                    tags=op.get("tags"),
                )
                meta["action"] = "updated"
                results.append(meta)
                continue
            except FileNotFoundError:
                pass  # Fall through to create

        op_type = op.get("type", "knowledge")

        if op_type == "task":
            kwargs = {
                "content": op["summary"],
                "tags": op.get("tags", []),
            }
            if op.get("owner"):
                kwargs["owner"] = op["owner"]
            if op.get("due"):
                kwargs["due"] = op["due"]
            meta = create_task(**kwargs)
        else:
            kwargs = {
                "content": op["summary"],
                "tags": op.get("tags", []),
            }
            if conversation_id:
                kwargs["conversation_id"] = conversation_id
            meta = create_knowledge(**kwargs)

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

# Shared: operation schema and type definitions (used by both prompts).
_SCHEMA_FIELDS = """\
Each element in the array is an operation object:
{
  "type": "knowledge",       // "knowledge" (default) or "task"
  "summary": "...",          // the content to save
  "tags": ["tag1"],          // descriptive tags; reuse existing ones when possible
  "owner": null,             // "user" or "agent" — for task only
  "due": null,               // YYYY-MM-DD — optional deadline for task
  "duplicate_of": null,      // ID of existing knowledge to update instead of creating
  "updated_content": null    // merged content when updating a duplicate
}

Type guide:
- "knowledge": a fact, preference, decision, or instruction worth remembering long-term.
- "task": action items (markdown checkboxes). Set due for deadline-sensitive items. owner="user" or "agent".
- "job": NEVER create this type — jobs are only created via the scheduler tools.

Dedup rules:
- If content overlaps with an existing entry, set duplicate_of + updated_content to merge; don't create a duplicate.
- Use existing tags when possible; only invent new ones if truly needed.
- Omit null/false fields (they are optional)."""


def _build_note_prompt(existing_entries: str, tags: str, note: str) -> str:
    return (
        "You are a memory manager. The user has written a note — save its contents.\n\n"
        "## Existing entries (for dedup — do NOT create duplicates)\n"
        f"{existing_entries}\n\n"
        "## Known tags\n"
        f"{tags}\n\n"
        "## Note\n"
        f"{note}\n\n"
        "## Instructions\n"
        "The user deliberately wrote this, so everything in it is worth saving.\n"
        "Infer the appropriate type from structure and language:\n"
        "- A list of action items, tasks, or ideas → a single `task` with all items as markdown checkboxes.\n"
        "  Format: `- [ ] item one\\n- [ ] item two\\n- [ ] item three`.\n"
        "  Optionally prepend a short title line before the checklist.\n"
        "  Do NOT create one task per item — the whole list is one task.\n"
        "- Something with a deadline or 'by [date]' phrasing → `task` with a `due` date.\n"
        "- A fact, preference, decision, or instruction → `knowledge`.\n"
        "- Mixed notes: split into separate operations by topic and intent.\n\n"
        "Return `[]` only if the note is empty or completely nonsensical.\n\n"
        "Respond with a JSON array of operations (no markdown fences).\n\n"
        + _SCHEMA_FIELDS
    )


def _build_summarize_prompt(existing_entries: str, tags: str, conversation: str) -> str:
    return (
        "You are a memory manager. Given a conversation, decide whether it contains anything worth remembering long-term.\n\n"
        "## Existing entries (for dedup — do NOT create duplicates)\n"
        f"{existing_entries}\n\n"
        "## Known tags\n"
        f"{tags}\n\n"
        "## Conversation\n"
        f"{conversation}\n\n"
        "## Instructions\n"
        "Only save meaningful, long-term information: preferences, decisions, facts, instructions, or tasks.\n"
        "Trivial exchanges (greetings, one-off questions, simple tool usage) should NOT be saved.\n"
        "If the conversation covers multiple unrelated topics, create separate operations for each.\n"
        "If the user or agent committed to something by a deadline, create a task with a due date.\n"
        "If there are open-ended action items with no deadline, group related ones into a single `task` using markdown checkboxes (`- [ ] item`). Don't create a separate task per item.\n"
        "Return `[]` if the conversation contains nothing worth saving.\n\n"
        "Respond with a JSON array of operations (no markdown fences).\n\n"
        + _SCHEMA_FIELDS
    )


def _format_existing_entries(entries: list[dict]) -> str:
    if not entries:
        return "(none)"
    lines = []
    for e in entries:
        content = e.get("content", "")
        tags = ", ".join(e.get("tags", []))
        eid = e.get("id")
        owner = e.get("owner")
        if owner:
            # Task
            lines.append(f"- [{eid}] task owner={owner} tags=[{tags}]:\n{content}")
        else:
            preview = content[:200] + ("..." if len(content) > 200 else "")
            lines.append(f"- [{eid}] knowledge tags=[{tags}]: {preview}")
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
    """Save conversation log and create/update knowledge and tasks.

    Returns a list of metadata dicts (empty if nothing saved).
    """
    # 1. Always save the full conversation log
    save_conversation(conversation_id, messages)

    # 2. Skip if too short
    non_system = [m for m in messages if m.get("role") != "system"]
    if len(non_system) < 2:
        return []

    # 3. Gather context for dedup
    existing = list_all_knowledge() + list_all_tasks()
    tags = get_tags()

    # 4. Build prompt and call LLM
    prompt = _build_summarize_prompt(
        existing_entries=_format_existing_entries(existing),
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
    """Process a user note into knowledge/tasks via LLM.

    Returns a list of metadata dicts (empty if nothing saved).
    """
    existing = list_all_knowledge() + list_all_tasks()
    tags = get_tags()

    prompt = _build_note_prompt(
        existing_entries=_format_existing_entries(existing),
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
    """Fire-and-forget: spawn a detached subprocess to process a note."""
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
