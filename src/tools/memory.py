"""Memory tools — knowledge, tasks, and archive management."""

import json

from memory import (
    archive_knowledge as _archive_knowledge,
    archive_task as _archive_task,
    complete_task_item as _complete_task_item,
    create_knowledge as _create_knowledge,
    create_task as _create_task,
    delete_knowledge as _delete_knowledge,
    delete_task as _delete_task,
    delete_tag as _delete_tag,
    get_tags as _get_tags,
    list_all_tasks as _list_all_tasks,
    read_conversation as _read_conversation,
    read_knowledge as _read_knowledge,
    read_task as _read_task,
    search_archive as _search_archive,
    search_knowledge as _search_knowledge,
    update_knowledge as _update_knowledge,
    update_task as _update_task,
)

TAG = "memory"
CATEGORY = "Memory — knowledge, tasks, and archive management"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _parse_tags(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",")]


def search_knowledge(query: str | None = None, tags: str | None = None) -> str:
    tag_list = _parse_tags(tags) if tags else None
    results = _search_knowledge(query=query, tags=tag_list)
    if not results:
        return "No knowledge entries found."
    return json.dumps(results, indent=2)


def read_knowledge(knowledge_id: str) -> str:
    return _read_knowledge(knowledge_id)


def read_task(task_id: str) -> str:
    return _read_task(task_id)


def read_conversation(conversation_id: str) -> str:
    return _read_conversation(conversation_id)


def create_knowledge(content: str, tags: str) -> str:
    tag_list = _parse_tags(tags)
    meta = _create_knowledge(content, tag_list)
    return json.dumps(meta, indent=2)


def update_knowledge(knowledge_id: str, content: str | None = None, tags: str | None = None) -> str:
    tag_list = _parse_tags(tags) if tags else None
    try:
        meta = _update_knowledge(knowledge_id, content=content, tags=tag_list)
    except FileNotFoundError as e:
        return str(e)
    return json.dumps(meta, indent=2)


def delete_knowledge(knowledge_id: str) -> str:
    try:
        _delete_knowledge(knowledge_id)
    except FileNotFoundError as e:
        return str(e)
    return f"Knowledge '{knowledge_id}' deleted."


def create_task(content: str, tags: str, owner: str = "user", due: str | None = None) -> str:
    tag_list = _parse_tags(tags)
    meta = _create_task(content, tag_list, owner=owner, due=due)
    return json.dumps(meta, indent=2)


def update_task(task_id: str, content: str | None = None, tags: str | None = None, due: str | None = None) -> str:
    tag_list = _parse_tags(tags) if tags else None
    try:
        meta = _update_task(task_id, content=content, tags=tag_list, due=due)
    except FileNotFoundError as e:
        return str(e)
    return json.dumps(meta, indent=2)


def complete_task(task_id: str, item: str | None = None, notes: str | None = None) -> str:
    try:
        if item is not None:
            _complete_task_item(task_id, item)
            return f"Item marked done in task '{task_id}'."
        else:
            _archive_task(task_id, notes=notes)
            return f"Task '{task_id}' completed and archived."
    except (FileNotFoundError, ValueError) as e:
        return str(e)


def list_tasks() -> str:
    tasks = _list_all_tasks()
    if not tasks:
        return "No open tasks."
    results = []
    for t in tasks:
        entry = {
            "id": t.get("id"),
            "owner": t.get("owner", "user"),
            "tags": t.get("tags", []),
            "preview": (t.get("content", "")[:200] or ""),
            "created": t.get("created"),
        }
        if t.get("due"):
            entry["due"] = t["due"]
        results.append(entry)
    return json.dumps(results, indent=2)


def search_archive(query: str | None = None, tags: str | None = None) -> str:
    tag_list = _parse_tags(tags) if tags else None
    results = _search_archive(query=query, tags=tag_list)
    if not results:
        return "No archived entries found."
    return json.dumps(results, indent=2)


def archive_knowledge(knowledge_id: str) -> str:
    try:
        _archive_knowledge(knowledge_id)
    except FileNotFoundError as e:
        return str(e)
    return f"Knowledge '{knowledge_id}' moved to archive."


def list_tags() -> str:
    tags = _get_tags()
    if not tags:
        return "No tags yet."
    return ", ".join(tags)


