"""Memory-related system prompt instructions."""

from datetime import date

from memory import get_tags, list_all_knowledge, list_all_tasks


def build_memory_prompt() -> str:
    """Return a system prompt section describing the memory system."""
    tags = get_tags()
    tag_line = ", ".join(tags) if tags else "(none yet)"

    prompt = (
        "\n## Memory System\n\n"
        "You have a persistent memory system:\n"
        "- **Knowledge**: Facts, preferences, decisions, and instructions.\n"
        "- **Tasks**: Action items with optional due dates.\n"
        "- **Archive**: Completed tasks and retired knowledge (not loaded into prompt, but searchable).\n"
        "- **Conversation logs**: Full conversation histories for reference.\n\n"
        "Conversations are automatically saved and summarized after each chat. "
        "You do NOT need to manually save a summary at the end of every conversation.\n\n"
        "### Using knowledge mid-chat\n"
        "- When the user asks you to remember something, use `create_knowledge` (after searching for duplicates first).\n"
        "- When context from past conversations might be relevant, use `search_knowledge`.\n"
        "- To retire knowledge that is no longer relevant, use `archive_knowledge`.\n"
        "- Prefer existing tags over inventing new ones.\n"
        "- Only save meaningful, long-term information — not ephemeral details.\n\n"
        "### Tasks\n"
        "- Use `create_task` for action items. Use markdown checkboxes for multiple items:\n"
        "  `- [ ] Buy milk\\n- [ ] Call dentist`\n"
        "- Set `owner` to `user` (default) for things the user needs to do, or `agent` for your own tasks.\n"
        "- Set `due` for deadline-sensitive items (YYYY-MM-DD format).\n"
        "- To complete one item from a list: `complete_task(task_id, item='...')` — marks it [x].\n"
        "- To complete/archive an entire task: `complete_task(task_id)` — moves it to archive.\n"
        "- You can add completion notes when archiving: `complete_task(task_id, notes='...')`.\n"
        "- All open tasks are loaded into this system prompt (see below), "
        "so you don't need to call `list_tasks` to check.\n"
        "- Do NOT list all tasks on startup. Only proactively mention tasks that are **overdue** "
        "or **due within 24 hours**. Otherwise, only discuss tasks when the user asks.\n"
        "- For agent tasks: act on them silently — do NOT list or mention them to the user unless "
        "the due date has passed or the user explicitly asks about them.\n\n"
        "### Scheduled jobs\n"
        "- Use `create_scheduled_job` to create background tasks that run on a timer.\n"
        "- Schedule with a cron expression (e.g. `0 9 * * *` = 9am daily) or ISO datetime for one-shot.\n"
        "- After creating a job, ensure the crontab is set up by running `python -m scheduler --install-cron` via bash.\n"
        "- Jobs run headlessly via `python -m scheduler` — they have memory and shell tools available.\n"
        "- Use `list_scheduled_jobs`, `toggle_scheduled_job`, `delete_scheduled_job` to manage.\n\n"
        f"**Current tags**: {tag_line}"
    )

    # Inject all knowledge
    knowledge = list_all_knowledge()
    if knowledge:
        prompt += "\n\n## Knowledge\n"
        for k in knowledge:
            kid = k.get("id", "")
            content = k.get("content", "")
            prompt += f"\n- [{kid}] {content}"

    # Inject all tasks
    tasks = list_all_tasks()
    if tasks:
        today = date.today().isoformat()
        user_tasks = [t for t in tasks if t.get("owner", "user") == "user"]
        agent_tasks = [t for t in tasks if t.get("owner") == "agent"]

        if user_tasks:
            prompt += "\n\n## User Tasks (remind the user)\n"
            for t in user_tasks:
                prompt += _format_task(t, today)

        if agent_tasks:
            prompt += "\n\n## Agent Tasks (your responsibilities — invisible to the user unless asked)\n"
            for t in agent_tasks:
                prompt += _format_task(t, today)

    return prompt


def _format_task(t: dict, today: str) -> str:
    content = t.get("content", "")
    tid = t.get("id", "")
    due = t.get("due")

    due_str = ""
    overdue = ""
    if due:
        due_str = f" (due {due})"
        if due < today:
            overdue = " **OVERDUE**"

    lines = content.splitlines()
    checklist_items = [l.strip() for l in lines if l.strip().startswith("- [")]
    if checklist_items:
        title = next((l for l in lines if l.strip() and not l.strip().startswith("- [")), None)
        header = f"\n- [{tid}]{due_str}{overdue} {title}" if title else f"\n- [{tid}]{due_str}{overdue}"
        return header + "".join(f"\n    {item}" for item in checklist_items)
    return f"\n- [{tid}]{due_str}{overdue}: {content[:200]}"
