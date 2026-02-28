"""Memory-related system prompt instructions."""

from memory import get_knowledge, get_tags


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

    return prompt
