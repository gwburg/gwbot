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
        from memory import create_memory
        create_memory(
            content=f"The user's name is {name}.",
            tags=["user", "identity"],
            knowledge_tag="always",
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

    # 4. Nightly memory review cron (optional)
    install_cron = input("\nInstall nightly memory review cron job? [y/N]: ").strip().lower()
    if install_cron == "y":
        from scheduler import install_cron as _install_cron
        result = _install_cron(schedule="0 3 * * *")
        print(f"  {result}")

    print("\n── Setup complete! ──\n")
