"""Storage layer for the two-tier memory system.

Low-level:  full conversation logs as JSONL  (~/.agent-memories/low/)
High-level: tagged summaries as Markdown     (~/.agent-memories/high/)
Tags:       single YAML file                 (~/.agent-memories/tags.yaml)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

_BASE_DIR = Path(os.environ.get("AGENT_MEMORY_DIR", Path.home() / ".agent-memories"))
_HIGH_DIR = _BASE_DIR / "high"
_LOW_DIR = _BASE_DIR / "low"
_TAGS_FILE = _BASE_DIR / "tags.yaml"


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def ensure_dirs() -> None:
    """Create the memory directory tree and tags file if missing."""
    _HIGH_DIR.mkdir(parents=True, exist_ok=True)
    _LOW_DIR.mkdir(parents=True, exist_ok=True)
    if not _TAGS_FILE.exists():
        _TAGS_FILE.write_text(yaml.dump([]))


# ---------------------------------------------------------------------------
# Conversation IDs
# ---------------------------------------------------------------------------


def new_conversation_id() -> str:
    return uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Low-level: conversation logs
# ---------------------------------------------------------------------------


def save_conversation(conversation_id: str, messages: list[dict]) -> None:
    """Write non-system messages as JSONL."""
    ensure_dirs()
    path = _LOW_DIR / f"{conversation_id}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            if msg.get("role") == "system":
                continue
            f.write(json.dumps(msg) + "\n")


def read_conversation(conversation_id: str) -> str:
    """Read a conversation log and return its contents."""
    path = _LOW_DIR / f"{conversation_id}.jsonl"
    if not path.exists():
        return f"Error: conversation '{conversation_id}' not found"
    return path.read_text()


def load_conversation(conversation_id: str) -> list[dict]:
    """Load a conversation log as a list of message dicts."""
    path = _LOW_DIR / f"{conversation_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Conversation '{conversation_id}' not found")
    messages = []
    for line in path.read_text().splitlines():
        if line.strip():
            messages.append(json.loads(line))
    return messages


def list_conversations() -> list[dict]:
    """List all saved conversations, newest first.

    Returns list of dicts with id, preview (last user message),
    date (mtime), and estimated_tokens.
    """
    ensure_dirs()
    results = []
    for path in _LOW_DIR.glob("*.jsonl"):
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        total_chars = 0
        last_user_msg = ""
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            total_chars += len(line)
            try:
                msg = json.loads(line)
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "")
            except json.JSONDecodeError:
                continue
        preview = last_user_msg[:80] + ("..." if len(last_user_msg) > 80 else "")
        results.append({
            "id": path.stem,
            "preview": preview,
            "date": mtime,
            "estimated_tokens": total_chars // 4,
        })
    results.sort(key=lambda r: r["date"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# High-level: tagged summaries
# ---------------------------------------------------------------------------


def _write_memory_file(memory_id: str, tags: list[str], content: str, conversation_id: str | None = None, created: str | None = None, knowledge_tag: str | None = None, type: str = "memory", deadline: str | None = None, owner: str | None = None) -> dict:
    """Write a high-level memory .md file with YAML frontmatter."""
    ensure_dirs()
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": memory_id,
        "tags": tags,
        "created": created or now,
        "updated": now,
    }
    if type != "memory":
        meta["type"] = type
    if deadline:
        meta["deadline"] = deadline
    if owner:
        meta["owner"] = owner
    if knowledge_tag:
        meta["knowledge_tag"] = knowledge_tag
    if conversation_id:
        meta["conversation_id"] = conversation_id

    frontmatter = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    doc = f"---\n{frontmatter}\n---\n{content}\n"

    path = _HIGH_DIR / f"{memory_id}.md"
    path.write_text(doc)

    _add_tags(tags)

    # Best-effort embedding — non-fatal on failure
    try:
        from memory.embeddings import compute_embedding, store_embedding

        vector = compute_embedding(content)
        if vector:
            store_embedding(memory_id, vector)
    except Exception:
        pass

    return meta


def create_memory(content: str, tags: list[str], conversation_id: str | None = None, knowledge_tag: str | None = None, type: str = "memory", deadline: str | None = None, owner: str | None = None) -> dict:
    """Create a new high-level memory and return its metadata."""
    memory_id = uuid4().hex[:12]
    return _write_memory_file(memory_id, tags, content, conversation_id, knowledge_tag=knowledge_tag, type=type, deadline=deadline, owner=owner)


def update_memory(memory_id: str, content: str | None = None, tags: list[str] | None = None, knowledge_tag: str | None = None, deadline: str | None = None) -> dict:
    """Update an existing memory's content and/or tags."""
    existing = _parse_memory_file(memory_id)
    if existing is None:
        raise FileNotFoundError(f"Memory '{memory_id}' not found")

    new_content = content if content is not None else existing["content"]
    new_tags = tags if tags is not None else existing["tags"]
    new_knowledge_tag = knowledge_tag if knowledge_tag is not None else existing.get("knowledge_tag")
    new_deadline = deadline if deadline is not None else existing.get("deadline")
    return _write_memory_file(memory_id, new_tags, new_content, existing.get("conversation_id"), existing["created"], knowledge_tag=new_knowledge_tag, type=existing.get("type", "memory"), deadline=new_deadline, owner=existing.get("owner"))


