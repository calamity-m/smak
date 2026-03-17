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
    """

    def __init__(self, trigger_url: str):
        self.trigger_url = trigger_url
        self.session = requests.Session()

    def start_process(self, payload: dict) -> dict:
        resp = self.session.post(self.trigger_url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
