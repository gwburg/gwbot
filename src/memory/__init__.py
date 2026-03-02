"""Storage layer for the memory system.

Logs:      full conversation logs as JSONL       (~/.agent-memories/logs/)
Knowledge: tagged summaries as Markdown           (~/.agent-memories/knowledge/)
Tasks:     task lists as Markdown                 (~/.agent-memories/tasks/)
Archive:   completed tasks / retired knowledge    (~/.agent-memories/archive/)
Jobs:      scheduled job definitions              (~/.agent-memories/jobs/)
Tags:      single YAML file                       (~/.agent-memories/tags.yaml)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

_BASE_DIR = Path(os.environ.get("AGENT_MEMORY_DIR", Path.home() / ".agent-memories"))
_KNOWLEDGE_DIR = _BASE_DIR / "knowledge"
_TASKS_DIR = _BASE_DIR / "tasks"
_ARCHIVE_DIR = _BASE_DIR / "archive"
_LOGS_DIR = _BASE_DIR / "logs"
_JOBS_DIR = _BASE_DIR / "jobs"
_TAGS_FILE = _BASE_DIR / "tags.yaml"


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def ensure_dirs() -> None:
    """Create the memory directory tree and tags file if missing."""
    _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    _TASKS_DIR.mkdir(parents=True, exist_ok=True)
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    if not _TAGS_FILE.exists():
        _TAGS_FILE.write_text(yaml.dump([]))


# ---------------------------------------------------------------------------
# Conversation IDs
# ---------------------------------------------------------------------------


def new_conversation_id() -> str:
    return uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Conversation logs
# ---------------------------------------------------------------------------


def save_conversation(conversation_id: str, messages: list[dict]) -> None:
    """Write non-system messages as JSONL."""
    ensure_dirs()
    path = _LOGS_DIR / f"{conversation_id}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            if msg.get("role") == "system":
                continue
            f.write(json.dumps(msg) + "\n")


def read_conversation(conversation_id: str) -> str:
    """Read a conversation log and return its contents."""
    path = _LOGS_DIR / f"{conversation_id}.jsonl"
    if not path.exists():
        return f"Error: conversation '{conversation_id}' not found"
    return path.read_text()


def load_conversation(conversation_id: str) -> list[dict]:
    """Load a conversation log as a list of message dicts."""
    path = _LOGS_DIR / f"{conversation_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Conversation '{conversation_id}' not found")
    messages = []
    for line in path.read_text().splitlines():
        if line.strip():
            messages.append(json.loads(line))
    return messages


def list_conversations(limit: int = 0, offset: int = 0) -> list[dict]:
    """List saved conversations, newest first.

    Args:
        limit: Max number of results to return (0 = all).
        offset: Number of results to skip from the start.

    Returns list of dicts with id, preview (last user message),
    date (mtime), and estimated_tokens.
    """
    ensure_dirs()
    results = []
    for path in _LOGS_DIR.glob("*.jsonl"):
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
    if limit > 0:
        return results[offset:offset + limit]
    return results[offset:]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _parse_file(file_id: str, directory: Path) -> dict | None:
    """Parse a .md file into a dict with metadata + content."""
    path = directory / f"{file_id}.md"
    if not path.exists():
        return None
    return _parse_frontmatter(path.read_text())


def _write_file(meta: dict, content: str, *, directory: Path = _KNOWLEDGE_DIR) -> dict:
    """Write a .md file with YAML frontmatter.

    ``meta`` must contain at least ``id`` and ``tags``.
    ``created`` is set automatically if missing; ``updated`` is always refreshed.
    """
    ensure_dirs()
    now = datetime.now(timezone.utc).isoformat()
    meta.setdefault("created", now)
    meta["updated"] = now

    frontmatter = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    doc = f"---\n{frontmatter}\n---\n{content}\n"

    path = directory / f"{meta['id']}.md"
    path.write_text(doc)

    _add_tags(meta.get("tags", []))

    # Best-effort embedding — non-fatal on failure (skip for jobs)
    if directory != _JOBS_DIR:
        try:
            from memory.embeddings import compute_embedding, store_embedding

            vector = compute_embedding(content)
            if vector:
                store_embedding(meta["id"], vector)
        except Exception:
            pass

    return meta


def _build_result(mem: dict, score: float | None = None) -> dict:
    content = mem.get("content", "")
    result = dict(mem)
    result["preview"] = content[:200] + ("..." if len(content) > 200 else "")
    result.pop("content", None)
    if score is not None:
        result["score"] = round(score, 3)
    return result


def _hybrid_search(candidates: list[dict], query: str | None = None, tags: list[str] | None = None) -> list[dict]:
    """Hybrid search: tag filtering + semantic similarity + keyword bonus."""
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


def _list_dir(directory: Path) -> list[dict]:
    """Parse all .md files in a directory."""
    ensure_dirs()
    items = []
    for path in sorted(directory.glob("*.md")):
        parsed = _parse_frontmatter(path.read_text())
        if parsed:
            items.append(parsed)
    return items


def _delete_file(file_id: str, directory: Path) -> None:
    """Delete a file and its embedding."""
    path = directory / f"{file_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"'{file_id}' not found in {directory.name}/")
    path.unlink()
    try:
        from memory.embeddings import delete_embedding
        delete_embedding(file_id)
    except Exception:
        pass


def _move_file(file_id: str, src_dir: Path, dest_dir: Path, extra_content: str | None = None) -> dict:
    """Move a file between directories, optionally appending content."""
    existing = _parse_file(file_id, src_dir)
    if existing is None:
        raise FileNotFoundError(f"'{file_id}' not found in {src_dir.name}/")

    content = existing.pop("content", "")
    if extra_content:
        content = content.rstrip() + "\n\n" + extra_content

    result = _write_file(existing, content, directory=dest_dir)

    # Remove from source
    src_path = src_dir / f"{file_id}.md"
    src_path.unlink()

    return result


# ---------------------------------------------------------------------------
# Knowledge CRUD
# ---------------------------------------------------------------------------


def create_knowledge(content: str, tags: list[str], conversation_id: str | None = None) -> dict:
    """Create a new knowledge entry and return its metadata."""
    meta: dict = {"id": uuid4().hex[:12], "tags": tags}
    if conversation_id:
        meta["conversation_id"] = conversation_id
    return _write_file(meta, content, directory=_KNOWLEDGE_DIR)


def update_knowledge(knowledge_id: str, content: str | None = None, tags: list[str] | None = None) -> dict:
    """Update an existing knowledge entry's content and/or tags."""
    existing = _parse_file(knowledge_id, _KNOWLEDGE_DIR)
    if existing is None:
        raise FileNotFoundError(f"Knowledge '{knowledge_id}' not found")

    new_content = content if content is not None else existing.pop("content", "")
    existing.pop("content", None)
    if tags is not None:
        existing["tags"] = tags
    return _write_file(existing, new_content, directory=_KNOWLEDGE_DIR)


