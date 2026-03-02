"""Interactive setup flow for gwbot.

Usage:
    Triggered automatically when .env is missing OPENROUTER_API_KEY,
    or explicitly via `uv run src/app.py --init`.
"""

import getpass
import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _read_env() -> dict[str, str]:
    """Read existing .env into a dict, preserving order isn't critical."""
    env: dict[str, str] = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    """Write dict back to .env, preserving any keys we don't manage."""
    lines = [f"{k}={v}" for k, v in env.items()]
    _ENV_PATH.write_text("\n".join(lines) + "\n")


def run_init() -> None:
    """Interactive setup wizard. Prompts for name, API key, monarch token, and cron."""
    print("\n── gwbot setup ──\n")

    env = _read_env()

    # 1. Name (optional)
    name = input("Your name (optional, press Enter to skip): ").strip()
    if name:
        from memory import create_knowledge
        create_knowledge(
            content=f"The user's name is {name}.",
            tags=["user", "identity"],
        )
        print(f"  Saved name: {name}")

    # 2. OpenRouter API key (required)
    existing_key = env.get("OPENROUTER_API_KEY", "")
    if existing_key:
        print(f"\nOpenRouter API key already set (ends in ...{existing_key[-4:]})")
        replace = input("Replace it? [y/N]: ").strip().lower()
        if replace == "y":
            key = getpass.getpass("New OpenRouter API key: ").strip()
            if key:
                env["OPENROUTER_API_KEY"] = key
    else:
        key = ""
        while not key:
            key = getpass.getpass("OpenRouter API key (required): ").strip()
            if not key:
                print("  API key is required.")
        env["OPENROUTER_API_KEY"] = key

    # 3. Monarch token (optional)
    existing_monarch = env.get("MONARCH_TOKEN", "")
    if existing_monarch:
        print(f"\nMonarch token already set (ends in ...{existing_monarch[-4:]})")
        replace = input("Replace it? [y/N]: ").strip().lower()
        if replace == "y":
            token = getpass.getpass("New Monarch Money token: ").strip()
            if token:
                env["MONARCH_TOKEN"] = token
    else:
        token = getpass.getpass("\nMonarch Money token (optional, press Enter to skip): ").strip()
        if token:
            env["MONARCH_TOKEN"] = token
        else:
            print("  Skipped — monarch tools will not be available.")

    # Write .env
    _write_env(env)
    print(f"\n  Saved .env to {_ENV_PATH}")

    # 4. Scheduler cron + nightly review job (optional)
    do_cron = input("\nInstall scheduler cron job (checks for due jobs every 15 min)? [y/N]: ").strip().lower()
    if do_cron == "y":
        from scheduler import install_cron as _install_cron
        result = _install_cron()
        print(f"  {result}")

        do_review = input("Create nightly memory review job (runs at 3 AM)? [y/N]: ").strip().lower()
        if do_review == "y":
            from memory import create_job
            _REVIEW_PROMPT = (
                "Review all stored knowledge and tasks for quality, relevance and hidden insights\n\n"
                "1. Use search_knowledge (empty query) to list everything, and list_tasks.\n"
                "2. Use read_knowledge / read_task on any that look outdated, contradictory, "
                "or redundant OR of interest relative to other entries or jobs\n"
                "3. Rules:\n"
                "   - Only act if there is a clear, tangible benefit. Otherwise do nothing.\n"
                "   - You may update or delete knowledge that is outdated, contradictory, or redundant.\n"
                "   - Archive knowledge that is no longer relevant.\n"
                "   - You may create new knowledge or tasks if cross-referencing reveals "
                "a genuinely useful action item or deadline the user would benefit from.\n"
                "   - Do NOT summarize or restate what is already stored.\n"
                "   - Do NOT create entries just for the sake of creating them.\n"
                "   - Be conservative — the bar for action should be high.\n"
                "4. If everything looks fine, simply respond that no changes are needed.\n"
                "5. If you have taken any actions, log those in a knowledge entry tagged 'update' "
                "outlining what you've done — it should be reported to the user in the next conversation "
                "and then archived after being reported."
            )
            create_job(prompt=_REVIEW_PROMPT, schedule="0 3 * * *", tags=["review", "maintenance"])
            print("  Created nightly review job.")

    print("\n── Setup complete! ──\n")
