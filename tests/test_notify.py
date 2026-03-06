"""Tests for the notification tools."""

import os
import time
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.notify import (
    _check_rate_limit,
    _get_ntfy_topic,
    _RATE_LIMIT,
    _send_times,
    notification_status,
    send_notification,
)


class TestRateLimit:
    def setup_method(self):
        _send_times.clear()

    def test_allows_when_under_limit(self):
        assert _check_rate_limit() is None

    def test_blocks_when_at_limit(self):
        for _ in range(_RATE_LIMIT):
            _send_times.append(time.time())
        result = _check_rate_limit()
        assert result is not None
        assert "Rate limited" in result

    def test_old_sends_expire(self):
        # Add sends from 2 hours ago — should not count
        old_time = time.time() - 7200
        for _ in range(_RATE_LIMIT):
            _send_times.append(old_time)
        assert _check_rate_limit() is None


class TestNtfyTopic:
    def test_uses_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("NTFY_TOPIC", "my-custom-topic")
        assert _get_ntfy_topic() == "my-custom-topic"

    def test_generates_deterministic_topic(self, monkeypatch):
        monkeypatch.delenv("NTFY_TOPIC", raising=False)
        topic1 = _get_ntfy_topic()
        topic2 = _get_ntfy_topic()
        assert topic1 == topic2
        assert topic1.startswith("gwbot-")


class TestSendNotification:
    def setup_method(self):
        _send_times.clear()

    def test_rejects_invalid_priority(self):
        result = send_notification("Test", "test", "CRITICAL")
        assert "Invalid priority" in result

    def test_respects_rate_limit(self):
        # Fill up rate limit
        for _ in range(_RATE_LIMIT):
            _send_times.append(time.time())
        result = send_notification("Test", "test", "normal")
        assert "Rate limited" in result


class TestNotificationStatus:
    def setup_method(self):
        _send_times.clear()

    def test_shows_backend_info(self):
        status = notification_status()
        assert "Notification Backend" in status
        assert "Recent sends" in status

    def test_shows_ntfy_when_no_pushover(self, monkeypatch):
        monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
        monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
        status = notification_status()
        assert "ntfy" in status

    def test_shows_pushover_when_configured(self, monkeypatch):
        monkeypatch.setenv("PUSHOVER_USER_KEY", "testuser1234")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "testtoken5678")
        status = notification_status()
        assert "Pushover" in status
        assert "test" in status  # partial key shown
