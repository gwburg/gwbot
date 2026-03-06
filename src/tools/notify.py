"""Notification tools — send push notifications to Will's phone.

Backends (in priority order):
1. **Pushover** — set PUSHOVER_USER_KEY + PUSHOVER_APP_TOKEN env vars
2. **ntfy.sh** — free, zero-config default. Set NTFY_TOPIC for a custom topic.

Will should install the relevant app on his phone:
- Pushover: https://pushover.net (iOS/Android, $5 one-time)
- ntfy: https://ntfy.sh (iOS/Android, free)
"""

import hashlib
import os
import platform
import time
from collections import deque

import requests

TAG = "notify"
CATEGORY = "Notifications — send push notifications to Will's phone"

# ---------------------------------------------------------------------------
# Rate limiting — max 10 notifications per hour to prevent spam
# ---------------------------------------------------------------------------

_send_times: deque[float] = deque(maxlen=60)
_RATE_LIMIT = 10
_RATE_WINDOW = 3600  # seconds


def _check_rate_limit() -> str | None:
    """Return an error message if rate-limited, else None."""
    now = time.time()
    # Remove sends outside the window
    while _send_times and _send_times[0] < now - _RATE_WINDOW:
        _send_times.popleft()
    if len(_send_times) >= _RATE_LIMIT:
        oldest = _send_times[0]
        wait_secs = int(oldest + _RATE_WINDOW - now) + 1
        return (
            f"Rate limited: {_RATE_LIMIT} notifications already sent in the last hour. "
            f"Try again in {wait_secs} seconds."
        )
    return None


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

_PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

# Priority mapping for Pushover (-2 to 2)
_PUSHOVER_PRIORITY = {
    "low": -1,
    "normal": 0,
    "high": 1,
    "urgent": 2,
}

# Priority mapping for ntfy (1-5)
_NTFY_PRIORITY = {
    "low": 2,
    "normal": 3,
    "high": 4,
    "urgent": 5,
}


def _get_ntfy_topic() -> str:
    """Get the ntfy topic name, generating a unique default if not configured."""
    topic = os.getenv("NTFY_TOPIC")
    if topic:
        return topic
    # Generate a deterministic but non-guessable topic from hostname
    hostname = platform.node()
    topic_hash = hashlib.sha256(f"gwbot-{hostname}".encode()).hexdigest()[:12]
    return f"gwbot-{topic_hash}"


def _send_pushover(title: str, message: str, priority: str) -> str:
    """Send via Pushover API."""
    user_key = os.getenv("PUSHOVER_USER_KEY")
    app_token = os.getenv("PUSHOVER_APP_TOKEN")

    data = {
        "token": app_token,
        "user": user_key,
        "title": title,
        "message": message,
        "priority": _PUSHOVER_PRIORITY.get(priority, 0),
    }

    # Urgent priority requires retry/expire params for Pushover
    if priority == "urgent":
        data["retry"] = 60    # retry every 60s
        data["expire"] = 600  # stop after 10 min

    try:
        resp = requests.post(_PUSHOVER_URL, data=data, timeout=10)
        resp.raise_for_status()
        return f"✅ Notification sent via Pushover (priority: {priority}): {title}"
    except requests.exceptions.RequestException as e:
        return f"❌ Pushover failed: {e}"


def _send_ntfy(title: str, message: str, priority: str) -> str:
    """Send via ntfy.sh."""
    topic = _get_ntfy_topic()
    ntfy_server = os.getenv("NTFY_SERVER", "https://ntfy.sh")
    url = f"{ntfy_server}/{topic}"

    headers = {
        "Title": title,
        "Priority": str(_NTFY_PRIORITY.get(priority, 3)),
        "Tags": "robot",
    }

    try:
        resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        resp.raise_for_status()
        return (
            f"✅ Notification sent via ntfy (priority: {priority}): {title}\n"
            f"Topic: {topic} on {ntfy_server}\n"
            f"Will needs to subscribe to this topic in the ntfy app to receive it."
        )
    except requests.exceptions.RequestException as e:
        return f"❌ ntfy failed: {e}"


