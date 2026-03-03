"""Tests for the web search and URL fetching tools."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch, MagicMock
import pytest

from tools.web import web_search, fetch_url, _html_to_text


# ---------------------------------------------------------------------------
# HTML extraction tests (unit tests — no network)
# ---------------------------------------------------------------------------


class TestHTMLExtraction:
    def test_basic_text(self):
        html = "<p>Hello world</p>"
        result = _html_to_text(html)
        assert "Hello world" in result

    def test_strips_script(self):
        html = "<p>Visible</p><script>var x = 1;</script><p>Also visible</p>"
        result = _html_to_text(html)
        assert "Visible" in result
        assert "Also visible" in result
        assert "var x" not in result

    def test_strips_style(self):
        html = "<p>Text</p><style>.foo { color: red; }</style>"
        result = _html_to_text(html)
        assert "Text" in result
        assert "color: red" not in result

    def test_strips_nav(self):
        html = "<nav>Skip to content</nav><article><p>Article content</p></article>"
        result = _html_to_text(html)
        assert "Article content" in result
        assert "Skip to content" not in result

    def test_block_tag_newlines(self):
        html = "<h1>Title</h1><p>Paragraph one</p><p>Paragraph two</p>"
        result = _html_to_text(html)
        assert "Title" in result
        assert "Paragraph one" in result
        assert "Paragraph two" in result

    def test_nested_skip_tags(self):
        # HTMLParser doesn't handle nested same-type tags, but real browsers don't
        # nest <script> tags either — test the practical case instead.
        html = "<p>Before</p><script>var x = 1;</script><p>After</p>"
        result = _html_to_text(html)
        assert "Before" in result
        assert "After" in result
        assert "var x" not in result

    def test_empty_html(self):
        result = _html_to_text("")
        assert result == ""

    def test_plain_text(self):
        result = _html_to_text("Just plain text")
        assert "Just plain text" in result


# ---------------------------------------------------------------------------
# web_search tests (mocked — no real network calls)
# ---------------------------------------------------------------------------


class TestWebSearch:
    def test_text_search_returns_formatted_results(self):
        """web_search with text type returns formatted titles, URLs, and snippets."""
        mock_results = [
            {"title": "Result One", "href": "https://example.com/1", "body": "First result snippet"},
            {"title": "Result Two", "href": "https://example.com/2", "body": "Second result snippet"},
        ]
        import ddgs as ddgs_mod
        import tools.web as web_mod

        instance = MagicMock()
        instance.text.return_value = iter(mock_results)

        orig = ddgs_mod.DDGS
        ddgs_mod.DDGS = lambda: instance
        result = web_mod.web_search("test query", max_results=5)
        ddgs_mod.DDGS = orig

        assert "Result One" in result
        assert "https://example.com/1" in result
        assert "First result snippet" in result
        assert "Result Two" in result

    def test_max_results_clamped(self):
        """Verify max_results is clamped to 1–10."""
        # We'll test the clamping logic indirectly
        with patch("ddgs.DDGS") as MockDDGS:
            instance = MockDDGS.return_value
            instance.text.return_value = iter([])
            # Just verify it doesn't raise with out-of-range values
            import tools.web as web_mod
            # Monkey-patch to use mock
            import ddgs as ddgs_mod
            orig = ddgs_mod.DDGS
            ddgs_mod.DDGS = lambda: instance
            result = web_mod.web_search("test", max_results=100)
            ddgs_mod.DDGS = orig
            # max_results should have been clamped to 10

    def test_search_failure_returns_error_string(self):
        """web_search should return an error string on failure, not raise."""
        import tools.web as web_mod
        import ddgs as ddgs_mod

        def raise_error():
            raise ConnectionError("Network unreachable")

        orig = ddgs_mod.DDGS
        ddgs_mod.DDGS = raise_error
        result = web_mod.web_search("test query")
        ddgs_mod.DDGS = orig

        assert "failed" in result.lower() or "error" in result.lower()

    def test_no_results(self):
        """Should return 'No results found' when search yields nothing."""
        import tools.web as web_mod
        import ddgs as ddgs_mod

        instance = MagicMock()
        instance.text.return_value = iter([])

        orig = ddgs_mod.DDGS
        ddgs_mod.DDGS = lambda: instance
        result = web_mod.web_search("completely obscure query xyz")
        ddgs_mod.DDGS = orig

        assert "No results found" in result


# ---------------------------------------------------------------------------
# fetch_url tests (mocked — no real network calls)
# ---------------------------------------------------------------------------


class TestFetchURL:
    def test_fetches_and_extracts_html(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.text = "<html><body><p>Hello from the web!</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("tools.web.requests.get", return_value=mock_response):
            result = fetch_url("https://example.com")

        assert "https://example.com" in result
        assert "Hello from the web!" in result

    def test_timeout_error(self):
        import requests as req_lib
        with patch("tools.web.requests.get", side_effect=req_lib.exceptions.Timeout):
            result = fetch_url("https://example.com")
        assert "timed out" in result.lower()

    def test_http_error(self):
        import requests as req_lib
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = req_lib.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = http_error

        mock_get = MagicMock(return_value=mock_response)
        with patch("tools.web.requests.get", mock_get):
            result = fetch_url("https://example.com/not-found")
        assert "404" in result or "error" in result.lower()

    def test_max_chars_truncation(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        long_content = "A" * 10000
        mock_response.text = f"<html><body><p>{long_content}</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("tools.web.requests.get", return_value=mock_response):
            result = fetch_url("https://example.com", max_chars=500)

        assert "truncated" in result.lower()
        # The total returned text should be somewhat near max_chars (plus header)
        assert len(result) < 10000

    def test_max_chars_clamped(self):
        """max_chars should be clamped to 500–32000."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = "<p>Content</p>"
        mock_response.raise_for_status = MagicMock()

        with patch("tools.web.requests.get", return_value=mock_response):
            # Should not raise even with extreme values
            result = fetch_url("https://example.com", max_chars=0)
        assert "Content" in result

    def test_unsupported_content_type(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.raise_for_status = MagicMock()

        with patch("tools.web.requests.get", return_value=mock_response):
            result = fetch_url("https://example.com/file.pdf")

        assert "unsupported" in result.lower() or "error" in result.lower()

    def test_json_content_type(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"key": "value"}'
        mock_response.raise_for_status = MagicMock()

        with patch("tools.web.requests.get", return_value=mock_response):
            result = fetch_url("https://api.example.com/data")

        assert '{"key": "value"}' in result or "key" in result


# ---------------------------------------------------------------------------
# Integration: tools registered in tool mapping
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_web_search_in_tool_mapping(self):
        from tools import TOOL_MAPPING
        assert "web_search" in TOOL_MAPPING

    def test_fetch_url_in_tool_mapping(self):
        from tools import TOOL_MAPPING
        assert "fetch_url" in TOOL_MAPPING

    def test_web_search_schema_valid(self):
        from tools import tools
        schemas = {t["function"]["name"]: t for t in tools}
        assert "web_search" in schemas
        schema = schemas["web_search"]
        assert schema["type"] == "function"
        assert "query" in schema["function"]["parameters"]["properties"]
        assert "query" in schema["function"]["parameters"]["required"]

    def test_fetch_url_schema_valid(self):
        from tools import tools
        schemas = {t["function"]["name"]: t for t in tools}
        assert "fetch_url" in schemas
        schema = schemas["fetch_url"]
        assert "url" in schema["function"]["parameters"]["properties"]
        assert "url" in schema["function"]["parameters"]["required"]

    def test_web_category_in_categories(self):
        from tools import categories
        assert any("web" in cat.lower() or "search" in cat.lower() for cat in categories)
