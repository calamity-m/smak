# smak — workflow smoke tests

Smoke test harness, designed to run in GitLab CI or GitHub Actions on a schedule.

Triggers workflows, polls for results, asserts on outcomes, and notifies on failure (Mattermost + auto-created GitLab/GitHub issues).

## Quick start

```bash
uv sync
uv run pytest tests/test_harness.py   # validate the harness itself (no external deps)
uv run pytest -n auto                 # run smoke tests in parallel (needs real endpoints)
```

## Project structure

```
├── .gitlab-ci.yml                    # GitLab CI pipeline
├── .github/workflows/smoke-test.yml  # GitHub Actions workflow
├── config.py                         # env-aware config
├── clients.py                        # API client + workflow trigger
├── polling.py                        # tenacity-based poll helpers
├── test_data.py                      # payload factory with unique test IDs
├── notifier.py                       # Mattermost message builder
├── issue_body.py                     # shared issue/comment body builder
├── gitlab_issues.py                  # auto-create GitLab issues on failure
├── github_issues.py                  # auto-create GitHub issues on failure
├── conftest.py                       # pytest fixtures, Rich output, notification hook
└── tests/
    ├── test_harness.py               # tests for the harness itself (offline, mocked)
    ├── test_happy_path.py            # template — copy for new smoke tests
    └── test_multi_step.py            # multi-stage workflow example
```

## Configuration

All config is via environment variables. Set them in your CI provider's variables/secrets, or export locally.

### Required

| Variable | Description |
|---|---|
| `SMOKE_API_BASE_URL` | Base URL of your microservice API (e.g. `https://your-service.qa.internal/api`) |
| `SMOKE_WORKFLOW_TRIGGER_URL` | URL to trigger workflow runs |

### Optional — general

| Variable | Default | Description |
|---|---|---|
| `SMOKE_ENV` | `qa` | Environment name (`qa`, `staging`). Controls default URLs and shows in notifications |
| `SMOKE_POLL_INTERVAL` | `5` | Seconds between poll attempts |
| `SMOKE_POLL_TIMEOUT` | `300` | Max seconds to wait for a workflow to complete |

### Optional — Mattermost notifications

| Variable | Default | Description |
|---|---|---|
| `SMOKE_MATTERMOST_WEBHOOK` | _(empty — disabled)_ | Incoming webhook URL. If set, sends pass/fail notifications |
| `SMOKE_NOTIFY_ON_SUCCESS` | `false` | Set to `true` to also notify on success (failures always notify) |

### Optional — GitLab issue creation

When configured, automatically creates a GitLab issue for each failing test. If an open issue already exists for that test, it adds a comment instead. Skipped entirely if the token is not set.

| Variable | Default | Description |
|---|---|---|
| `SMOKE_GITLAB_TOKEN` | _(empty — disabled)_ | Project or personal access token with `api` scope |
| `SMOKE_GITLAB_PROJECT_ID` | _(empty — disabled)_ | Numeric project ID (Settings > General) |
| `SMOKE_GITLAB_URL` | `https://gitlab.com` | Your GitLab instance URL (for self-hosted) |

### Optional — GitHub issue creation

Same behaviour as GitLab issues, but for GitHub repos. Skipped entirely if the token is not set. Both can be enabled simultaneously.

| Variable | Default | Description |
|---|---|---|
| `SMOKE_GITHUB_TOKEN` | _(empty — disabled)_ | Personal access token or GitHub App token with `issues: write` |
| `SMOKE_GITHUB_REPO` | _(empty — disabled)_ | `owner/repo` (e.g. `acme/smoke-tests`) |
| `SMOKE_GITHUB_URL` | `https://api.github.com` | API base URL (for GitHub Enterprise Server) |

### CI-provided (automatic)

These are set automatically by GitLab CI / GitHub Actions and used to link issues back to the pipeline:

| Variable | Set by | Used for |
|---|---|---|
| `CI_PIPELINE_URL` | GitLab CI | Linked in issue body and comments |
| `CI_JOB_URL` | GitLab CI | Linked in issue body |

## CI setup

### GitLab CI

Add a pipeline schedule at **Settings > CI/CD > Pipeline schedules**:

- **Recommended:** `0 7 * * 1-5` (7am weekdays, before standup)
- Set `CRITICAL_ONLY=true` on a tighter schedule to run only `@pytest.mark.critical` tests
- Set variables in **Settings > CI/CD > Variables**

### GitHub Actions

The workflow runs on schedule, push to main, and manual dispatch:

- **Schedule:** `0 7 * * 1-5` (7am UTC weekdays) — edit in `.github/workflows/smoke-test.yml`
- Set variables in **Settings > Secrets and variables > Actions**
- Secrets: `SMOKE_MATTERMOST_WEBHOOK`, `SMOKE_GITHUB_TOKEN`
- Variables: `SMOKE_API_BASE_URL`, `SMOKE_WORKFLOW_TRIGGER_URL`, `SMOKE_ENV`, `SMOKE_GITHUB_REPO`

## Writing tests

Copy `tests/test_happy_path.py` as a template. Each test gets fixtures injected automatically:

- `api` — HTTP client for your microservice
- `trigger` — workflow trigger client
- `poll_config` — `{"timeout": ..., "interval": ...}` from config
- `test_context` — dict to stash triage IDs (shows up in notifications and issues on failure)

```python
@pytest.mark.critical
def test_my_workflow(api, trigger, poll_config, test_context):
    payload = make_payload({"order_type": "standard"})
    test_context["test_id"] = payload["test_id"]
    test_context["correlation_id"] = payload["correlation_id"]

    result = trigger.start_process(payload)
    test_context["request_id"] = result.get("request_id")

    data = poll_for_status(
        api=api,
        path=f"/entities/{payload['test_id']}",
        expected_status="COMPLETED",
        **poll_config,
    )

    assert data is not None
```