def delete_knowledge(knowledge_id: str) -> None:
    """Delete a knowledge entry."""
    _delete_file(knowledge_id, _KNOWLEDGE_DIR)


def read_knowledge(knowledge_id: str) -> str:
    """Read the full .md file for a knowledge entry."""
    path = _KNOWLEDGE_DIR / f"{knowledge_id}.md"
    if not path.exists():
        return f"Error: knowledge '{knowledge_id}' not found"
    return path.read_text()


def list_all_knowledge() -> list[dict]:
    """Parse all knowledge entries."""
    return _list_dir(_KNOWLEDGE_DIR)


def search_knowledge(query: str | None = None, tags: list[str] | None = None) -> list[dict]:
    """Hybrid search over knowledge entries."""
    return _hybrid_search(list_all_knowledge(), query, tags)


def archive_knowledge(knowledge_id: str) -> dict:
    """Move a knowledge entry to the archive."""
    return _move_file(knowledge_id, _KNOWLEDGE_DIR, _ARCHIVE_DIR)


# ---------------------------------------------------------------------------
# Tasks CRUD
# ---------------------------------------------------------------------------


def create_task(content: str, tags: list[str], owner: str = "user", due: str | None = None, job: str | None = None) -> dict:
    """Create a new task and return its metadata."""
    meta: dict = {"id": uuid4().hex[:12], "tags": tags, "owner": owner}
    if due:
        meta["due"] = due
    if job:
        meta["job"] = job
    return _write_file(meta, content, directory=_TASKS_DIR)


def update_task(task_id: str, content: str | None = None, tags: list[str] | None = None, due: str | None = None) -> dict:
    """Update an existing task's content, tags, and/or due date."""
    existing = _parse_file(task_id, _TASKS_DIR)
    if existing is None:
        raise FileNotFoundError(f"Task '{task_id}' not found")

    new_content = content if content is not None else existing.pop("content", "")
    existing.pop("content", None)
    if tags is not None:
        existing["tags"] = tags
    if due is not None:
        existing["due"] = due
    return _write_file(existing, new_content, directory=_TASKS_DIR)


