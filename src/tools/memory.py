"""Memory tools — search, read, and create persistent memories."""

import json

from memory import (
    create_memory as _create_memory,
    get_tags as _get_tags,
    read_conversation as _read_conversation,
    read_memory as _read_memory,
    search_memories as _search_memories,
    update_memory as _update_memory,
)

TAG = "memory"
CATEGORY = "Memory — search, read, and create persistent memories across conversations"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def search_memories(query: str | None = None, tags: str | None = None) -> str:
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = _search_memories(query=query, tags=tag_list)
    if not results:
        return "No memories found."
    return json.dumps(results, indent=2)


def read_memory(memory_id: str) -> str:
    return _read_memory(memory_id)


def read_conversation(conversation_id: str) -> str:
    return _read_conversation(conversation_id)


def create_memory(content: str, tags: str, knowledge_tag: str | None = None) -> str:
    tag_list = [t.strip() for t in tags.split(",")]
    meta = _create_memory(content, tag_list, knowledge_tag=knowledge_tag)
    return json.dumps(meta, indent=2)


def update_memory(memory_id: str, content: str | None = None, tags: str | None = None, knowledge_tag: str | None = None) -> str:
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    try:
        meta = _update_memory(memory_id, content=content, tags=tag_list, knowledge_tag=knowledge_tag)
    except FileNotFoundError as e:
        return str(e)
    return json.dumps(meta, indent=2)


def list_tags() -> str:
    tags = _get_tags()
    if not tags:
        return "No tags yet."
    return ", ".join(tags)


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


tools = [
    {
        "type": "function",
        "function": {
            "name": "search_memories",
            "description": (
                "Search high-level memories by keyword and/or tags. "
                "Returns id, tags, and a preview for each match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search for in memory content",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags to filter by (e.g. 'preference,food')",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory",
            "description": "Read the full content of a high-level memory by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "The memory ID to read",
                    },
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_conversation",
            "description": "Read the full low-level conversation log by its conversation ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {
                        "type": "string",
                        "description": "The conversation ID to read",
                    },
                },
                "required": ["conversation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_memory",
            "description": (
                "Create a new high-level memory. Before creating, always search_memories first "
                "to avoid duplicates. If a similar memory exists, use update_memory instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory content (a concise summary or fact)",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated descriptive tags (e.g. 'preference,food'). Use existing tags when possible.",
                    },
                    "knowledge_tag": {
                        "type": "string",
                        "enum": ["always", "shell", "editor", "memory", "monarch"],
                        "description": (
                            "Optional. Auto-injects this memory as domain knowledge. "
                            "'always' = loaded into system prompt at startup. "
                            "Tool-category tags (shell, editor, memory, monarch) = injected into "
                            "the first tool result from that category each conversation."
                        ),
                    },
                },
                "required": ["content", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory",
            "description": "Update an existing memory's content and/or tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "The memory ID to update",
                    },
                    "content": {
                        "type": "string",
                        "description": "New content to replace the existing content",
                    },
                    "tags": {
                        "type": "string",
                        "description": "New comma-separated descriptive tags to replace existing tags",
                    },
                    "knowledge_tag": {
                        "type": "string",
                        "enum": ["always", "shell", "editor", "memory", "monarch"],
                        "description": (
                            "Optional. Auto-injects this memory as domain knowledge. "
                            "'always' = loaded into system prompt at startup. "
                            "Tool-category tags = injected into first tool result from that category."
                        ),
                    },
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tags",
            "description": "List all known memory tags.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


TOOL_MAPPING = {
    "search_memories": search_memories,
    "read_memory": read_memory,
    "read_conversation": read_conversation,
    "create_memory": create_memory,
    "update_memory": update_memory,
    "list_tags": list_tags,
}
