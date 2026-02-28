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


# ---------------------------------------------------------------------------
# High-level: tagged summaries
# ---------------------------------------------------------------------------


def _write_memory_file(memory_id: str, tags: list[str], content: str, conversation_id: str | None = None, created: str | None = None) -> dict:
    """Write a high-level memory .md file with YAML frontmatter."""
    ensure_dirs()
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": memory_id,
        "tags": tags,
        "created": created or now,
        "updated": now,
    }
    if conversation_id:
        meta["conversation_id"] = conversation_id

    frontmatter = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    doc = f"---\n{frontmatter}\n---\n{content}\n"

    path = _HIGH_DIR / f"{memory_id}.md"
    path.write_text(doc)

    _add_tags(tags)
    return meta


def create_memory(content: str, tags: list[str], conversation_id: str | None = None) -> dict:
    """Create a new high-level memory and return its metadata."""
    memory_id = uuid4().hex[:12]
    return _write_memory_file(memory_id, tags, content, conversation_id)


def update_memory(memory_id: str, content: str | None = None, tags: list[str] | None = None) -> dict:
    """Update an existing memory's content and/or tags."""
    existing = _parse_memory_file(memory_id)
    if existing is None:
        raise FileNotFoundError(f"Memory '{memory_id}' not found")

    new_content = content if content is not None else existing["content"]
    new_tags = tags if tags is not None else existing["tags"]
    return _write_memory_file(memory_id, new_tags, new_content, existing.get("conversation_id"), existing["created"])


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


def search_memories(query: str | None = None, tags: list[str] | None = None) -> list[dict]:
    """Filter memories by keyword and/or tag. Returns id, tags, and a preview."""
    all_memories = list_all_memories()
    results = []
    for mem in all_memories:
        # Tag filter
        if tags:
            mem_tags = mem.get("tags", [])
            if not any(t in mem_tags for t in tags):
                continue
        # Keyword filter
        if query:
            content = mem.get("content", "")
            if query.lower() not in content.lower():
                continue
        # Build preview
        content = mem.get("content", "")
        preview = content[:200] + ("..." if len(content) > 200 else "")
        results.append({
            "id": mem.get("id"),
            "tags": mem.get("tags", []),
            "preview": preview,
            "conversation_id": mem.get("conversation_id"),
            "created": mem.get("created"),
            "updated": mem.get("updated"),
        })
    return results


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def get_tags() -> list[str]:
    """Read all known tags from tags.yaml."""
    ensure_dirs()
    data = yaml.safe_load(_TAGS_FILE.read_text())
    return data if isinstance(data, list) else []


def _add_tags(new_tags: list[str]) -> None:
    """Merge new tags into tags.yaml."""
    existing = set(get_tags())
    updated = sorted(existing | set(new_tags))
    _TAGS_FILE.write_text(yaml.dump(updated, default_flow_style=False))
