"""Scheduler tools — create, list, and manage timed background jobs."""

import os
import subprocess
import sys

from memory import create_job, delete_memory, list_jobs, toggle_job

TAG = "scheduler"
CATEGORY = "Scheduler — create, list, and manage timed background jobs"

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CRON_COMMENT = "# agent-scheduler"
_CRON_CMD = f"cd {_SRC_DIR} && uv run python -m scheduler"


def create_scheduled_job(
    prompt: str,
    schedule: str,
    tags: list[str] | None = None,
    max_iterations: int = 5,
) -> str:
    """Create a new scheduled job."""
    meta = create_job(
        prompt=prompt,
        schedule=schedule,
        tags=tags or [],
        max_iterations=max_iterations,
    )
    return f"Created job {meta['id']} with schedule '{schedule}'"


def list_scheduled_jobs(include_disabled: bool = False) -> str:
    """List all scheduled jobs."""
    jobs = list_jobs(include_disabled=include_disabled)
    if not jobs:
        return "No scheduled jobs found."
    lines = []
    for j in jobs:
        status = "enabled" if j.get("enabled", True) else "disabled"
        last_run = j.get("last_run", "never")
        schedule = j.get("schedule", "?")
        prompt = (j.get("content", "") or "")[:80]
        tags = ", ".join(j.get("tags", []))
        lines.append(
            f"- [{j['id']}] schedule={schedule} status={status} "
            f"last_run={last_run} tags=[{tags}]\n  prompt: {prompt}"
        )
    return "\n".join(lines)


def delete_scheduled_job(job_id: str) -> str:
    """Delete a scheduled job by ID."""
    try:
        delete_memory(job_id)
        return f"Deleted job {job_id}"
    except FileNotFoundError:
        return f"Error: job '{job_id}' not found"


def toggle_scheduled_job(job_id: str, enabled: bool) -> str:
    """Enable or disable a scheduled job."""
    try:
        toggle_job(job_id, enabled)
        state = "enabled" if enabled else "disabled"
        return f"Job {job_id} is now {state}"
    except FileNotFoundError:
        return f"Error: job '{job_id}' not found"


def install_cron() -> str:
    """Add a crontab entry that runs the scheduler every 15 minutes."""
    try:
        existing = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        current = existing.stdout if existing.returncode == 0 else ""
    except Exception:
        current = ""

    if _CRON_COMMENT in current:
        return "Cron entry already installed. Use show_cron to view it."

    entry = f"*/15 * * * * {_CRON_CMD} {_CRON_COMMENT}\n"
    new_crontab = current.rstrip("\n") + "\n" + entry if current.strip() else entry

    try:
        proc = subprocess.run(
            ["crontab", "-"], input=new_crontab, capture_output=True, text=True
        )
        if proc.returncode != 0:
            return f"Error installing cron: {proc.stderr}"
        return f"Installed cron entry: {entry.strip()}"
    except Exception as e:
        return f"Error: {e}"


def uninstall_cron() -> str:
    """Remove the agent-scheduler crontab entry."""
    try:
        existing = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        if existing.returncode != 0:
            return "No crontab found."
        current = existing.stdout
    except Exception:
        return "No crontab found."

    lines = [l for l in current.splitlines() if _CRON_COMMENT not in l]
    new_crontab = "\n".join(lines) + "\n" if lines else ""

    if new_crontab.strip():
        proc = subprocess.run(
            ["crontab", "-"], input=new_crontab, capture_output=True, text=True
        )
    else:
        proc = subprocess.run(
            ["crontab", "-r"], capture_output=True, text=True
        )

    if proc.returncode != 0:
        return f"Error: {proc.stderr}"
    return "Removed agent-scheduler cron entry."


def show_cron() -> str:
    """Show current agent-related crontab entries."""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return "No crontab found."
        lines = [l for l in result.stdout.splitlines() if _CRON_COMMENT in l]
        if not lines:
            return "No agent-scheduler entries in crontab."
        return "\n".join(lines)
    except Exception:
        return "No crontab found."


tools = [
    {
        "type": "function",
        "function": {
            "name": "create_scheduled_job",
            "description": (
                "Create a timed background job that runs on a schedule. "
                "Use a cron expression (e.g. '0 9 * * *' for 9am daily) or an ISO datetime for one-shot jobs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The instruction the agent will execute when this job runs.",
                    },
                    "schedule": {
                        "type": "string",
                        "description": "Cron expression (e.g. '0 9 * * *') or ISO datetime (e.g. '2025-03-01T14:00:00') for one-shot.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for the job.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Max agent loop iterations. Defaults to 5.",
                    },
                },
                "required": ["prompt", "schedule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled_jobs",
            "description": "List all scheduled background jobs with their schedule, last run time, and status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_disabled": {
                        "type": "boolean",
                        "description": "Include disabled jobs. Defaults to false.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_scheduled_job",
            "description": "Delete a scheduled job by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The ID of the job to delete.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_scheduled_job",
            "description": "Enable or disable a scheduled job.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The ID of the job to toggle.",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "True to enable, false to disable.",
                    },
                },
                "required": ["job_id", "enabled"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_cron",
            "description": "Install a crontab entry that runs the scheduler every 15 minutes. Idempotent — won't duplicate.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "uninstall_cron",
            "description": "Remove the agent-scheduler crontab entry.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_cron",
            "description": "Show current agent-scheduler crontab entries.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_MAPPING = {
    "create_scheduled_job": create_scheduled_job,
    "list_scheduled_jobs": list_scheduled_jobs,
    "delete_scheduled_job": delete_scheduled_job,
    "toggle_scheduled_job": toggle_scheduled_job,
    "install_cron": install_cron,
    "uninstall_cron": uninstall_cron,
    "show_cron": show_cron,
}
