"""
Mattermost notification builder.
Hooks into pytest via conftest.py to send results automatically.
"""

import requests as http_requests
from rich.console import Console

console = Console()


def send_mattermost(webhook_url: str, payload: dict):
    if not webhook_url:
        return
    try:
        http_requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        console.print(f"[dim]Failed to send Mattermost notification: {e}[/dim]")


def build_failure_message(environment: str, results: dict) -> dict:
    """Build a Mattermost message for failed runs."""
    header = (
        f"### :x: Smoke Test FAILED — {environment.upper()}\n"
        f"**Results:** {results['passed']} passed, {results['failed']} failed, "
        f"{results['errors']} errors ({results['duration']:.1f}s)\n"
    )

    failure_lines = []
    for name, details in results.get("failure_details", {}).items():
        failure_lines.append(f"#### :rotating_light: `{name}`")

        ctx = details.get("context", {})
        if ctx:
            ctx_str = " | ".join(f"**{k}:** `{v}`" for k, v in ctx.items())
            failure_lines.append(ctx_str)

        traceback_text = details.get("longrepr", "No details available")
        if len(traceback_text) > 800:
            traceback_text = traceback_text[:800] + "\n... (truncated)"
        failure_lines.append(f"```\n{traceback_text}\n```")

    body = header + "\n---\n" + "\n---\n".join(failure_lines)

    return {
        "username": "smoke-test",
        "icon_emoji": ":fire:",
        "text": body,
    }


def build_success_message(environment: str, results: dict) -> dict:
    return {
        "username": "smoke-test",
        "icon_emoji": ":white_check_mark:",
        "text": (
            f"### :white_check_mark: Smoke Test PASSED — {environment.upper()}\n"
            f"**Results:** {results['passed']}/{results['total']} passed "
            f"({results['duration']:.1f}s)"
        ),
    }
