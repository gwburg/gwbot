"""Tests for the conversation search feature."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestSearchConversations:
    """Tests for memory.search_conversations."""

    def _write_log(self, log_dir: Path, conv_id: str, messages: list[dict]):
        """Helper to write a JSONL conversation log."""
        path = log_dir / f"{conv_id}.jsonl"
        with open(path, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

    def test_finds_matching_user_message(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._write_log(log_dir, "conv001", [
            {"role": "user", "content": "Tell me about Python decorators"},
            {"role": "assistant", "content": "Sure, here is some info..."},
        ])

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("decorators")

        assert len(results) == 1
        assert results[0]["id"] == "conv001"
        assert results[0]["role"] == "user"
        assert "decorators" in results[0]["snippet"].lower()

    def test_finds_matching_assistant_message(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._write_log(log_dir, "conv002", [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "I can help with scheduling tasks"},
        ])

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("scheduling")

        assert len(results) == 1
        assert results[0]["role"] == "assistant"

    def test_case_insensitive(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._write_log(log_dir, "conv003", [
            {"role": "user", "content": "Tell me about KUBERNETES"},
        ])

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("kubernetes")

        assert len(results) == 1

    def test_skips_tool_messages(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._write_log(log_dir, "conv004", [
            {"role": "tool", "content": "secret tool output with uniqueword123"},
            {"role": "user", "content": "What happened?"},
        ])

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("uniqueword123")

        assert len(results) == 0

    def test_max_results_limit(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        messages = [{"role": "user", "content": f"Message {i} about widgets"} for i in range(10)]
        self._write_log(log_dir, "conv005", messages)

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("widgets", max_results=3)

        assert len(results) == 3

    def test_no_results(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._write_log(log_dir, "conv006", [
            {"role": "user", "content": "Hello there"},
        ])

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("nonexistentstringxyz")

        assert results == []

    def test_snippet_truncation(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        long_content = "A" * 200 + "TARGET" + "B" * 200
        self._write_log(log_dir, "conv007", [
            {"role": "user", "content": long_content},
        ])

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("TARGET")

        assert len(results) == 1
        snippet = results[0]["snippet"]
        # Snippet should contain the target but be shorter than the full content
        assert "TARGET" in snippet
        assert len(snippet) < len(long_content)
        assert snippet.startswith("...")
        assert snippet.endswith("...")

    def test_empty_logs_dir(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        with patch("memory._LOGS_DIR", log_dir):
            from memory import search_conversations
            results = search_conversations("anything")

        assert results == []


class TestSearchConversationsTool:
    """Tests for the tool wrapper in tools.memory."""

    def test_tool_registered(self):
        from tools import TOOL_MAPPING
        assert "search_conversations" in TOOL_MAPPING

    def test_tool_schema_valid(self):
        from tools.memory import tools as memory_tools
        schemas = [t for t in memory_tools if t["function"]["name"] == "search_conversations"]
        assert len(schemas) == 1
        schema = schemas[0]
        assert "query" in schema["function"]["parameters"]["properties"]
        assert "query" in schema["function"]["parameters"]["required"]

    def test_tool_returns_json_string(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        # Write a test log
        path = log_dir / "testconv.jsonl"
        path.write_text(json.dumps({"role": "user", "content": "test search target"}) + "\n")

        with patch("memory._LOGS_DIR", log_dir):
            from tools.memory import search_conversations
            result = search_conversations(query="target")

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_tool_no_results_message(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        with patch("memory._LOGS_DIR", log_dir):
            from tools.memory import search_conversations
            result = search_conversations(query="nonexistent")

        assert result == "No matching conversations found."
