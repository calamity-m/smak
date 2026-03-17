"""
conftest.py — pytest configuration and fixtures.

Provides:
  - Shared fixtures (config, api client, workflow trigger)
  - Rich terminal output
  - Mattermost notifications on completion
  - Parallel execution support via pytest-xdist
"""
import time

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clients import APIClient, WorkflowTrigger
from config import Config
from github_issues import create_issues_for_failures as github_create_issues
from gitlab_issues import create_issues_for_failures as gitlab_create_issues
from notifier import build_failure_message, build_success_message, send_mattermost

console = Console()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def config():
    """Load config once per test session."""
    return Config.from_env()


@pytest.fixture(scope="session")
def api(config):
    """API client for your microservice."""
    return APIClient(config.api_base_url)


@pytest.fixture(scope="session")
def trigger(config):
    """Workflow trigger client."""
    return WorkflowTrigger(config.workflow_trigger_url)


@pytest.fixture(scope="session")
def poll_config(config):
    """Polling defaults. Use in poll_for_status/poll_until calls."""
    return {
        "timeout": config.poll_timeout,
        "interval": config.poll_interval,
    }


@pytest.fixture()
def test_context(request):
    """
    Stash key-value pairs for triage. Anything you put here shows up
    in the failure notification and Rich output if the test fails.

    Usage:
        def test_something(api, trigger, test_context):
            test_context["request_id"] = "abc-123"
            test_context["entity_id"] = entity_id
            ...
    """
    ctx = {}
    request.node._test_context = ctx
    return ctx


# ---------------------------------------------------------------------------
# Rich output plugin
# ---------------------------------------------------------------------------

class RichTerminalReporter:
    def __init__(self):
        self._results = {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "duration": 0.0,
            "failure_details": {},
        }
        self._start_time = None
        self._test_contexts = {}  # nodeid -> {key: value} from test_context fixture

    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self, session):
        self._start_time = time.time()
        config = Config.from_env()
        console.print()
        console.rule(f"[bold cyan]Smoke Tests — {config.environment.upper()}[/bold cyan]")
        console.print()

    @pytest.hookimpl()
    def pytest_runtest_logreport(self, report):
        if report.when != "call":
            return

        test_name = report.nodeid.split("::")[-1]

        if report.passed:
            self._results["passed"] += 1
            console.print(f"  [green]✓[/green] {test_name} [dim]({report.duration:.1f}s)[/dim]")
        elif report.failed:
            self._results["failed"] += 1
            ctx = self._test_contexts.get(report.nodeid, {})
            ctx_line = ""
            if ctx:
                ctx_line = "  " + " | ".join(f"{k}={v}" for k, v in ctx.items())
                console.print(f"  [red]✗[/red] {test_name} [dim]({report.duration:.1f}s)[/dim]")
                console.print(f"    [dim]{ctx_line.strip()}[/dim]")
            else:
                console.print(f"  [red]✗[/red] {test_name} [dim]({report.duration:.1f}s)[/dim]")
            self._results["failure_details"][test_name] = {
                "longrepr": str(report.longrepr),
                "context": ctx,
            }
        elif report.skipped:
            console.print(f"  [yellow]○[/yellow] {test_name} [dim](skipped)[/dim]")

        self._results["total"] += 1

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_makereport(self, item, call):
        # Capture test_context from the fixture before the item is torn down
        if call.when == "call":
            ctx = getattr(item, "_test_context", None)
            if ctx:
                self._test_contexts[item.nodeid] = dict(ctx)
        if call.when == "setup" and call.excinfo is not None:
            self._results["errors"] += 1
            test_name = item.nodeid.split("::")[-1]
            console.print(f"  [red]⚠[/red] {test_name} [dim](setup error)[/dim]")

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        self._results["duration"] = time.time() - (self._start_time or time.time())

        console.print()
        self._print_summary_table()
        self._print_failures()
        self._send_notification()

    def _print_summary_table(self):
        r = self._results
        passed = r["passed"]
        failed = r["failed"]
        errors = r["errors"]
        duration = r["duration"]

        if failed or errors:
            status = "[bold red]FAILED[/bold red]"
            border_style = "red"
        else:
            status = "[bold green]PASSED[/bold green]"
            border_style = "green"

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Status", status)
        table.add_row("Passed", f"[green]{passed}[/green]")
        if failed:
            table.add_row("Failed", f"[red]{failed}[/red]")
        if errors:
            table.add_row("Errors", f"[red]{errors}[/red]")
        table.add_row("Duration", f"{duration:.1f}s")

        console.print(Panel(table, title="Summary", border_style=border_style))

    def _print_failures(self):
        for name, details in self._results["failure_details"].items():
            ctx = details.get("context", {})
            body = ""
            if ctx:
                body += " | ".join(f"{k}={v}" for k, v in ctx.items()) + "\n\n"
            body += details["longrepr"]
            console.print()
            console.print(Panel(
                body,
                title=f"[red]FAILED: {name}[/red]",
                border_style="red",
                expand=True,
            ))

    def _send_notification(self):
        config = Config.from_env()
        r = self._results

        if r["failed"] or r["errors"]:
            # Mattermost
            webhook = config.mattermost_webhook_url
            if webhook:
                msg = build_failure_message(config.environment, r)
                send_mattermost(webhook, msg)

            # Issues (fires whichever are configured, skips the rest)
            gitlab_create_issues(config.environment, r["failure_details"])
            github_create_issues(config.environment, r["failure_details"])

        elif config.notify_on_success:
            webhook = config.mattermost_webhook_url
            if webhook:
                msg = build_success_message(config.environment, r)
                send_mattermost(webhook, msg)


_reporter = RichTerminalReporter()


def pytest_configure(config):
    config.pluginmanager.register(_reporter, "rich-reporter")