def delete_tag(tag: str) -> str:
    still_using = _delete_tag(tag)
    msg = f"Tag '{tag}' removed from tags.yaml."
    if still_using:
        msg += f" Note: {still_using} entry/entries still reference this tag."
    return msg


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


tools = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Search knowledge entries by keyword and/or tags. "
                "Returns id, tags, and a preview for each match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search for in content",
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
            "name": "read_knowledge",
            "description": "Read the full content of a knowledge entry by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge_id": {
                        "type": "string",
                        "description": "The knowledge ID to read",
                    },
                },
                "required": ["knowledge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_task",
            "description": "Read the full content of a task by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID to read",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_conversation",
            "description": "Read the full conversation log by its conversation ID.",
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
            "name": "create_knowledge",
            "description": (
                "Create a new knowledge entry. Before creating, always search_knowledge first "
                "to avoid duplicates. If a similar entry exists, use update_knowledge instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The content (a concise summary or fact)",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated descriptive tags (e.g. 'preference,food'). Use existing tags when possible.",
                    },
                },
                "required": ["content", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_knowledge",
            "description": "Update an existing knowledge entry's content and/or tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge_id": {
                        "type": "string",
                        "description": "The knowledge ID to update",
                    },
                    "content": {
                        "type": "string",
                        "description": "New content to replace the existing content",
                    },
                    "tags": {
                        "type": "string",
                        "description": "New comma-separated descriptive tags to replace existing tags",
                    },
                },
                "required": ["knowledge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_knowledge",
            "description": "Permanently delete a knowledge entry by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge_id": {
                        "type": "string",
                        "description": "The knowledge ID to delete",
                    },
                },
                "required": ["knowledge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a task. Use markdown checkboxes for multiple items (e.g. '- [ ] item'). Optionally set a due date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Task content. For multiple items use '- [ ] item' format on separate lines.",
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
                    "due": {
                        "type": "string",
                        "description": "Optional due date as YYYY-MM-DD or datetime as YYYY-MM-DDTHH:MM (e.g. '2026-03-15' or '2026-03-15T21:00')",
                    },
                },
                "required": ["content", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update an existing task's content, tags, and/or due date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID to update",
                    },
                    "content": {
                        "type": "string",
                        "description": "New content to replace the existing content",
                    },
                    "tags": {
                        "type": "string",
                        "description": "New comma-separated descriptive tags",
                    },
                    "due": {
                        "type": "string",
                        "description": "New due date as YYYY-MM-DD or YYYY-MM-DDTHH:MM",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": (
                "Complete a task or a specific item within it. "
                "With 'item': marks the matching checklist item as [x]. "
                "Without 'item': archives the entire task. "
                "Optionally add completion notes when archiving."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID to complete",
                    },
                    "item": {
                        "type": "string",
                        "description": "Text of specific checklist item to mark done (case-insensitive substring match). Omit to archive the entire task.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional completion notes appended when archiving the task. Only used when archiving (no 'item').",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List all open tasks.",
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
            "name": "search_archive",
            "description": "Search archived tasks and knowledge entries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search for",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags to filter by",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "archive_knowledge",
            "description": "Move a knowledge entry to the archive (no longer injected into system prompt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge_id": {
                        "type": "string",
                        "description": "The knowledge ID to archive",
                    },
                },
                "required": ["knowledge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tags",
            "description": "List all known tags.",
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
            "name": "delete_tag",
            "description": (
                "Remove a tag from tags.yaml. "
                "Reports how many entries still reference the deleted tag."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "The tag name to delete",
                    },
                },
                "required": ["tag"],
            },
        },
    },
]


TOOL_MAPPING = {
    "search_knowledge": search_knowledge,
    "read_knowledge": read_knowledge,
    "read_task": read_task,
    "read_conversation": read_conversation,
    "create_knowledge": create_knowledge,
    "update_knowledge": update_knowledge,
    "delete_knowledge": delete_knowledge,
    "create_task": create_task,
    "update_task": update_task,
    "complete_task": complete_task,
    "list_tasks": list_tasks,
    "search_archive": search_archive,
    "archive_knowledge": archive_knowledge,
    "list_tags": list_tags,
    "delete_tag": delete_tag,
}
