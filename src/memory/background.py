"""Background agent that summarizes conversations into high-level memories."""

import json

import models
from memory import (
    create_memory,
    get_tags,
    list_all_memories,
    save_conversation,
    update_memory,
)

DEFAULT_MODEL = models.MINIMAX

_SUMMARIZE_PROMPT = """\
You are a memory manager. Given a conversation, decide whether it contains anything worth remembering long-term.

## Existing memories (for dedup — do NOT create duplicates)
{existing_memories}

## Known tags
{tags}

## Conversation
{conversation}

## Instructions
Respond with a single JSON object (no markdown fences):
{{
  "should_save": true/false,
  "summary": "concise summary of the key information",
  "tags": ["tag1", "tag2"],
  "duplicate_of": null or "memory_id_to_update",
  "updated_content": null or "merged content if updating a duplicate"
}}

Rules:
- Only set should_save=true if the conversation contains meaningful, long-term information (preferences, decisions, facts, instructions).
- Trivial conversations (greetings, one-off questions, simple tool usage) should NOT be saved.
- If the information overlaps with an existing memory, set duplicate_of to its ID and provide updated_content that merges the old and new info.
- Use existing tags when possible; only invent new tags if truly needed.
- Keep summaries concise — one to three sentences."""


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


async def process_conversation(client, conversation_id: str, messages: list[dict], model: str | None = None) -> dict | None:
    """Save conversation log and optionally create/update a high-level memory.

    Returns memory metadata dict on success, None if skipped.
    """
    # 1. Always save the full conversation log
    save_conversation(conversation_id, messages)

    # 2. Skip if too short
    non_system = [m for m in messages if m.get("role") != "system"]
    if len(non_system) < 2:
        return None

    # 3. Gather context for dedup
    existing = list_all_memories()
    tags = get_tags()

    # 4. Build prompt and call LLM
    prompt = _SUMMARIZE_PROMPT.format(
        existing_memories=_format_existing_memories(existing),
        tags=", ".join(tags) if tags else "(none)",
        conversation=_format_conversation(messages),
    )

    response = await client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    result = json.loads(raw)

    # 5. Skip if nothing worth saving
    if not result.get("should_save"):
        return None

    # 6. Create or update memory
    if result.get("duplicate_of") and result.get("updated_content"):
        try:
            meta = update_memory(
                result["duplicate_of"],
                content=result["updated_content"],
                tags=result.get("tags"),
            )
            meta["action"] = "updated"
            return meta
        except FileNotFoundError:
            pass  # Fall through to create

    meta = create_memory(
        content=result["summary"],
        tags=result.get("tags", []),
        conversation_id=conversation_id,
    )
    meta["action"] = "created"
    return meta
