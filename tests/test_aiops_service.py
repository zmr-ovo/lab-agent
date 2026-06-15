import pytest

import app.services.aiops_service as service_module


@pytest.mark.asyncio
async def test_api_alerts_take_priority(monkeypatch):
    captured = {}

    async def fake_execute(user_input, session_id, **kwargs):
        captured.update(kwargs)
        yield {"type": "complete", "response": "report", "is_mock": True}

    monkeypatch.setattr(service_module.aiops_service, "execute", fake_execute)
    alerts = [{"status": "firing", "labels": {"service": "video-gateway"}}]

    events = [
        event
        async for event in service_module.aiops_service.diagnose(
            session_id="test", alerts=alerts, lookback_minutes=30
        )
    ]

    assert captured["alerts"] == alerts
    assert captured["alert_source"] == "api"
    assert captured["lookback_minutes"] == 30
    assert events[-1]["diagnosis"]["report"] == "report"


@pytest.mark.asyncio
async def test_no_alerts_returns_report_without_running_graph(monkeypatch):
    async def fake_alerts():
        return {"status": "success", "data": [], "is_mock": False}

    async def fail_execute(*args, **kwargs):
        raise AssertionError("graph should not run without alerts")
        yield

    monkeypatch.setattr(service_module, "get_active_alerts_impl", fake_alerts)
    monkeypatch.setattr(service_module.aiops_service, "execute", fail_execute)

    events = [
        event async for event in service_module.aiops_service.diagnose(session_id="test", alerts=[])
    ]

    assert [event["type"] for event in events] == ["status", "report", "complete"]
    assert events[-1]["diagnosis"]["status"] == "no_active_alerts"
