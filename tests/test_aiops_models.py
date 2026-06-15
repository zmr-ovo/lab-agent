import pytest
from pydantic import ValidationError

from app.models.aiops import AIOpsRequest


def test_aiops_request_accepts_alertmanager_aliases():
    request = AIOpsRequest.model_validate(
        {
            "session_id": "incident-1",
            "alert": {
                "status": "firing",
                "labels": {"alertname": "HighCPU", "service": "video-gateway"},
                "annotations": {"description": "CPU is high"},
                "startsAt": "2026-06-15T01:00:00Z",
            },
            "lookback_minutes": 90,
        }
    )

    assert request.alert is not None
    assert request.alert.labels["service"] == "video-gateway"
    assert request.alert.starts_at is not None
    assert request.lookback_minutes == 90


def test_aiops_request_rejects_excessive_lookback():
    with pytest.raises(ValidationError):
        AIOpsRequest(lookback_minutes=1441)
