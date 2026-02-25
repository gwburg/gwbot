import re
import subprocess

# Each entry is (regex_pattern, human_readable_reason).
# Checked in order; first match blocks the command.
_BLOCKED = [
    (r"\bsudo\b",                   "sudo is not permitted"),
    (r"\brm\b.*-[a-zA-Z]*[rR]",     "recursive rm is not permitted"),
    (r":\(\)\s*\{",                 "fork bomb detected"),
    (r"\bmkfs\b",                   "mkfs is not permitted"),
    (r"\bdd\b.+of=/dev/",           "dd writes to a device are not permitted"),
    (r"\bshutdown\b",               "shutdown is not permitted"),
    (r"\breboot\b",                 "reboot is not permitted"),
    (r"\bhalt\b",                   "halt is not permitted"),
    (r"\bpoweroff\b",               "poweroff is not permitted"),
    (r"\|\s*(bash|sh|zsh)\b",       "piping into a shell is not permitted"),
]

DEFAULT_TIMEOUT = 30
MAX_OUTPUT_CHARS = 10_000


def _check_blocked(command: str) -> str | None:
    """Return a reason string if the command is blocked, else None."""
    for pattern, reason in _BLOCKED:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS], True


def bash(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    reason = _check_blocked(command)
    if reason:
        return f"Error: blocked — {reason}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"

    parts = [f"Exit code: {result.returncode}"]

    if result.stdout:
        stdout, truncated = _truncate(result.stdout)
        parts.append(f"stdout:\n{stdout}")
        if truncated:
            parts.append(f"[stdout truncated at {MAX_OUTPUT_CHARS} chars]")

    if result.stderr:
        stderr, truncated = _truncate(result.stderr)
        parts.append(f"stderr:\n{stderr}")
        if truncated:
            parts.append(f"[stderr truncated at {MAX_OUTPUT_CHARS} chars]")

    return "\n".join(parts)


tools = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Execute a bash/zsh shell command and return its exit code, stdout, and stderr. "
                f"Times out after {DEFAULT_TIMEOUT}s by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": f"Optional. Timeout in seconds. Defaults to {DEFAULT_TIMEOUT}. Increase for long-running commands."
                    }
                },
                "required": ["command"]
            }
        }
    }
]

TOOL_MAPPING = {
    "bash": bash
}
