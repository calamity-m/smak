================================================================================
WORKFLOW SMOKE TESTS — COMPLETE PROJECT
================================================================================


STRUCTURE
=========

workflow-smoke-tests/
│
│── .gitlab-ci.yml          # CI: scheduled pipeline + parallel execution
│── pyproject.toml           # pytest config (markers, junit output)
│── requirements.txt         # 5 deps: pytest, pytest-xdist, tenacity, rich, requests
│
│── config.py                # env-aware config (set once via env vars, never touch again)
│── clients.py               # API client + workflow trigger (adapt to your endpoints)
│── polling.py               # tenacity-based poll helpers (set up once)
│── test_data.py             # payload factory with unique test IDs
│── notifier.py              # mattermost message builder
│── conftest.py              # pytest fixtures + rich output + notification hook
│
└── tests/
    │── __init__.py
    │── test_happy_path.py   # template — copy for new tests
    └── test_multi_step.py   # example: multi-stage workflow


HOW IT FLOWS
============

  pytest -n auto
    │
    ├─ worker 1: test_happy_path.py
    │    ├─ test_basic_workflow_completes()
    │    │    make_payload() → trigger.start_process() → poll_for_status() → assert
    │    ├─ test_workflow_produces_correct_output()
    │    │    make_payload() → trigger.start_process() → poll_for_status() → assert
    │    └─ test_workflow_handles_invalid_input()
    │         make_payload() → trigger.start_process() → poll_for_status() → assert
    │
    ├─ worker 2: test_multi_step.py
    │    ├─ test_multi_step_workflow()
    │    └─ test_large_batch_workflow()
    │
    └─ worker N: test_whatever_you_add_next.py
         └─ ...

  All workers run simultaneously. Each test:
    1. Generates unique test data (identifiable in your DB)
    2. Triggers the workflow
    3. Polls YOUR microservice API (not the workflow engine)
    4. Asserts the result

  On finish: rich summary table + mattermost ping if failed


================================================================================
FILE: requirements.txt
================================================================================

requests>=2.28.0
tenacity>=8.0.0
rich>=13.0.0
pytest>=7.0.0
pytest-xdist>=3.0.0


================================================================================
FILE: pyproject.toml
================================================================================

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "critical: tests for the most important hot paths",
    "slow: tests that take a long time to poll",
]

# JUnit XML for GitLab CI test reporting (shows pass/fail in merge requests)
addopts = "--junitxml=report.xml -v"


================================================================================
FILE: .gitlab-ci.yml
================================================================================

# .gitlab-ci.yml
#
# Schedule this: Settings > CI/CD > Pipeline schedules
# Recommended: "0 7 * * 1-5" (7am weekdays, before standup)
#
# Run all tests in parallel:         pytest -n auto
# Run only critical hot path tests:  pytest -n auto -m critical
# Run a single test:                 pytest tests/test_happy_path.py::test_basic_workflow_completes

stages:
  - smoke-test

smoke-test:
  stage: smoke-test
  image: python:3.11-slim
  variables:
    # Set these in GitLab CI/CD Variables (Settings > CI/CD > Variables):
    #   SMOKE_API_BASE_URL
    #   SMOKE_WORKFLOW_TRIGGER_URL
    #   SMOKE_MATTERMOST_WEBHOOK
    #   SMOKE_ENV (default: qa)
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.pip-cache"
  cache:
    paths:
      - .pip-cache/
  before_script:
    - pip install -r requirements.txt
  script:
    # -n auto = use as many workers as there are CPU cores
    # all test files run in parallel, each test case can run simultaneously
    - pytest -n auto --junitxml=report.xml
  artifacts:
    when: always
    reports:
      junit: report.xml
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "web"      # manual trigger from UI
    - if: $CI_COMMIT_BRANCH == "main"        # test changes to tests

# Optional: run only critical tests on a tighter schedule
smoke-test-critical:
  extends: smoke-test
  script:
    - pytest -n auto -m critical --junitxml=report.xml
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule" && $CRITICAL_ONLY == "true"


================================================================================
FILE: config.py
================================================================================

