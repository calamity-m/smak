"""
Happy path smoke test — copy this file as a template for new tests.

Run all tests in parallel:    pytest -n auto
Run just critical ones:       pytest -m critical
Run a single test:            pytest tests/test_happy_path.py::test_basic_workflow_completes
"""
import pytest

from test_data import make_payload
from polling import poll_for_status, PollTimeout


@pytest.mark.critical
def test_basic_workflow_completes(api, trigger, poll_config, test_context):
    """
    Trigger a workflow, wait for it to complete,
    verify the result landed via your microservice API.
    """
    # 1. Build test input
    payload = make_payload({
        # Your workflow-specific fields here:
        # "customer_id": make_uuid(),
        # "order_type": "standard",
        # "amount": 100.00,
    })
    test_id = payload["test_id"]
    test_context["test_id"] = test_id
    test_context["correlation_id"] = payload["correlation_id"]

    # 2. Trigger the workflow
    result = trigger.start_process(payload)
    # Grab whatever ID the trigger returns for lookup:
    # entity_id = result["id"]
    entity_id = test_id  # adjust to match your actual lookup
    test_context["entity_id"] = entity_id

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
def test_workflow_produces_correct_output(api, trigger, poll_config, test_context):
    """Verify the workflow produces the right output data."""
    payload = make_payload({
        # "input_value": 42,
    })
    test_id = payload["test_id"]
    test_context["test_id"] = test_id
    test_context["correlation_id"] = payload["correlation_id"]

    trigger.start_process(payload)

    data = poll_for_status(
        api=api,
        path=f"/entities/{test_id}",
        expected_status="COMPLETED",
        **poll_config,
    )

    assert data is not None
    # assert data["computed_result"] == 84


def test_workflow_handles_invalid_input(api, trigger, poll_config, test_context):
    """Verify the workflow handles bad input gracefully."""
    payload = make_payload({
        # "amount": -1,  # invalid
    })
    test_id = payload["test_id"]
    test_context["test_id"] = test_id
    test_context["correlation_id"] = payload["correlation_id"]

    trigger.start_process(payload)

    data = poll_for_status(
        api=api,
        path=f"/entities/{test_id}",
        expected_status="REJECTED",
        **poll_config,
    )

    assert data is not None
    # assert "error" in data or data.get("rejection_reason") is not None
