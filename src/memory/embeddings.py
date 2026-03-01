"""Embedding storage and computation for semantic memory search."""

import os
import sqlite3
import struct
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = Path(os.environ.get("AGENT_MEMORY_DIR", Path.home() / ".agent-memories"))
_DB_PATH = _BASE_DIR / "embeddings.db"
_EMBED_MODEL = "openai/text-embedding-3-small"
_API_URL = "https://openrouter.ai/api/v1/embeddings"


def _init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            memory_id TEXT PRIMARY KEY,
            vector BLOB NOT NULL,
            model TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


_init_db()


def _get_db() -> sqlite3.Connection:
    return sqlite3.connect(str(_DB_PATH))


def _pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def compute_embedding(text: str) -> list[float] | None:
    """Call OpenRouter embeddings API synchronously. Returns None on failure."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.post(
            _API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": _EMBED_MODEL, "input": text},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception:
        return None


def store_embedding(memory_id: str, vector: list[float]) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (memory_id, vector, model) VALUES (?, ?, ?)",
        (memory_id, _pack_vector(vector), _EMBED_MODEL),
    )
    conn.commit()
    conn.close()


def get_embedding(memory_id: str) -> list[float] | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT vector FROM embeddings WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    conn.close()
    return _unpack_vector(row[0]) if row else None


def get_all_embeddings() -> dict[str, list[float]]:
    conn = _get_db()
    rows = conn.execute("SELECT memory_id, vector FROM embeddings").fetchall()
    conn.close()
    return {mid: _unpack_vector(blob) for mid, blob in rows}


def delete_embedding(memory_id: str) -> None:
    conn = _get_db()
    conn.execute("DELETE FROM embeddings WHERE memory_id = ?", (memory_id,))
    conn.commit()
    conn.close()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def backfill_embeddings() -> int:
    """Compute embeddings for any memories missing from the DB. Returns count."""
    from memory import list_all_memories

    memories = list_all_memories()
    stored = get_all_embeddings()
    count = 0
    for mem in memories:
        mid = mem.get("id")
        if mid and mid not in stored:
            vec = compute_embedding(mem.get("content", ""))
            if vec:
                store_embedding(mid, vec)
                count += 1
    return count
