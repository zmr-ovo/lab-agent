from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.api.aiops as aiops_api
import app.services.incident_service as incident_module
from app.api.aiops import _ensure_local_demo_request, _normalize_cls_alert


def test_normalize_cls_alert_accepts_simple_callback_payload() -> None:
    alert = _normalize_cls_alert(
        {
            "alarmName": "lab-agent-error-alert",
            "service": "lab-agent",
            "level": "critical",
            "message": "error_count >= 2",
        }
    )

    assert alert["status"] == "firing"
    assert alert["labels"]["alertname"] == "lab-agent-error-alert"
    assert alert["labels"]["service"] == "lab-agent"
    assert alert["annotations"]["description"] == "error_count >= 2"


@pytest.mark.asyncio
async def test_incident_service_persists_completed_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_diagnose(**kwargs):
        assert kwargs["alert_source"] == "local-mock-callback"
        yield {"type": "report", "report": "# 技术报告\n\n根因为上游连接超时。"}
        yield {
            "type": "complete",
            "diagnosis": {"status": "completed", "report": "# 技术报告\n\n已完成。"},
        }

    monkeypatch.setattr(incident_module.aiops_service, "diagnose", fake_diagnose)
    service = incident_module.IncidentService(str(tmp_path))
    incident = service.create(
        alert={"status": "firing", "labels": {"service": "lab-agent"}},
        source="local-mock-callback",
        is_mock_callback=True,
        lookback_minutes=15,
    )

    await service._run(incident["incident_id"])

    completed = service.get(incident["incident_id"])
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["report"].startswith("# 技术报告")
    report = tmp_path / f"{incident['incident_id']}.md"
    assert report.exists()
    assert "回调类型: `Mock`" in report.read_text(encoding="utf-8")


def test_demo_rejects_forwarded_public_request() -> None:
    request = Request(
        {
            "type": "http",
            "client": ("127.0.0.1", 12345),
            "headers": [(b"cf-connecting-ip", b"203.0.113.10")],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        _ensure_local_demo_request(request)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_start_demo_uploads_logs_and_starts_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeIncidentService:
        def has_active(self) -> bool:
            return False

        def create(self, **kwargs):
            assert kwargs["source"] == "web-ui-mock-callback"
            assert kwargs["is_mock_callback"] is True
            assert "status_code:503 OR status_code:504" in kwargs["alert"]["annotations"][
                "recommended_cls_query"
            ]
            return {"incident_id": "incident-demo", "status": "queued"}

        def start(self, incident_id: str) -> None:
            assert incident_id == "incident-demo"

    monkeypatch.setattr(aiops_api, "incident_service", FakeIncidentService())
    monkeypatch.setattr(aiops_api, "fault_logs", lambda service: [{"service": service}])
    monkeypatch.setattr(aiops_api, "upload_logs", lambda logs: len(list(logs)))
    request = Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": []})

    response = await aiops_api.start_aiops_demo(request)

    assert response["incident_id"] == "incident-demo"
    assert response["uploaded_log_count"] == 1
    assert response["log_source"] == "real-tencent-cls"
    assert response["callback_mode"] == "mock"
