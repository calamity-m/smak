"""
Tests for the smoke test harness itself.
These run without any external connections — safe to run locally or in CI.

    pytest tests/test_harness.py
"""
from unittest.mock import MagicMock, call, patch

from config import Config
from test_data import make_payload, make_test_id, make_uuid
from polling import poll_for_status, poll_until, PollTimeout
from notifier import build_failure_message, build_success_message
from issue_body import build_issue_body, build_comment_body
from gitlab_issues import create_issues_for_failures as gitlab_create_issues
from github_issues import create_issues_for_failures as github_create_issues
from clients import APIClient, WorkflowTrigger

import pytest


# ---------------------------------------------------------------------------
# test_data
# ---------------------------------------------------------------------------

class TestTestData:
    def test_make_test_id_has_prefix(self):
        tid = make_test_id("smoke")
        assert tid.startswith("smoke-")
        assert len(tid) == len("smoke-") + 6

    def test_make_test_id_custom_prefix(self):
        tid = make_test_id("regression")
        assert tid.startswith("regression-")

    def test_make_uuid_format(self):
        uid = make_uuid()
        assert len(uid) == 36  # standard uuid4 string
        assert uid.count("-") == 4

    def test_make_payload_has_required_fields(self):
        p = make_payload()
        assert "test_id" in p
        assert "correlation_id" in p
        assert "timestamp" in p

    def test_make_payload_overrides(self):
        p = make_payload({"customer_name": "Test Corp", "amount": 420.69})
        assert p["customer_name"] == "Test Corp"
        assert p["amount"] == 420.69
        assert "test_id" in p  # base fields still present

    def test_make_payload_unique_ids(self):
        p1 = make_payload()
        p2 = make_payload()
        assert p1["test_id"] != p2["test_id"]
        assert p1["correlation_id"] != p2["correlation_id"]


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_defaults_to_qa(self):
        with patch.dict("os.environ", {}, clear=True):
            cfg = Config.from_env()
            assert cfg.environment == "qa"
            assert "qa" in cfg.api_base_url

    def test_staging_env(self):
        with patch.dict("os.environ", {"SMOKE_ENV": "staging"}, clear=True):
            cfg = Config.from_env()
            assert cfg.environment == "staging"
            assert "staging" in cfg.api_base_url

    def test_env_var_overrides(self):
        with patch.dict("os.environ", {
            "SMOKE_API_BASE_URL": "https://custom.example.com/api",
            "SMOKE_WORKFLOW_TRIGGER_URL": "https://custom.example.com/trigger",
            "SMOKE_POLL_INTERVAL": "10",
            "SMOKE_POLL_TIMEOUT": "600",
        }, clear=True):
            cfg = Config.from_env()
            assert cfg.api_base_url == "https://custom.example.com/api"
            assert cfg.workflow_trigger_url == "https://custom.example.com/trigger"
            assert cfg.poll_interval == 10
            assert cfg.poll_timeout == 600

    def test_notify_on_success_flag(self):
        with patch.dict("os.environ", {"SMOKE_NOTIFY_ON_SUCCESS": "true"}, clear=True):
            assert Config.from_env().notify_on_success is True
        with patch.dict("os.environ", {"SMOKE_NOTIFY_ON_SUCCESS": "no"}, clear=True):
            assert Config.from_env().notify_on_success is False
        with patch.dict("os.environ", {}, clear=True):
            assert Config.from_env().notify_on_success is False


# ---------------------------------------------------------------------------
# polling (with mocked API)
# ---------------------------------------------------------------------------

class TestPolling:
    def _mock_api(self, responses: list[dict]):
        """Create a mock APIClient that returns responses in sequence."""
        api = MagicMock(spec=APIClient)
        mock_responses = []
        for data in responses:
            resp = MagicMock()
            resp.json.return_value = data
            mock_responses.append(resp)
        api.get.side_effect = mock_responses
        return api

    def test_poll_for_status_immediate_match(self):
        api = self._mock_api([{"status": "COMPLETED", "result": "ok"}])

        data = poll_for_status(
            api=api,
            path="/entities/123",
            expected_status="COMPLETED",
            timeout=5,
            interval=0.1,
        )

        assert data["status"] == "COMPLETED"
        assert data["result"] == "ok"
        assert api.get.call_count == 1

    def test_poll_for_status_eventually_matches(self):
        api = self._mock_api([
            {"status": "PENDING"},
            {"status": "PROCESSING"},
            {"status": "COMPLETED", "result": "done"},
        ])

        data = poll_for_status(
            api=api,
            path="/entities/123",
            expected_status="COMPLETED",
            timeout=5,
            interval=0.1,
        )

        assert data["status"] == "COMPLETED"
        assert api.get.call_count == 3

    def test_poll_for_status_timeout(self):
        api = self._mock_api([{"status": "PENDING"}] * 100)

        with pytest.raises(PollTimeout, match="Timed out"):
            poll_for_status(
                api=api,
                path="/entities/123",
                expected_status="COMPLETED",
                timeout=0.5,
                interval=0.1,
            )

    def test_poll_until_immediate(self):
        result = poll_until(
            fn=lambda: {"done": True},
            timeout=5,
            interval=0.1,
            description="thing",
        )
        assert result == {"done": True}

    def test_poll_until_eventually(self):
        call_count = 0

        def check():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return "found it"
            return None

        result = poll_until(fn=check, timeout=5, interval=0.1, description="thing")
        assert result == "found it"
        assert call_count == 3

    def test_poll_until_timeout(self):
        with pytest.raises(PollTimeout, match="waiting for: thing"):
            poll_until(
                fn=lambda: None,
                timeout=0.5,
                interval=0.1,
                description="thing",
            )


