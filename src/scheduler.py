"""Headless scheduler — entry point for cron.

Usage:
    python -m scheduler            # check all due jobs
    python -m scheduler --run ID   # run a specific job
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter
from dotenv import load_dotenv

import models
from memory import (
    _BASE_DIR,
    list_jobs,
    toggle_job,
    update_job_run,
    _parse_job_file,
)

load_dotenv()

_LOCK_FILE = _BASE_DIR / ".scheduler.lock"
_LOG_FILE = _BASE_DIR / ".scheduler.log"

_JOB_MODEL = models.SONNET

logging.basicConfig(
    filename=str(_LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


def _acquire_lock() -> bool:
    """Try to acquire a PID-based lockfile. Returns True on success."""
    if _LOCK_FILE.exists():
        try:
            pid = int(_LOCK_FILE.read_text().strip())
            # Check if PID is still running
            os.kill(pid, 0)
            return False  # Process is still running
        except (ProcessLookupError, ValueError):
            pass  # Stale lock — proceed
        except PermissionError:
            return False  # Process exists but we can't signal it

    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    try:
        _LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Job scheduling checks
# ---------------------------------------------------------------------------


def is_job_due(job: dict) -> bool:
    """Check if a job should run now."""
    schedule = job.get("schedule", "")
    if not schedule:
        return False

    last_run = job.get("last_run")
    now = datetime.now(timezone.utc)

    # Try as cron expression
    if croniter.is_valid(schedule):
        if not last_run:
            return True
        last_dt = datetime.fromisoformat(last_run)
        cron = croniter(schedule, last_dt)
        next_run = cron.get_next(datetime)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        return now >= next_run

    # Try as ISO datetime (one-shot)
    try:
        target = datetime.fromisoformat(schedule)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        if now >= target and not last_run:
            return True
    except ValueError:
        log.warning("Invalid schedule for job %s: %s", job.get("id"), schedule)

    return False


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


async def run_job(client, job: dict) -> None:
    """Run a single job headlessly using agent_loop."""
    from agent import agent_loop
    from tools import get_tools

    job_id = job["id"]
    prompt = job.get("content", "")
    max_iter = job.get("max_iterations", 5)

    log.info("Running job %s: %.80s", job_id, prompt)

    tool_names = ["bash", "text_editor", "search_knowledge", "read_knowledge",
                  "create_knowledge", "update_knowledge", "delete_knowledge",
                  "create_task", "update_task", "complete_task", "read_task"]
    job_tools, _ = get_tools(tool_names)

    messages = [
        {"role": "system", "content": (
            "You are a background agent running a scheduled job. "
            "Complete the task described in the user message. "
            "Be concise and efficient. You have memory and shell tools available."
        )},
        {"role": "user", "content": prompt},
    ]

    await agent_loop(
        client,
        _JOB_MODEL,
        messages,
        job_tools,
        max_iterations=max_iter,
    )

    update_job_run(job_id)

    # Disable one-shot jobs (ISO datetime, not cron)
    schedule = job.get("schedule", "")
    if not croniter.is_valid(schedule):
        toggle_job(job_id, enabled=False)

    log.info("Completed job %s", job_id)


# ---------------------------------------------------------------------------
# Cron management (CLI only — not exposed as LLM tools)
# ---------------------------------------------------------------------------

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_CRON_COMMENT = "# agent-scheduler"
_CRON_CMD = f"cd {_SRC_DIR} && uv run python -m scheduler"


def install_cron(schedule: str = "*/15 * * * *") -> str:
    """Add a crontab entry that runs the scheduler on the given schedule."""
    import subprocess

    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        current = existing.stdout if existing.returncode == 0 else ""
    except Exception:
        current = ""

    if _CRON_COMMENT in current:
        return "Cron entry already installed."

    entry = f"{schedule} {_CRON_CMD} {_CRON_COMMENT}\n"
    new_crontab = current.rstrip("\n") + "\n" + entry if current.strip() else entry

    proc = subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
    if proc.returncode != 0:
        return f"Error installing cron: {proc.stderr}"
    return f"Installed: {entry.strip()}"


def uninstall_cron() -> str:
    """Remove the agent-scheduler crontab entry."""
    import subprocess

    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if existing.returncode != 0:
            return "No crontab found."
        current = existing.stdout
    except Exception:
        return "No crontab found."

    lines = [l for l in current.splitlines() if _CRON_COMMENT not in l]
    new_crontab = "\n".join(lines) + "\n" if lines else ""

    if new_crontab.strip():
        proc = subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
    else:
        proc = subprocess.run(["crontab", "-r"], capture_output=True, text=True)

    if proc.returncode != 0:
        return f"Error: {proc.stderr}"
    return "Removed agent-scheduler cron entry."


def show_cron() -> str:
    """Show current agent-related crontab entries."""
    import subprocess

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            return "No crontab found."
        lines = [l for l in result.stdout.splitlines() if _CRON_COMMENT in l]
        if not lines:
            return "No agent-scheduler entries in crontab."
        return "\n".join(lines)
    except Exception:
        return "No crontab found."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    if args.run:
        # Run a specific job
        job = _parse_job_file(args.run)
        if not job:
            log.error("Job %s not found", args.run)
            return
        await run_job(client, job)
        return

    # Default: check all due jobs
    jobs = list_jobs()
    for job in jobs:
        if is_job_due(job):
            try:
                await run_job(client, job)
            except Exception:
                log.exception("Job %s failed", job.get("id"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent scheduler — headless runner for cron")
    parser.add_argument("--run", metavar="ID", help="Run a specific job by ID")
    parser.add_argument("--install-cron", action="store_true", help="Install crontab entry (every 15 min)")
    parser.add_argument("--uninstall-cron", action="store_true", help="Remove crontab entry")
    parser.add_argument("--show-cron", action="store_true", help="Show agent-scheduler crontab entries")
    args = parser.parse_args()

    # Cron management — instant operations, no lock needed
    if args.install_cron:
        print(install_cron())
        sys.exit(0)
    if args.uninstall_cron:
        print(uninstall_cron())
        sys.exit(0)
    if args.show_cron:
        print(show_cron())
        sys.exit(0)

    if not _acquire_lock():
        log.info("Another scheduler instance is running — exiting")
        sys.exit(0)

    try:
        asyncio.run(main(args))
    except Exception:
        log.exception("Scheduler failed")
    finally:
        _release_lock()