def _get_backend() -> str:
    """Determine which backend to use based on available env vars."""
    if os.getenv("PUSHOVER_USER_KEY") and os.getenv("PUSHOVER_APP_TOKEN"):
        return "pushover"
    return "ntfy"


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


def send_notification(title: str, message: str, priority: str = "normal") -> str:
    """Send a push notification to Will's phone.

    Use this to proactively alert Will about important things — task reminders,
    budget alerts, morning briefings, or anything time-sensitive.

    Args:
        title: Short notification title (shown prominently on phone).
        message: Notification body text with details.
        priority: One of "low", "normal", "high", "urgent".
            - low: No sound, appears silently
            - normal: Default notification sound
            - high: Bypasses do-not-disturb on some devices
            - urgent: Persistent alert until acknowledged (use sparingly!)

    Returns a confirmation or error message.
    """
    # Validate priority
    priority = priority.lower()
    if priority not in ("low", "normal", "high", "urgent"):
        return f"Invalid priority '{priority}'. Use: low, normal, high, urgent."

    # Check rate limit
    rate_err = _check_rate_limit()
    if rate_err:
        return rate_err

    # Record this send
    _send_times.append(time.time())

    # Dispatch to appropriate backend
    backend = _get_backend()
    if backend == "pushover":
        return _send_pushover(title, message, priority)
    else:
        return _send_ntfy(title, message, priority)


def notification_status() -> str:
    """Check notification system status — which backend is configured and ready.

    Returns information about the current notification setup, including
    which backend is active and any setup instructions.
    """
    backend = _get_backend()
    now = time.time()

    # Count recent sends
    while _send_times and _send_times[0] < now - _RATE_WINDOW:
        _send_times.popleft()
    recent_count = len(_send_times)

    lines = [f"**Notification Backend:** {backend}"]
    lines.append(f"**Recent sends (last hour):** {recent_count}/{_RATE_LIMIT}")

    if backend == "pushover":
        lines.append("**Status:** ✅ Pushover configured and ready")
        lines.append("**User Key:** " + os.getenv("PUSHOVER_USER_KEY", "")[:4] + "...")
    else:
        topic = _get_ntfy_topic()
        server = os.getenv("NTFY_SERVER", "https://ntfy.sh")
        is_custom = bool(os.getenv("NTFY_TOPIC"))
        lines.append(f"**Status:** {'✅ Custom' if is_custom else '⚠️ Auto-generated'} ntfy topic")
        lines.append(f"**Server:** {server}")
        lines.append(f"**Topic:** `{topic}`")
        lines.append("")
        lines.append("**Setup instructions for Will:**")
        lines.append(f"1. Install the ntfy app (iOS: App Store, Android: Play Store/F-Droid)")
        lines.append(f"2. Subscribe to topic: `{topic}` on server `{server}`")
        lines.append(f"3. (Optional) Set `NTFY_TOPIC=your-custom-topic` in .env for a memorable name")
        lines.append("")
        lines.append("**To upgrade to Pushover:**")
        lines.append("1. Create a Pushover account at https://pushover.net")
        lines.append("2. Create an application to get an API token")
        lines.append("3. Set `PUSHOVER_USER_KEY` and `PUSHOVER_APP_TOKEN` in .env")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": (
                "Send a push notification to Will's phone. Use this to proactively alert "
                "Will about important things — task reminders, budget alerts, morning "
                "briefings, completed background tasks, or anything time-sensitive. "
                "Supports priority levels: low (silent), normal, high (bypasses DND), "
                "urgent (persistent, use sparingly). Rate-limited to 10/hour."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short notification title (shown prominently on phone).",
                    },
                    "message": {
                        "type": "string",
                        "description": "Notification body text with details.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": (
                            "Notification priority. 'low'=silent, 'normal'=default sound, "
                            "'high'=bypasses DND, 'urgent'=persistent alert (use sparingly!). "
                            "Default 'normal'."
                        ),
                        "default": "normal",
                    },
                },
                "required": ["title", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notification_status",
            "description": (
                "Check notification system status — which backend is configured, "
                "how many notifications have been sent recently, and setup instructions."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

TOOL_MAPPING = {
    "send_notification": send_notification,
    "notification_status": notification_status,
}
