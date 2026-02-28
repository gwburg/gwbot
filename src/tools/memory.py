"""Memory tools — search, read, and create persistent memories."""

import json

from memory import (
    complete_recurring_task as _complete_recurring,
    create_memory as _create_memory,
    delete_memory as _delete_memory,
    get_tags as _get_tags,
    list_tasks as _list_tasks,
    read_conversation as _read_conversation,
    read_memory as _read_memory,
    search_memories as _search_memories,
    update_memory as _update_memory,
    _parse_memory_file,
)

TAG = "memory"
CATEGORY = "Memory — search, read, and create persistent memories across conversations"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _parse_tags(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",")]


def search_memories(query: str | None = None, tags: str | None = None) -> str:
    tag_list = _parse_tags(tags) if tags else None
    results = _search_memories(query=query, tags=tag_list)
    if not results:
        return "No memories found."
    return json.dumps(results, indent=2)


def read_memory(memory_id: str) -> str:
    return _read_memory(memory_id)


def read_conversation(conversation_id: str) -> str:
    return _read_conversation(conversation_id)


def create_memory(content: str, tags: str, knowledge_tag: str | None = None) -> str:
    tag_list = _parse_tags(tags)
    meta = _create_memory(content, tag_list, knowledge_tag=knowledge_tag)
    return json.dumps(meta, indent=2)


def update_memory(memory_id: str, content: str | None = None, tags: str | None = None, knowledge_tag: str | None = None) -> str:
    tag_list = _parse_tags(tags) if tags else None
    try:
        meta = _update_memory(memory_id, content=content, tags=tag_list, knowledge_tag=knowledge_tag)
    except FileNotFoundError as e:
        return str(e)
    return json.dumps(meta, indent=2)


def delete_memory(memory_id: str) -> str:
    try:
        _delete_memory(memory_id)
    except FileNotFoundError as e:
        return str(e)
    return f"Memory '{memory_id}' deleted."


def list_tags() -> str:
    tags = _get_tags()
    if not tags:
        return "No tags yet."
    return ", ".join(tags)


def create_todo(content: str, tags: str, owner: str = "user") -> str:
    tag_list = _parse_tags(tags)
    meta = _create_memory(content, tag_list, type="todo", owner=owner)
    return json.dumps(meta, indent=2)


def create_reminder(content: str, tags: str, deadline: str, owner: str = "user", recurring: bool = False) -> str:
    tag_list = _parse_tags(tags)
    meta = _create_memory(content, tag_list, type="reminder", deadline=deadline, owner=owner, recurring=recurring)
    return json.dumps(meta, indent=2)


def complete_task(memory_id: str, item: str | None = None) -> str:
    try:
        existing = _parse_memory_file(memory_id)
        if existing is None:
            return f"Memory '{memory_id}' not found"

        # Completing a specific item within a todo list
        if item is not None:
            content = existing.get("content", "")
            lines = content.splitlines()
            item_lower = item.lower()
            matched = next(
                (i for i, l in enumerate(lines)
                 if l.strip().startswith("- [ ]") and item_lower in l.lower()),
                None,
            )
            if matched is None:
                return f"Item '{item}' not found in todo list '{memory_id}'."
            lines.pop(matched)
            remaining = [l for l in lines if l.strip().startswith("- [ ]")]
            if not remaining:
                _delete_memory(memory_id)
                return f"Last item completed — todo list '{memory_id}' removed."
            _update_memory(memory_id, content="\n".join(lines).strip())
            return f"Item completed. {len(remaining)} item(s) remaining."

        # Recurring reminders are marked done for today instead of deleted.
        if existing.get("recurring"):
            _complete_recurring(memory_id)
            deadline = existing.get("deadline", "unknown")
            return f"Recurring reminder '{memory_id}' marked done for today (next due {deadline})."
        _delete_memory(memory_id)
    except FileNotFoundError as e:
        return str(e)
    return f"Task '{memory_id}' completed and removed."


def list_tasks() -> str:
    tasks = _list_tasks()
    if not tasks:
        return "No open tasks."
    results = []
    for t in tasks:
        entry = {
            "id": t.get("id"),
            "type": t.get("type"),
            "owner": t.get("owner", "user"),
            "tags": t.get("tags", []),
            "preview": (t.get("content", "")[:200] or ""),
            "created": t.get("created"),
        }
        if t.get("deadline"):
            entry["deadline"] = t["deadline"]
        results.append(entry)
    return json.dumps(results, indent=2)


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
            "name": "delete_memory",
            "description": "Permanently delete a memory by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "The memory ID to delete",
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
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "Create a TODO list. Use markdown checkbox format for multiple items: '- [ ] item'. Completed items are removed one by one via complete_task; the list is deleted when all items are done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The todo list content. For multiple items use markdown checkboxes, e.g. '- [ ] Buy milk\\n- [ ] Call dentist'. For a single item, plain text is fine.",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated descriptive tags",
                    },
                    "owner": {
                        "type": "string",
                        "enum": ["user", "agent"],
                        "description": "'user' = remind the user to do this. 'agent' = something the agent should do/remember. Defaults to 'user'.",
                    },
                },
                "required": ["content", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder with a deadline. Non-recurring reminders are deleted when completed. Recurring reminders are hidden for the day and reappear in future sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "What to be reminded about",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated descriptive tags",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Due date in YYYY-MM-DD format (e.g. '2026-03-15')",
                    },
                    "owner": {
                        "type": "string",
                        "enum": ["user", "agent"],
                        "description": "'user' = remind the user about this. 'agent' = something the agent should do by the deadline. Defaults to 'user'.",
                    },
                    "recurring": {
                        "type": "boolean",
                        "description": "If true, completing this reminder hides it for today instead of deleting it. Use for repeating tasks like weekly reports. Defaults to false.",
                    },
                },
                "required": ["content", "tags", "deadline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a TODO or reminder as done. For todo lists, pass 'item' to complete one item (list is deleted when all items are done). Without 'item', completes the entire task. Recurring reminders are hidden for today and reappear in future sessions; all others are deleted permanently.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "The ID of the todo or reminder to complete",
                    },
                    "item": {
                        "type": "string",
                        "description": "For todo lists: text of the specific item to mark done (case-insensitive substring match). Omit to complete the entire task.",
                    },
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List all open TODOs and reminders. Reminders are sorted by deadline.",
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
    "delete_memory": delete_memory,
    "list_tags": list_tags,
    "create_todo": create_todo,
    "create_reminder": create_reminder,
    "complete_task": complete_task,
    "list_tasks": list_tasks,
}
