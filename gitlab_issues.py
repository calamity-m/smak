"""
GitLab issue creation for failed smoke tests.

Creates one issue per failing test. Deduplicates by searching for open issues
with the "smoke-test-failure" label and the test name in the title — if one
already exists, it adds a comment with the latest run details instead.

Requires:
  SMOKE_GITLAB_TOKEN      — project or personal access token (api scope)
  SMOKE_GITLAB_PROJECT_ID — numeric project ID (Settings > General)
  SMOKE_GITLAB_URL        — optional, defaults to https://gitlab.com
"""

import os

import requests as http_requests
from rich.console import Console

from issue_body import build_comment_body, build_issue_body

console = Console()

LABEL = "smoke-test-failure"


def is_configured() -> bool:
    return bool(os.getenv("SMOKE_GITLAB_TOKEN")) and bool(os.getenv("SMOKE_GITLAB_PROJECT_ID"))


def _headers() -> dict:
    return {"PRIVATE-TOKEN": os.getenv("SMOKE_GITLAB_TOKEN", "")}


def _base_url() -> str:
    return os.getenv("SMOKE_GITLAB_URL", "https://gitlab.com").rstrip("/")


def _ensure_label_exists(base_url: str, project_id: str, headers: dict):
    """Create the label if it doesn't exist yet."""
    url = f"{base_url}/api/v4/projects/{project_id}/labels"
    resp = http_requests.get(url, headers=headers, params={"search": LABEL}, timeout=10)
    if resp.ok and any(label["name"] == LABEL for label in resp.json()):
        return
    http_requests.post(
        url,
        headers=headers,
        json={"name": LABEL, "color": "#DC3545", "description": "Auto-created by smoke tests"},
        timeout=10,
    )


def _find_open_issue(base_url: str, project_id: str, headers: dict, test_name: str) -> dict | None:
    """Find an existing open issue for this test."""
    url = f"{base_url}/api/v4/projects/{project_id}/issues"
    resp = http_requests.get(
        url,
        headers=headers,
        params={
            "labels": LABEL,
            "state": "opened",
            "search": test_name,
            "in": "title",
        },
        timeout=10,
    )
    if not resp.ok:
        return None
    for issue in resp.json():
        if test_name in issue["title"]:
            return issue
    return None


def create_issues_for_failures(environment: str, failure_details: dict):
    """
    Create or update GitLab issues for each failed test.
    Silently skips if not configured.
    """
    if not is_configured():
        return

    project_id = os.getenv("SMOKE_GITLAB_PROJECT_ID", "")
    base_url = _base_url()
    headers = _headers()

    try:
        _ensure_label_exists(base_url, project_id, headers)
    except Exception as e:
        console.print(f"[dim]GitLab: failed to ensure label: {e}[/dim]")

    for test_name, details in failure_details.items():
        try:
            existing = _find_open_issue(base_url, project_id, headers, test_name)

            if existing:
                issue_iid = existing["iid"]
                comment_url = f"{base_url}/api/v4/projects/{project_id}/issues/{issue_iid}/notes"
                body = build_comment_body(environment, details)
                http_requests.post(
                    comment_url,
                    headers=headers,
                    json={"body": body},
                    timeout=10,
                )
                console.print(f"  [dim]GitLab: updated issue #{issue_iid} for {test_name}[/dim]")
            else:
                issues_url = f"{base_url}/api/v4/projects/{project_id}/issues"
                body = build_issue_body(environment, test_name, details)
                resp = http_requests.post(
                    issues_url,
                    headers=headers,
                    json={
                        "title": f"Smoke test failure: {test_name}",
                        "description": body,
                        "labels": LABEL,
                    },
                    timeout=10,
                )
                if resp.ok:
                    iid = resp.json()["iid"]
                    web_url = resp.json()["web_url"]
                    console.print(f"  [dim]GitLab: created issue #{iid} for {test_name}: {web_url}[/dim]")
                else:
                    console.print(f"  [dim]GitLab: failed to create issue for {test_name}: {resp.status_code}[/dim]")

        except Exception as e:
            console.print(f"  [dim]GitLab: failed to create/update issue for {test_name}: {e}[/dim]")
