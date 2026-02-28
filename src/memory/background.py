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

_SUMMARIZE_PROMPT = """\
You are a memory manager. Given a conversation, decide whether it contains anything worth remembering long-term.

## Existing memories (for dedup — do NOT create duplicates)
{existing_memories}

## Known tags
{tags}

## Conversation
{conversation}

## Instructions
Respond with a JSON array of memory operations (no markdown fences). Each element is an object:
{{
  "summary": "concise summary of one distinct piece of information",
  "tags": ["tag1", "tag2"],
  "duplicate_of": null or "memory_id_to_update",
  "updated_content": null or "merged content if updating a duplicate"
}}

Return an empty array `[]` if the conversation contains nothing worth saving.

Rules:
- Only save meaningful, long-term information (preferences, decisions, facts, instructions).
- Trivial conversations (greetings, one-off questions, simple tool usage) should NOT be saved.
- Each memory should capture ONE distinct topic or fact. If the conversation covers multiple unrelated topics, create separate memories for each.
- If information overlaps with an existing memory, set duplicate_of to its ID and provide updated_content that merges the old and new info.
- Use existing tags when possible; only invent new tags if truly needed.
- Keep summaries concise — one to three sentences each."""


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

    operations = json.loads(raw)

    if not isinstance(operations, list) or not operations:
        return []

    # 5. Process each memory operation
    results = []
    for op in operations:
        if op.get("duplicate_of") and op.get("updated_content"):
            try:
                meta = update_memory(
                    op["duplicate_of"],
                    content=op["updated_content"],
                    tags=op.get("tags"),
                )
                meta["action"] = "updated"
                results.append(meta)
                continue
            except FileNotFoundError:
                pass  # Fall through to create

        meta = create_memory(
            content=op["summary"],
            tags=op.get("tags", []),
            conversation_id=conversation_id,
        )
        meta["action"] = "created"
        results.append(meta)

    return results


def spawn_background(conversation_id: str, messages: list[dict]) -> None:
    """Fire-and-forget: save conversation log and spawn a detached subprocess.

    The raw conversation log is saved synchronously (fast, no network).
    The LLM summarization runs in a detached subprocess that survives
    TUI exit and terminal closure.
    """
    # Save the raw conversation log immediately (no network, fast)
    save_conversation(conversation_id, messages)

    # Write conversation data to a temp file (subprocess will clean it up)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="agent_conv_", delete=False
    )
    json.dump({"conversation_id": conversation_id, "messages": messages}, tmp)
    tmp.close()

    # Launch detached subprocess that runs this module's __main__ block
    subprocess.Popen(
        [sys.executable, "-m", "memory.background", tmp.name],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    from openai import AsyncOpenAI

    load_dotenv()

    conv_file = sys.argv[1]
    try:
        with open(conv_file) as f:
            data = json.load(f)

        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        asyncio.run(
            process_conversation(
                client, data["conversation_id"], data["messages"]
            )
        )
    finally:
        # Always clean up the temp file
        try:
            os.unlink(conv_file)
        except OSError:
            pass
