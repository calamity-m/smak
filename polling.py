"""
Polling helpers built on tenacity.
These are just thin wrappers so your tests read cleanly.
"""

from collections.abc import Callable
from typing import Any

from tenacity import (
    RetryError,
    retry,
    retry_if_result,
    stop_after_delay,
    wait_fixed,
)

from clients import APIClient


class PollTimeout(Exception):
    """Raised when we give up waiting for a result."""


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
    except RetryError as err:
        try:
            final = api.get(path).json()
            actual = final.get(status_field, "unknown")
        except Exception:
            actual = "unreachable"

        raise PollTimeout(
            f"Timed out after {timeout}s waiting for {status_field}='{expected_status}' "
            f"at {path} (last seen: '{actual}')"
        ) from err


def poll_until(
    fn: Callable[[], Any],
    timeout: int = 300,
    interval: int = 5,
    description: str = "condition",
) -> Any:
    """
    Generic poller. Call fn() repeatedly until it returns a truthy value.

    fn should return:
      - The result when condition is met
      - None/False when still waiting
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
    except RetryError as err:
        raise PollTimeout(f"Timed out after {timeout}s waiting for: {description}") from err