def delete_memory(memory_id: str) -> None:
    """Delete a memory file and its embedding."""
    path = _HIGH_DIR / f"{memory_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"Memory '{memory_id}' not found")
    path.unlink()
    try:
        from memory.embeddings import delete_embedding
        delete_embedding(memory_id)
    except Exception:
        pass


def list_tasks() -> list[dict]:
    """Return all todo/reminder memories, reminders sorted by deadline first."""
    tasks = [m for m in list_all_memories() if m.get("type") in ("todo", "reminder")]
    # Reminders with deadline first (sorted by deadline), then todos
    reminders = sorted(
        [t for t in tasks if t.get("type") == "reminder"],
        key=lambda t: t.get("deadline") or "",
    )
    todos = [t for t in tasks if t.get("type") == "todo"]
    return reminders + todos


def read_memory(memory_id: str) -> str:
    """Read the full .md file for a memory."""
    path = _HIGH_DIR / f"{memory_id}.md"
    if not path.exists():
        return f"Error: memory '{memory_id}' not found"
    return path.read_text()


def _parse_memory_file(memory_id: str) -> dict | None:
    """Parse a memory .md file into a dict with metadata + content."""
    path = _HIGH_DIR / f"{memory_id}.md"
    if not path.exists():
        return None
    text = path.read_text()
    return _parse_frontmatter(text)


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from a markdown string."""
    if not text.startswith("---"):
        return {"content": text}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"content": text}
    meta = yaml.safe_load(parts[1]) or {}
    meta["content"] = parts[2].strip()
    return meta


def list_all_memories() -> list[dict]:
    """Parse all high-level memories and return their metadata + content."""
    ensure_dirs()
    memories = []
    for path in sorted(_HIGH_DIR.glob("*.md")):
        text = path.read_text()
        parsed = _parse_frontmatter(text)
        if parsed:
            memories.append(parsed)
    return memories


def _build_result(mem: dict, score: float | None = None) -> dict:
    content = mem.get("content", "")
    result = {
        "id": mem.get("id"),
        "tags": mem.get("tags", []),
        "preview": content[:200] + ("..." if len(content) > 200 else ""),
        "conversation_id": mem.get("conversation_id"),
        "created": mem.get("created"),
        "updated": mem.get("updated"),
    }
    if score is not None:
        result["score"] = round(score, 3)
    return result


def search_memories(query: str | None = None, tags: list[str] | None = None) -> list[dict]:
    """Hybrid search: tag filtering + semantic similarity + keyword bonus."""
    candidates = list_all_memories()

    # Tag filter (cheap, do first)
    if tags:
        candidates = [m for m in candidates if any(t in m.get("tags", []) for t in tags)]

    if not query:
        return [_build_result(m) for m in candidates]

    # Try to compute query embedding for semantic search
    query_vec = None
    stored_embeddings: dict[str, list[float]] = {}
    try:
        from memory.embeddings import (
            compute_embedding,
            cosine_similarity,
            get_all_embeddings,
        )

        query_vec = compute_embedding(query)
        if query_vec:
            stored_embeddings = get_all_embeddings()
    except Exception:
        pass

    scored: list[tuple[float, dict]] = []
    for mem in candidates:
        mid = mem.get("id")
        content = mem.get("content", "")

        keyword_match = query.lower() in content.lower()

        sim = 0.0
        if query_vec and mid in stored_embeddings:
            sim = cosine_similarity(query_vec, stored_embeddings[mid])

        score = sim + (0.3 if keyword_match else 0.0)

        if keyword_match or sim >= 0.3:
            scored.append((score, mem))

    scored.sort(key=lambda x: -x[0])
    return [_build_result(m, score=s) for s, m in scored]


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def get_tags() -> list[str]:
    """Read all known tags from tags.yaml."""
    ensure_dirs()
    data = yaml.safe_load(_TAGS_FILE.read_text())
    return data if isinstance(data, list) else []


def get_knowledge(tag: str) -> list[dict]:
    """Return all memories whose knowledge_tag matches the given tag."""
    return [m for m in list_all_memories() if m.get("knowledge_tag") == tag]


def _add_tags(new_tags: list[str]) -> None:
    """Merge new tags into tags.yaml."""
    existing = set(get_tags())
    updated = sorted(existing | set(new_tags))
    _TAGS_FILE.write_text(yaml.dump(updated, default_flow_style=False))