# ---------------------------------------------------------------------------
# notifier message building
# ---------------------------------------------------------------------------

class TestNotifier:
    def _results(self, **overrides):
        base = {
            "passed": 2,
            "failed": 1,
            "errors": 0,
            "total": 3,
            "duration": 12.5,
            "failure_details": {
                "test_basic_workflow_completes": {
                    "longrepr": "AssertionError: expected COMPLETED got PENDING",
                    "context": {
                        "test_id": "smoke-abc123",
                        "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                        "request_id": "req-xyz-789",
                    },
                },
            },
        }
        base.update(overrides)
        return base

    def test_failure_message_includes_context(self):
        msg = build_failure_message("qa", self._results())
        text = msg["text"]

        assert "FAILED" in text
        assert "smoke-abc123" in text
        assert "550e8400-e29b-41d4-a716-446655440000" in text
        assert "req-xyz-789" in text
        assert "2 passed" in text
        assert "1 failed" in text

    def test_failure_message_without_context(self):
        results = self._results()
        results["failure_details"]["test_basic_workflow_completes"]["context"] = {}
        msg = build_failure_message("qa", results)
        assert "FAILED" in msg["text"]

    def test_failure_message_truncates_long_traceback(self):
        results = self._results()
        results["failure_details"]["test_basic_workflow_completes"]["longrepr"] = "x" * 1000
        msg = build_failure_message("qa", results)
        assert "truncated" in msg["text"]

    def test_success_message(self):
        msg = build_success_message("staging", {
            "passed": 5,
            "total": 5,
            "duration": 8.3,
        })
        assert "PASSED" in msg["text"]
        assert "STAGING" in msg["text"]
        assert "5/5" in msg["text"]

    def test_failure_message_metadata(self):
        msg = build_failure_message("qa", self._results())
        assert msg["username"] == "smoke-test"
        assert msg["icon_emoji"] == ":fire:"


# ---------------------------------------------------------------------------
# issue body (shared)
# ---------------------------------------------------------------------------

