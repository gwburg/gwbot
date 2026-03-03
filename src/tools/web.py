"""Web tools — search the web and fetch URLs."""

import re
from html.parser import HTMLParser

import requests

TAG = "web"
CATEGORY = "Web — search the internet and fetch URLs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _HTMLTextExtractor(HTMLParser):
    """Extract readable text from HTML, skipping scripts/styles/nav."""

    _SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "aside", "iframe"}
    _BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "div", "article",
                   "section", "blockquote", "pre", "td", "th", "tr"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped + " ")

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"\n[ \t]+", "\n", text)      # strip leading whitespace on lines
        text = re.sub(r"[ \t]{2,}", " ", text)       # collapse inline spaces
        text = re.sub(r"\n{3,}", "\n\n", text)       # max 2 consecutive newlines
        return text.strip()


def _html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def web_search(query: str, max_results: int = 5, search_type: str = "text") -> str:
    """Search the web using DuckDuckGo.

    Args:
        query: Search query string.
        max_results: Number of results to return (1–10).
        search_type: "text" for general web results, "news" for recent news.

    Returns formatted search results.
    """
    max_results = max(1, min(10, max_results))

    try:
        from ddgs import DDGS
        ddgs = DDGS()

        if search_type == "news":
            raw = list(ddgs.news(query, max_results=max_results))
            # Fallback: if news fails or is empty, try text search
            if not raw:
                raw = list(ddgs.text(f"{query} news", max_results=max_results))
                results = []
                for r in raw:
                    title = r.get("title", "").strip()
                    url = r.get("href", "").strip()
                    body = r.get("body", "").strip()
                    line = f"**{title}**\n{url}"
                    if body:
                        line += f"\n{body}"
                    results.append(line)
            else:
                results = []
                for r in raw:
                    title = r.get("title", "").strip()
                    url = r.get("url", r.get("href", "")).strip()
                    body = r.get("body", "").strip()
                    date = r.get("date", "").strip()
                    line = f"**{title}**"
                    if date:
                        line += f" ({date[:10]})"
                    line += f"\n{url}"
                    if body:
                        line += f"\n{body}"
                    results.append(line)
        else:
            raw = list(ddgs.text(query, max_results=max_results))
            results = []
            for r in raw:
                title = r.get("title", "").strip()
                url = r.get("href", "").strip()
                body = r.get("body", "").strip()
                line = f"**{title}**\n{url}"
                if body:
                    line += f"\n{body}"
                results.append(line)

        if not results:
            return "No results found."

        header = f"Search results for: {query}\n\n"
        return header + "\n\n---\n\n".join(results)

    except Exception as e:
        return f"Search failed: {e}"


def fetch_url(url: str, max_chars: int = 8000) -> str:
    """Fetch a URL and return its text content.

    Strips HTML tags, scripts, and navigation. Useful for reading articles,
    documentation, or any web page after finding it via web_search.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return (default 8000, max 32000).

    Returns the page text content, truncated if necessary.
    """
    max_chars = max(500, min(32000, max_chars))

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return f"Error: Request timed out fetching {url}"
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP {e.response.status_code} fetching {url}"
    except requests.exceptions.RequestException as e:
        return f"Error fetching {url}: {e}"

    content_type = resp.headers.get("content-type", "")

    # Handle non-HTML (plain text, JSON, etc.)
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        if "json" in content_type:
            text = resp.text
        elif "text/" in content_type:
            text = resp.text
        else:
            return f"Error: Unsupported content type '{content_type}' for {url}"
    else:
        text = _html_to_text(resp.text)

    if not text.strip():
        return f"No readable content found at {url}"

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... [truncated — {len(text) - max_chars} more chars available. Call fetch_url with a larger max_chars to read more.]"

    return f"Content from {url}:\n\n{text}"


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web using DuckDuckGo. Returns titles, URLs, and snippets. "
                "Use search_type='news' for recent news articles. "
                "After finding relevant URLs, use fetch_url to read the full content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (1–10). Default 5.",
                        "default": 5,
                    },
                    "search_type": {
                        "type": "string",
                        "enum": ["text", "news"],
                        "description": "Search type: 'text' for general web, 'news' for recent news. Default 'text'.",
                        "default": "text",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch a URL and return its readable text content (HTML stripped). "
                "Useful for reading full articles, documentation, or any web page. "
                "Typical workflow: web_search → fetch_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return (default 8000, max 32000).",
                        "default": 8000,
                    },
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_MAPPING = {
    "web_search": web_search,
    "fetch_url": fetch_url,
}
