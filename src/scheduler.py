"""Headless scheduler — entry point for cron.

Usage:
    python -m scheduler            # check all due jobs + daily review
    python -m scheduler --run ID   # run a specific job
    python -m scheduler --review   # force daily review
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
    list_all_memories,
    list_jobs,
    toggle_job,
    update_job_run,
    _parse_memory_file,
)

load_dotenv()

_LOCK_FILE = _BASE_DIR / ".scheduler.lock"
_LOG_FILE = _BASE_DIR / ".scheduler.log"
_LAST_REVIEW_FILE = _BASE_DIR / ".last_review"

_REVIEW_INTERVAL_HOURS = 24
_REVIEW_MODEL = models.SONNET
_REVIEW_MAX_ITERATIONS = 5

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

    tool_names = ["bash", "text_editor", "search_memories", "read_memory",
                  "create_memory", "update_memory"]
    try:
        job_tools, _ = get_tools(tool_names)
    except ValueError:
        # Fall back to just memory + bash if some tools don't exist
        job_tools, _ = get_tools(["bash"])

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
        _REVIEW_MODEL,
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
# Daily review
# ---------------------------------------------------------------------------


def _review_is_due() -> bool:
    """Check if 24h+ have passed since the last daily review."""
    if not _LAST_REVIEW_FILE.exists():
        return True
    try:
        last = datetime.fromisoformat(_LAST_REVIEW_FILE.read_text().strip())
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= _REVIEW_INTERVAL_HOURS * 3600
    except (ValueError, OSError):
        return True


async def run_daily_review(client) -> None:
    """Run the daily memory review."""
    from agent import agent_loop
    from memory.background import _format_existing_memories
    from tools import get_tools

    log.info("Starting daily memory review")

    memories = list_all_memories()
    if not memories:
        log.info("No memories to review")
        _LAST_REVIEW_FILE.write_text(datetime.now(timezone.utc).isoformat())
        return

    existing_text = _format_existing_memories(memories)

    tool_names = ["search_memories", "read_memory", "create_memory",
                  "update_memory", "delete_memory", "create_todo",
                  "create_reminder", "complete_task"]
    try:
        review_tools, _ = get_tools(tool_names)
    except ValueError:
        review_tools = []

    messages = [
        {"role": "system", "content": (
            "You are a background memory review agent. You have been given all stored memories.\n\n"
            "## Rules\n"
            "- **Only act if there is a clear, tangible benefit.** Otherwise do nothing.\n"
            "- You may create memories, todos, or reminders if cross-referencing reveals "
            "a genuinely useful action item or deadline the user would benefit from.\n"
            "- You may update or delete memories that are outdated, contradictory, or redundant.\n"
            "- Do NOT summarize or restate what is already stored.\n"
            "- Do NOT create entries just for the sake of creating them.\n"
            "- If everything looks fine, simply respond that no changes are needed.\n"
            "- Be conservative — the bar for action should be high.\n"
        )},
        {"role": "user", "content": (
            f"Here are all current memories. Review them and take action only if clearly beneficial.\n\n"
            f"{existing_text}"
        )},
    ]

    await agent_loop(
        client,
        _REVIEW_MODEL,
        messages,
        review_tools,
        max_iterations=_REVIEW_MAX_ITERATIONS,
    )

    _LAST_REVIEW_FILE.write_text(datetime.now(timezone.utc).isoformat())
    log.info("Daily review completed")


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
        job = _parse_memory_file(args.run)
        if not job or job.get("type") != "job":
            log.error("Job %s not found", args.run)
            return
        await run_job(client, job)
        return

    if args.review:
        await run_daily_review(client)
        return

    # Default: check daily review + all due jobs
    if _review_is_due():
        try:
            await run_daily_review(client)
        except Exception:
            log.exception("Daily review failed")

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
    parser.add_argument("--review", action="store_true", help="Force daily memory review")
    args = parser.parse_args()

    if not _acquire_lock():
        log.info("Another scheduler instance is running — exiting")
        sys.exit(0)

    try:
        asyncio.run(main(args))
    except Exception:
        log.exception("Scheduler failed")
    finally:
        _release_lock()