class TestIssueBody:
    def _details(self):
        return {
            "longrepr": "AssertionError: expected COMPLETED got PENDING",
            "context": {
                "test_id": "smoke-abc123",
                "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        }

    def test_build_issue_body_includes_context(self):
        body = build_issue_body("qa", "test_basic_workflow_completes", self._details())
        assert "smoke-abc123" in body
        assert "550e8400-e29b-41d4-a716-446655440000" in body
        assert "QA" in body
        assert "test_basic_workflow_completes" in body
        assert "AssertionError" in body

    def test_build_issue_body_includes_pipeline_url(self):
        with patch.dict("os.environ", {"CI_PIPELINE_URL": "https://gitlab.com/p/123"}):
            body = build_issue_body("qa", "test_basic_workflow_completes", self._details())
        assert "https://gitlab.com/p/123" in body

    def test_build_comment_body_includes_context(self):
        body = build_comment_body("qa", self._details())
        assert "Still failing" in body
        assert "smoke-abc123" in body
        assert "QA" in body


# ---------------------------------------------------------------------------
# gitlab issues
# ---------------------------------------------------------------------------

class TestGitlabIssues:
    def _failure_details(self):
        return {
            "test_basic_workflow_completes": {
                "longrepr": "AssertionError: expected COMPLETED got PENDING",
                "context": {
                    "test_id": "smoke-abc123",
                    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                },
            },
        }

    def test_skips_when_no_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("gitlab_issues.http_requests") as mock_http:
                gitlab_create_issues("qa", self._failure_details())
                mock_http.get.assert_not_called()
                mock_http.post.assert_not_called()

    def test_creates_new_issue_when_none_exists(self):
        env = {
            "SMOKE_GITLAB_TOKEN": "test-token",
            "SMOKE_GITLAB_PROJECT_ID": "42",
            "SMOKE_GITLAB_URL": "https://gitlab.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("gitlab_issues.http_requests") as mock_http:
                label_resp = MagicMock()
                label_resp.ok = True
                label_resp.json.return_value = []

                label_create_resp = MagicMock()
                label_create_resp.ok = True

                search_resp = MagicMock()
                search_resp.ok = True
                search_resp.json.return_value = []

                create_resp = MagicMock()
                create_resp.ok = True
                create_resp.json.return_value = {"iid": 99, "web_url": "https://gitlab.example.com/issues/99"}

                mock_http.get.side_effect = [label_resp, search_resp]
                mock_http.post.side_effect = [label_create_resp, create_resp]

                gitlab_create_issues("qa", self._failure_details())

                create_call = mock_http.post.call_args_list[-1]
                assert "issues" in create_call.args[0]
                assert create_call.kwargs["json"]["title"] == "Smoke test failure: test_basic_workflow_completes"
                assert "smoke-test-failure" in create_call.kwargs["json"]["labels"]

    def test_comments_on_existing_issue(self):
        env = {
            "SMOKE_GITLAB_TOKEN": "test-token",
            "SMOKE_GITLAB_PROJECT_ID": "42",
            "SMOKE_GITLAB_URL": "https://gitlab.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("gitlab_issues.http_requests") as mock_http:
                label_resp = MagicMock()
                label_resp.ok = True
                label_resp.json.return_value = [{"name": "smoke-test-failure"}]

                search_resp = MagicMock()
                search_resp.ok = True
                search_resp.json.return_value = [{
                    "iid": 42,
                    "title": "Smoke test failure: test_basic_workflow_completes",
                }]

                comment_resp = MagicMock()
                comment_resp.ok = True

                mock_http.get.side_effect = [label_resp, search_resp]
                mock_http.post.return_value = comment_resp

                gitlab_create_issues("qa", self._failure_details())

                comment_call = mock_http.post.call_args_list[-1]
                assert "/notes" in comment_call.args[0]
                assert "Still failing" in comment_call.kwargs["json"]["body"]


# ---------------------------------------------------------------------------
# github issues
# ---------------------------------------------------------------------------

class TestGithubIssues:
    def _failure_details(self):
        return {
            "test_basic_workflow_completes": {
                "longrepr": "AssertionError: expected COMPLETED got PENDING",
                "context": {
                    "test_id": "smoke-abc123",
                    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                },
            },
        }

    def test_skips_when_no_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("github_issues.http_requests") as mock_http:
                github_create_issues("qa", self._failure_details())
                mock_http.get.assert_not_called()
                mock_http.post.assert_not_called()

    def test_creates_new_issue_when_none_exists(self):
        env = {
            "SMOKE_GITHUB_TOKEN": "ghp_test123",
            "SMOKE_GITHUB_REPO": "acme/smoke-tests",
            "SMOKE_GITHUB_URL": "https://api.github.com",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("github_issues.http_requests") as mock_http:
                # Label exists
                label_resp = MagicMock()
                label_resp.ok = True

                # Search returns no matches
                search_resp = MagicMock()
                search_resp.ok = True
                search_resp.json.return_value = {"items": []}

                # Issue creation succeeds
                create_resp = MagicMock()
                create_resp.ok = True
                create_resp.json.return_value = {"number": 7, "html_url": "https://github.com/acme/smoke-tests/issues/7"}

                mock_http.get.side_effect = [label_resp, search_resp]
                mock_http.post.return_value = create_resp

                github_create_issues("qa", self._failure_details())

                create_call = mock_http.post.call_args_list[-1]
                assert "issues" in create_call.args[0]
                assert create_call.kwargs["json"]["title"] == "Smoke test failure: test_basic_workflow_completes"
                assert "smoke-test-failure" in create_call.kwargs["json"]["labels"]

    def test_comments_on_existing_issue(self):
        env = {
            "SMOKE_GITHUB_TOKEN": "ghp_test123",
            "SMOKE_GITHUB_REPO": "acme/smoke-tests",
            "SMOKE_GITHUB_URL": "https://api.github.com",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("github_issues.http_requests") as mock_http:
                # Label exists
                label_resp = MagicMock()
                label_resp.ok = True

                # Search finds existing issue
                search_resp = MagicMock()
                search_resp.ok = True
                search_resp.json.return_value = {"items": [{
                    "number": 42,
                    "title": "Smoke test failure: test_basic_workflow_completes",
                }]}

                comment_resp = MagicMock()
                comment_resp.ok = True

                mock_http.get.side_effect = [label_resp, search_resp]
                mock_http.post.return_value = comment_resp

                github_create_issues("qa", self._failure_details())

                comment_call = mock_http.post.call_args_list[-1]
                assert "/comments" in comment_call.args[0]
                assert "Still failing" in comment_call.kwargs["json"]["body"]


# ---------------------------------------------------------------------------
# clients (structure only, no network)
# ---------------------------------------------------------------------------

class TestClients:
    def test_api_client_strips_trailing_slash(self):
        client = APIClient("https://example.com/api/")
        assert client.base_url == "https://example.com/api"

    def test_workflow_trigger_stores_url(self):
        trigger = WorkflowTrigger("https://example.com/trigger")
        assert trigger.trigger_url == "https://example.com/trigger"
