from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("github")


def _get_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT") or ""
    headers = {
        "User-Agent": "Nakama-Kun-MCP",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _is_mock() -> bool:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT") or ""
    return token.startswith("mock_") or token == "mock_token" or os.environ.get("GITHUB_MOCK") == "true"


@mcp.tool()
def github_create_issue(owner: str, repo: str, title: str, body: str) -> str:
    """Create a new GitHub issue.

    Permissions: github_write
    Categories: github, vcs
    Usage: Create an issue in a repository.
    """
    if _is_mock():
        return f"MOCK: Issue created successfully in '{owner}/{repo}' with title '{title}'."

    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    data = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_get_headers(), method="POST")
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            return f"Issue #{res_data.get('number')} created successfully: {res_data.get('html_url')}"
    except Exception as e:
        return f"ERROR: Failed to create issue: {e}"


@mcp.tool()
def github_get_issue(owner: str, repo: str, issue_number: int) -> str:
    """Get details of a GitHub issue.

    Permissions: github_read
    Categories: github, vcs
    Usage: Retrieve an issue's details by number.
    """
    if _is_mock():
        return f"MOCK: Details for issue #{issue_number} in '{owner}/{repo}': Title: 'Mock Issue', State: 'open'."

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    req = urllib.request.Request(url, headers=_get_headers())
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            return f"Issue #{res_data.get('number')}: {res_data.get('title')} ({res_data.get('state')})\nURL: {res_data.get('html_url')}\nBody:\n{res_data.get('body')}"
    except Exception as e:
        return f"ERROR: Failed to get issue: {e}"


@mcp.tool()
def github_list_prs(owner: str, repo: str, state: str = "open") -> str:
    """List open or closed PRs in a GitHub repository.

    Permissions: github_read
    Categories: github, vcs
    Usage: Retrieve a list of pull requests.
    """
    if _is_mock():
        return f"MOCK: List of {state} PRs in '{owner}/{repo}': PR #1 'Mock PR' by mockuser."

    url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state={state}"
    req = urllib.request.Request(url, headers=_get_headers())
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            prs = []
            for pr in res_data:
                prs.append(f"PR #{pr.get('number')}: {pr.get('title')} ({pr.get('state')}) by {pr.get('user', {}).get('login')}")
            return "\n".join(prs) if prs else "No pull requests found."
    except Exception as e:
        return f"ERROR: Failed to list PRs: {e}"


@mcp.tool()
def github_search_repo(query: str) -> str:
    """Search for repositories on GitHub.

    Permissions: github_read
    Categories: github, vcs
    Usage: Search repositories by query.
    """
    if _is_mock():
        return f"MOCK: Repositories matching '{query}': 'owner/repo-mock' - Description: 'Mock Repo'."

    url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers=_get_headers())
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            items = res_data.get("items", [])
            repos = []
            for item in items[:5]:
                repos.append(f"{item.get('full_name')} ({item.get('stargazers_count')} stars) - {item.get('description')}\nURL: {item.get('html_url')}")
            return "\n\n".join(repos) if repos else "No repositories found."
    except Exception as e:
        return f"ERROR: Failed to search repositories: {e}"


if __name__ == "__main__":
    mcp.run()