def delete_task(task_id: str) -> None:
    """Delete a task."""
    _delete_file(task_id, _TASKS_DIR)


def read_task(task_id: str) -> str:
    """Read the full .md file for a task."""
    path = _TASKS_DIR / f"{task_id}.md"
    if not path.exists():
        return f"Error: task '{task_id}' not found"
    return path.read_text()


def list_all_tasks() -> list[dict]:
    """Parse all task files."""
    return _list_dir(_TASKS_DIR)


def complete_task_item(task_id: str, item: str) -> dict:
    """Mark a checklist item as [x] in a task file.

    Returns the updated metadata.
    """
    existing = _parse_file(task_id, _TASKS_DIR)
    if existing is None:
        raise FileNotFoundError(f"Task '{task_id}' not found")

    content = existing.pop("content", "")
    lines = content.splitlines()
    item_lower = item.lower()
    matched = next(
        (i for i, l in enumerate(lines)
         if l.strip().startswith("- [ ]") and item_lower in l.lower()),
        None,
    )
    if matched is None:
        raise ValueError(f"Item '{item}' not found in task '{task_id}'")

    # Replace - [ ] with - [x]
    lines[matched] = lines[matched].replace("- [ ]", "- [x]", 1)
    return _write_file(existing, "\n".join(lines), directory=_TASKS_DIR)


def archive_task(task_id: str, notes: str | None = None) -> dict:
    """Move a task to the archive, optionally appending completion notes."""
    extra = f"**Completion notes:** {notes}" if notes else None
    return _move_file(task_id, _TASKS_DIR, _ARCHIVE_DIR, extra_content=extra)


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def list_archive() -> list[dict]:
    """Parse all archived files."""
    return _list_dir(_ARCHIVE_DIR)


def search_archive(query: str | None = None, tags: list[str] | None = None) -> list[dict]:
    """Hybrid search over archived entries."""
    return _hybrid_search(list_archive(), query, tags)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def create_job(prompt: str, schedule: str, tags: list[str] | None = None, max_iterations: int = 5) -> dict:
    """Create a new scheduled job and return its metadata."""
    meta: dict = {
        "id": uuid4().hex[:12],
        "tags": tags or [],
        "type": "job",
        "schedule": schedule,
        "enabled": True,
        "max_iterations": max_iterations,
    }
    return _write_file(meta, prompt, directory=_JOBS_DIR)


def list_jobs(include_disabled: bool = False) -> list[dict]:
    """Return all jobs from the jobs directory."""
    ensure_dirs()
    jobs = []
    for path in sorted(_JOBS_DIR.glob("*.md")):
        parsed = _parse_frontmatter(path.read_text())
        if parsed:
            jobs.append(parsed)
    if not include_disabled:
        jobs = [j for j in jobs if j.get("enabled", True)]
    return jobs


def _parse_job_file(job_id: str) -> dict | None:
    """Parse a job .md file into a dict with metadata + content."""
    return _parse_file(job_id, _JOBS_DIR)


def delete_job(job_id: str) -> None:
    """Delete a job file."""
    path = _JOBS_DIR / f"{job_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"Job '{job_id}' not found")
    path.unlink()


def _update_job(job_id: str, **overrides) -> dict:
    """Read an existing job and re-write it with field overrides."""
    existing = _parse_job_file(job_id)
    if existing is None:
        raise FileNotFoundError(f"Job '{job_id}' not found")
    content = existing.pop("content", "")
    existing.update(overrides)
    return _write_file(existing, content, directory=_JOBS_DIR)


def update_job_run(job_id: str) -> dict:
    """Set last_run to now on a job."""
    return _update_job(job_id, last_run=datetime.now(timezone.utc).isoformat())


def toggle_job(job_id: str, enabled: bool) -> dict:
    """Enable or disable a job."""
    return _update_job(job_id, enabled=enabled)


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


def delete_tag(tag: str) -> int:
    """Remove a tag from tags.yaml. Returns number of entries still using it."""
    existing = get_tags()
    updated = [t for t in existing if t != tag]
    _TAGS_FILE.write_text(yaml.dump(updated, default_flow_style=False))
    all_items = list_all_knowledge() + list_all_tasks()
    still_using = sum(1 for m in all_items if tag in m.get("tags", []))
    return still_using