"""
Configuration per environment.
All values come from env vars with sensible defaults.
Set once in GitLab CI/CD variables and forget about it.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    environment: str
    api_base_url: str
    workflow_trigger_url: str
    mattermost_webhook_url: str
    poll_interval: int
    poll_timeout: int
    notify_on_success: bool

    @classmethod
    def from_env(cls) -> "Config":
        env = os.getenv("SMOKE_ENV", "qa")

        defaults = {
            "qa": {
                "api_base_url": "https://your-microservice.qa.internal/api",
                "workflow_trigger_url": "https://your-workflow-trigger.qa.internal",
            },
            "staging": {
                "api_base_url": "https://your-microservice.staging.internal/api",
                "workflow_trigger_url": "https://your-workflow-trigger.staging.internal",
            },
        }

        env_defaults = defaults.get(env, defaults["qa"])

        return cls(
            environment=env,
            api_base_url=os.getenv("SMOKE_API_BASE_URL", env_defaults["api_base_url"]),
            workflow_trigger_url=os.getenv("SMOKE_WORKFLOW_TRIGGER_URL", env_defaults["workflow_trigger_url"]),
            mattermost_webhook_url=os.getenv("SMOKE_MATTERMOST_WEBHOOK", ""),
            poll_interval=int(os.getenv("SMOKE_POLL_INTERVAL", "5")),
            poll_timeout=int(os.getenv("SMOKE_POLL_TIMEOUT", "300")),
            notify_on_success=os.getenv("SMOKE_NOTIFY_ON_SUCCESS", "").lower() in ("1", "true", "yes"),
        )


================================================================================
FILE: clients.py
================================================================================

"""
Thin HTTP clients for your microservice and the workflow trigger.
Adapt these to match your actual endpoints.
"""
import requests


class APIClient:
    """Talks to your Java microservice API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        # Add auth if needed:
        # self.session.headers["Authorization"] = f"Bearer {os.getenv('API_TOKEN')}"

    def get(self, path: str, **kwargs) -> requests.Response:
        resp = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def post(self, path: str, json: dict | None = None, **kwargs) -> requests.Response:
        resp = self.session.post(f"{self.base_url}/{path.lstrip('/')}", json=json, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp


class WorkflowTrigger:
    """
    Wraps whatever kicks off a workflow run.
    Adapt start_process() to match your actual trigger mechanism.
    If old mate's script does something other than an HTTP call,
    just replace the body of this method.
    """

    def __init__(self, trigger_url: str):
        self.trigger_url = trigger_url
        self.session = requests.Session()

    def start_process(self, payload: dict) -> dict:
        resp = self.session.post(self.trigger_url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()


================================================================================
FILE: test_data.py
================================================================================

"""
Test data generation.
Every payload gets a unique, identifiable ID so you can find test data
in your DB and it never collides with real data.
"""
import uuid
from datetime import datetime


def make_test_id(prefix: str = "smoke") -> str:
    """e.g. smoke-a3f8b2"""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def make_uuid() -> str:
    return str(uuid.uuid4())


def make_payload(overrides: dict | None = None) -> dict:
    """
    Build a base test input payload.
    Override specific fields per test case.

    Usage:
        data = make_payload({"customer_name": "Test Corp", "amount": 420.69})
    """
    base = {
        "test_id": make_test_id(),
        "correlation_id": make_uuid(),
        "timestamp": datetime.now().isoformat(),
        # Add your default fields here - whatever every workflow needs:
        # "entity_id": make_uuid(),
        # "entity_type": "test",
    }
    if overrides:
        base.update(overrides)
    return base


================================================================================
FILE: polling.py
================================================================================

"""
Polling helpers built on tenacity.
These are just thin wrappers so your tests read cleanly.
"""
from tenacity import (
    retry,
    retry_if_result,
    stop_after_delay,
    wait_fixed,
    RetryError,
)

from clients import APIClient


class PollTimeout(Exception):
    """Raised when we give up waiting for a result."""
    pass


def poll_for_status(
    api: APIClient,
    path: str,
    expected_status: str,
    status_field: str = "status",
    timeout: int = 300,
    interval: int = 5,
) -> dict:
    """
    Poll an API endpoint until a field matches the expected value.

    Returns the full response dict on success.
    Raises PollTimeout if it doesn't arrive in time.

    Usage:
        result = poll_for_status(
            api=api,
            path=f"/entities/{entity_id}",
            expected_status="COMPLETED",
            timeout=120,
        )
    """

    @retry(
        retry=retry_if_result(lambda r: r is None),
        stop=stop_after_delay(timeout),
        wait=wait_fixed(interval),
        reraise=True,
    )
    def _check():
        resp = api.get(path)
        data = resp.json()
        if data.get(status_field) == expected_status:
            return data
        return None

    try:
        return _check()
    except RetryError:
        # One last check to get the actual status for the error message
        try:
            final = api.get(path).json()
            actual = final.get(status_field, "unknown")
        except Exception:
            actual = "unreachable"

        raise PollTimeout(
            f"Timed out after {timeout}s waiting for {status_field}='{expected_status}' "
            f"at {path} (last seen: '{actual}')"
        )


def poll_until(
    fn,
    timeout: int = 300,
    interval: int = 5,
    description: str = "condition",
) -> any:
    """
    Generic poller. Call fn() repeatedly until it returns a truthy value.

    fn should return:
      - The result when condition is met
      - None/False when still waiting

    Usage:
        result = poll_until(
            fn=lambda: check_something(),
            timeout=120,
            description="thing to happen",
        )
    """

    @retry(
        retry=retry_if_result(lambda r: r is None),
        stop=stop_after_delay(timeout),
        wait=wait_fixed(interval),
        reraise=True,
    )
    def _check():
        return fn()

    try:
        return _check()
    except RetryError:
        raise PollTimeout(f"Timed out after {timeout}s waiting for: {description}")


================================================================================
FILE: notifier.py
================================================================================

"""
Mattermost notification as a pytest plugin.
Hooks into pytest's session finish to send results automatically.
No manual wiring needed - just having this file in conftest.py is enough.
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
        # Truncate long tracebacks for readability in chat
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


================================================================================
FILE: conftest.py
================================================================================

"""
conftest.py — pytest configuration and fixtures.

This is the "set up once and forget" file. It provides:
  - Shared fixtures (config, api client, workflow trigger)
  - Rich terminal output (replaces pytest's default)
  - Mattermost notifications on completion
  - Parallel execution support via pytest-xdist

All tests get access to these fixtures automatically.
"""
import time
import pytest
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from config import Config
from clients import APIClient, WorkflowTrigger
from notifier import send_mattermost, build_failure_message, build_success_message

console = Console()


# ---------------------------------------------------------------------------
# Fixtures — available to all tests automatically
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def config():
    """Load config once per test session."""
    return Config.from_env()


@pytest.fixture(scope="session")
def api(config):
    """API client for your Java microservice. Shared across all tests."""
    return APIClient(config.api_base_url)


@pytest.fixture(scope="session")
def trigger(config):
    """Workflow trigger client. Shared across all tests."""
    return WorkflowTrigger(config.workflow_trigger_url)


@pytest.fixture(scope="session")
def poll_config(config):
    """Polling defaults. Use in poll_for_status/poll_until calls."""
    return {
        "timeout": config.poll_timeout,
        "interval": config.poll_interval,
    }


# ---------------------------------------------------------------------------
# Rich output — pretty print test progress and results
# ---------------------------------------------------------------------------

class RichTerminalReporter:
    """
    Custom pytest plugin that uses Rich for terminal output.
    Replaces the default dots/letters with clear pass/fail indicators.
    """

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

    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self, session):
        self._start_time = time.time()
        config = Config.from_env()
        console.print()
        console.rule(f"[bold cyan]Smoke Tests — {config.environment.upper()}[/bold cyan]")
        console.print()

    @pytest.hookimpl(hookimpl=True)
    def pytest_runtest_logreport(self, report):
        if report.when != "call":
            return

        test_name = report.nodeid.split("::")[-1]

        if report.passed:
            self._results["passed"] += 1
            console.print(f"  [green]✓[/green] {test_name} [dim]({report.duration:.1f}s)[/dim]")
        elif report.failed:
            self._results["failed"] += 1
            console.print(f"  [red]✗[/red] {test_name} [dim]({report.duration:.1f}s)[/dim]")
            self._results["failure_details"][test_name] = {
                "longrepr": str(report.longrepr),
            }
        elif report.skipped:
            console.print(f"  [yellow]○[/yellow] {test_name} [dim](skipped)[/dim]")

        self._results["total"] += 1

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_makereport(self, item, call):
        """Capture errors during setup/teardown."""
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
            console.print()
            console.print(Panel(
                details["longrepr"],
                title=f"[red]FAILED: {name}[/red]",
                border_style="red",
                expand=True,
            ))

    def _send_notification(self):
        config = Config.from_env()
        webhook = config.mattermost_webhook_url
        if not webhook:
            return

        r = self._results
        if r["failed"] or r["errors"]:
            msg = build_failure_message(config.environment, r)
            send_mattermost(webhook, msg)
        elif config.notify_on_success:
            msg = build_success_message(config.environment, r)
            send_mattermost(webhook, msg)


# Register the plugin
_reporter = RichTerminalReporter()


def pytest_configure(config):
    config.pluginmanager.register(_reporter, "rich-reporter")


================================================================================
FILE: tests/test_happy_path.py
================================================================================

"""
Example: happy path smoke test.

Copy this file for each new test scenario. Each test function:
  - Gets fixtures (api, trigger, poll_config) injected automatically by pytest
  - Uses test_data to generate identifiable payloads
  - Uses polling helpers to wait for results
  - Just asserts — pytest handles the rest

Run all tests in parallel:
    pytest -n auto

Run just the critical ones:
    pytest -m critical

Run a single test:
    pytest tests/test_happy_path.py::test_basic_workflow_completes
"""
import pytest

from test_data import make_payload
from polling import poll_for_status, poll_until, PollTimeout


@pytest.mark.critical
def test_basic_workflow_completes(api, trigger, poll_config):
    """
    The most basic test: trigger a workflow, wait for it to complete,
    verify the result landed in the DB via your microservice API.
    """
    # 1. Build test input
    payload = make_payload({
        # Your workflow-specific fields here:
        # "customer_id": make_uuid(),
        # "order_type": "standard",
        # "amount": 100.00,
    })
    test_id = payload["test_id"]

    # 2. Trigger the workflow
    result = trigger.start_process(payload)
    # Grab whatever ID the trigger returns that you'll use to look it up:
    # entity_id = result["id"]
    entity_id = test_id  # adjust to match your actual lookup

    # 3. Poll your microservice API for the expected result
    data = poll_for_status(
        api=api,
        path=f"/entities/{entity_id}",
        expected_status="COMPLETED",
        **poll_config,
    )

    # 4. Assert on the result
    assert data is not None, "Expected result data but got None"
    # assert data["output_field"] == "expected_value"
    # assert data.get("error") is None, f"Unexpected error: {data.get('error')}"


@pytest.mark.critical
def test_workflow_produces_correct_output(api, trigger, poll_config):
    """
    Example: verify the workflow not only completes, but produces
    the right output data.
    """
    payload = make_payload({
        # "input_value": 42,
    })
    test_id = payload["test_id"]

    trigger.start_process(payload)

    data = poll_for_status(
        api=api,
        path=f"/entities/{test_id}",
        expected_status="COMPLETED",
        **poll_config,
    )

    # Assert on the actual business logic output
    assert data is not None
    # assert data["computed_result"] == 84  # or whatever the expected output is


def test_workflow_handles_invalid_input(api, trigger, poll_config):
    """
    Example: verify the workflow handles bad input gracefully
    instead of silently eating it.
    """
    payload = make_payload({
        # "amount": -1,  # invalid
    })
    test_id = payload["test_id"]

    trigger.start_process(payload)

    # Maybe this one should end up in an ERROR or REJECTED state
    data = poll_for_status(
        api=api,
        path=f"/entities/{test_id}",
        expected_status="REJECTED",  # or "ERROR" or whatever your system uses
        **poll_config,
    )

    assert data is not None
    # assert "error" in data or data.get("rejection_reason") is not None


================================================================================
FILE: tests/test_multi_step.py
================================================================================

"""
Example: multi-step workflow test.

For workflows that go through multiple stages, you can
poll for each stage sequentially, or just poll for the final state.
"""
import pytest

from test_data import make_payload
from polling import poll_for_status


@pytest.mark.slow
def test_multi_step_workflow(api, trigger, poll_config):
    """
    Example: a workflow that goes PENDING -> PROCESSING -> COMPLETED.
    We verify it reaches COMPLETED without getting stuck.
    """
    payload = make_payload({
        # "workflow_type": "multi_step",
    })
    test_id = payload["test_id"]

    trigger.start_process(payload)

    # If you want to verify intermediate states, poll for each:
    #
    # poll_for_status(
    #     api=api,
    #     path=f"/entities/{test_id}",
    #     expected_status="PROCESSING",
    #     timeout=60,  # shorter timeout for intermediate states
    #     interval=poll_config["interval"],
    # )

    # Then poll for the final state
    data = poll_for_status(
        api=api,
        path=f"/entities/{test_id}",
        expected_status="COMPLETED",
        **poll_config,
    )

    assert data is not None


@pytest.mark.slow
def test_large_batch_workflow(api, trigger, poll_config):
    """
    Example: trigger a workflow with a larger dataset.
    Give it more time since it's expected to take longer.
    """
    payload = make_payload({
        # "batch_size": 100,
    })
    test_id = payload["test_id"]

    trigger.start_process(payload)

    data = poll_for_status(
        api=api,
        path=f"/entities/{test_id}",
        expected_status="COMPLETED",
        timeout=600,  # 10 min for the big one
        interval=poll_config["interval"],
    )

    assert data is not None
    # assert data["processed_count"] == 100
