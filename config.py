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
