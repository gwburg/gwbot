"""Memory-related system prompt instructions."""

from datetime import date

from memory import get_knowledge, get_tags, list_tasks


def build_memory_prompt(category_tags: list[str] | None = None) -> str:
    """Return a system prompt section describing the memory system."""
    tags = get_tags()
    tag_line = ", ".join(tags) if tags else "(none yet)"

    valid_tags = ", ".join(f"`{t}`" for t in category_tags) if category_tags else "(none)"

    prompt = (
        "\n## Memory System\n\n"
        "You have a persistent memory system with two tiers:\n"
        "- **High-level memories**: Tagged summaries of important facts, preferences, and decisions.\n"
        "- **Low-level conversations**: Full conversation logs for reference.\n\n"
        "Conversations are automatically saved and summarized after each chat. "
        "You do NOT need to manually save a summary at the end of every conversation.\n\n"
        "### Using memories mid-chat\n"
        "- When the user asks you to remember something, use `create_memory` (after searching for duplicates first).\n"
        "- When context from past conversations might be relevant, use `search_memories`.\n"
        "- Prefer existing tags over inventing new ones.\n"
        "- Only save meaningful, long-term information — not ephemeral details.\n\n"
        "### TODOs and reminders\n"
        "- Use `create_todo` for simple tasks and `create_reminder` for deadline-based reminders.\n"
        "- Set `owner` to `user` (default) for things the user needs to do, or `agent` for your own tasks.\n"
        "- Use `list_tasks` to see all open items, `complete_task` to mark done.\n"
        "- Reminders with a future deadline are recurring: `complete_task` hides them for today, "
        "and they reappear in future sessions. Past-due reminders and TODOs are deleted permanently.\n"
        "- All open tasks are automatically loaded into this system prompt at startup (see below), "
        "so you don't need to call `list_tasks` to check — just read the sections below.\n"
        "- For user tasks: proactively remind the user, especially about overdue items.\n"
        "- For agent tasks: act on them silently — do NOT list or mention them to the user unless "
        "the deadline has passed or the user explicitly asks about them.\n\n"
        "### Knowledge tags\n"
        "Memories can be tagged for automatic injection:\n"
        "- `always` — content is loaded into the system prompt at startup.\n"
        f"- Tool-category tags ({valid_tags}) — content is injected into the first tool result "
        "from that category in each conversation, so you receive domain knowledge exactly when needed.\n\n"
        f"**Current tags**: {tag_line}"
    )

    # Inject always-tagged knowledge
    always_knowledge = get_knowledge("always")
    if always_knowledge:
        prompt += "\n\n## Knowledge (always loaded)\n"
        for mem in always_knowledge:
            prompt += f"\n- {mem.get('content', '')}"

    # Inject open tasks
    tasks = list_tasks()
    if tasks:
        today = date.today().isoformat()
        user_tasks = [t for t in tasks if t.get("owner", "user") == "user"]
        agent_tasks = [t for t in tasks if t.get("owner") == "agent"]

        if user_tasks:
            prompt += "\n\n## User Tasks (remind the user)\n"
            for t in user_tasks:
                prompt += _format_task(t, today)

        if agent_tasks:
            prompt += "\n\n## Agent Tasks (your responsibilities)\n"
            for t in agent_tasks:
                prompt += _format_task(t, today)

    return prompt


def _format_task(t: dict, today: str) -> str:
    content = t.get("content", "")[:200]
    tid = t.get("id", "")
    ttype = t.get("type", "todo")
    deadline = t.get("deadline")
    if ttype == "reminder" and deadline:
        overdue = " **OVERDUE**" if deadline < today else ""
        return f"\n- [{tid}] REMINDER (due {deadline}{overdue}): {content}"
    return f"\n- [{tid}] TODO: {content}"
