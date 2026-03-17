"""
Multi-step workflow test.

For workflows that go through multiple stages, you can
poll for each stage sequentially, or just poll for the final state.
"""

import pytest

from polling import poll_for_status
from test_data import make_payload


@pytest.mark.slow
def test_multi_step_workflow(api, trigger, poll_config):
    """
    Workflow goes PENDING -> PROCESSING -> COMPLETED.
    Verify it reaches COMPLETED without getting stuck.
    """
    payload = make_payload(
        {
            # "workflow_type": "multi_step",
        }
    )
    test_id = payload["test_id"]

    trigger.start_process(payload)

    # Optionally verify intermediate states:
    # poll_for_status(
    #     api=api,
    #     path=f"/entities/{test_id}",
    #     expected_status="PROCESSING",
    #     timeout=60,
    #     interval=poll_config["interval"],
    # )

    data = poll_for_status(
        api=api,
        path=f"/entities/{test_id}",
        expected_status="COMPLETED",
        **poll_config,
    )

    assert data is not None


@pytest.mark.slow
def test_large_batch_workflow(api, trigger, poll_config):
    """Trigger a workflow with a larger dataset — give it more time."""
    payload = make_payload(
        {
            # "batch_size": 100,
        }
    )
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
