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
