from __future__ import annotations

import os
import re
import urllib.request
import urllib.parse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("browser")


def _is_mock() -> bool:
    return os.environ.get("BROWSER_MOCK") == "true" or os.environ.get("OFFLINE") == "true"


def _clean_html(html: str) -> str:
    html = re.sub(r"<(script|style).*?>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]*>", "", html)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


@mcp.tool()
def browser_open(url: str) -> str:
    """Open a URL and return parsed textual content.

    Permissions: web_access
    Categories: web, browser
    Usage: Open a web page and read its text.
    """
    if _is_mock():
        return f"MOCK: Content from '{url}': Welcome to mock web page. This is mock browser content."

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Nakama-Kun-MCP"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")
            return _clean_html(html)
    except Exception as e:
        return f"ERROR: Failed to open '{url}': {e}"


@mcp.tool()
def browser_search(query: str) -> str:
    """Search the web for a query.

    Permissions: web_access
    Categories: web, browser
    Usage: Search web pages using DuckDuckGo HTML version.
    """
    if _is_mock():
        return f"MOCK: Search results for '{query}': Result 1: 'Mock Result 1' - URL: http://example.com/1"

    search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": "Nakama-Kun-MCP"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")
            links = re.findall(r'<a class="result__url" href="([^"]+)"', html)
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, flags=re.DOTALL)
            titles = re.findall(r'<a class="result__a"[^>]*>(.*?)</a>', html, flags=re.DOTALL)

            results = []
            for i in range(min(5, len(titles))):
                title = _clean_html(titles[i])
                link = links[i] if i < len(links) else ""
                snippet = _clean_html(snippets[i]) if i < len(snippets) else ""
                results.append(f"{i+1}. {title}\nURL: {link}\nSnippet: {snippet}")

            if not results:
                cleaned = _clean_html(html)
                return f"No formatted results found. DDG output:\n{cleaned[:1000]}"
            return "\n\n".join(results)
    except Exception as e:
        return f"ERROR: Failed to execute search: {e}"


@mcp.tool()
def browser_extract_content(url: str) -> str:
    """Extract plain text body content from a URL.

    Permissions: web_access
    Categories: web, browser
    Usage: Extract clean readable body text from a webpage.
    """
    return browser_open(url)


if __name__ == "__main__":
    mcp.run()
