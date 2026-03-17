"""
GitHub issue creation for failed smoke tests.

Creates one issue per failing test. Deduplicates by searching for open issues
with the "smoke-test-failure" label and the test name in the title — if one
already exists, it adds a comment with the latest run details instead.

Requires:
  SMOKE_GITHUB_TOKEN — personal access token or GitHub App token (issues write)
  SMOKE_GITHUB_REPO  — owner/repo (e.g. "acme/smoke-tests")
  SMOKE_GITHUB_URL   — optional, defaults to https://api.github.com (for GHES)
"""
import os

import requests as http_requests
from rich.console import Console

from issue_body import build_comment_body, build_issue_body

console = Console()

LABEL = "smoke-test-failure"


def is_configured() -> bool:
    return bool(os.getenv("SMOKE_GITHUB_TOKEN")) and bool(os.getenv("SMOKE_GITHUB_REPO"))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('SMOKE_GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _base_url() -> str:
    return os.getenv("SMOKE_GITHUB_URL", "https://api.github.com").rstrip("/")


def _ensure_label_exists(base_url: str, repo: str, headers: dict):
    """Create the label if it doesn't exist yet."""
    url = f"{base_url}/repos/{repo}/labels/{LABEL}"
    resp = http_requests.get(url, headers=headers, timeout=10)
    if resp.ok:
        return
    http_requests.post(
        f"{base_url}/repos/{repo}/labels",
        headers=headers,
        json={"name": LABEL, "color": "DC3545", "description": "Auto-created by smoke tests"},
        timeout=10,
    )


def _find_open_issue(base_url: str, repo: str, headers: dict, test_name: str) -> dict | None:
    """Find an existing open issue for this test."""
    url = f"{base_url}/search/issues"
    query = f"repo:{repo} is:issue is:open label:{LABEL} in:title {test_name}"
    resp = http_requests.get(
        url,
        headers=headers,
        params={"q": query},
        timeout=10,
    )
    if not resp.ok:
        return None
    for issue in resp.json().get("items", []):
        if test_name in issue["title"]:
            return issue
    return None


def create_issues_for_failures(environment: str, failure_details: dict):
    """
    Create or update GitHub issues for each failed test.
    Silently skips if not configured.
    """
    if not is_configured():
        return

    repo = os.getenv("SMOKE_GITHUB_REPO", "")
    base_url = _base_url()
    headers = _headers()

    try:
        _ensure_label_exists(base_url, repo, headers)
    except Exception as e:
        console.print(f"[dim]GitHub: failed to ensure label: {e}[/dim]")

    for test_name, details in failure_details.items():
        try:
            existing = _find_open_issue(base_url, repo, headers, test_name)

            if existing:
                issue_number = existing["number"]
                comment_url = f"{base_url}/repos/{repo}/issues/{issue_number}/comments"
                body = build_comment_body(environment, details)
                http_requests.post(
                    comment_url, headers=headers, json={"body": body}, timeout=10,
                )
                console.print(f"  [dim]GitHub: updated issue #{issue_number} for {test_name}[/dim]")
            else:
                issues_url = f"{base_url}/repos/{repo}/issues"
                body = build_issue_body(environment, test_name, details)
                resp = http_requests.post(
                    issues_url,
                    headers=headers,
                    json={
                        "title": f"Smoke test failure: {test_name}",
                        "body": body,
                        "labels": [LABEL],
                    },
                    timeout=10,
                )
                if resp.ok:
                    number = resp.json()["number"]
                    html_url = resp.json()["html_url"]
                    console.print(f"  [dim]GitHub: created issue #{number} for {test_name}: {html_url}[/dim]")
                else:
                    console.print(f"  [dim]GitHub: failed to create issue for {test_name}: {resp.status_code}[/dim]")

        except Exception as e:
            console.print(f"  [dim]GitHub: failed to create/update issue for {test_name}: {e}[/dim]")
