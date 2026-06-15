"""Background incident diagnosis and report persistence."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import config
from app.services.aiops_service import aiops_service

_UTC = timezone.utc  # noqa: UP017 - compatible with Python 3.10 editor stubs


class IncidentService:
    """Track webhook-triggered diagnoses and persist their reports."""

    def __init__(self, report_dir: str | None = None) -> None:
        self.report_dir = Path(report_dir or config.aiops_report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._incidents: dict[str, dict[str, Any]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._load_existing()

    def _load_existing(self) -> None:
        for path in sorted(self.report_dir.glob("*.json"), reverse=True):
            try:
                incident = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning(f"忽略无法读取的 AIOps 事件文件: {path}")
                continue
            incident_id = incident.get("incident_id")
            if incident_id:
                if incident.get("status") in {"queued", "running"}:
                    incident["status"] = "failed"
                    incident["error"] = "应用重启导致后台诊断中断，请重新发起演示"
                    incident["updated_at"] = self._now()
                    path.write_text(
                        json.dumps(incident, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                self._incidents[str(incident_id)] = incident

    @staticmethod
    def _now() -> str:
        return datetime.now(_UTC).isoformat()

    def create(
        self,
        *,
        alert: dict[str, Any],
        source: str,
        is_mock_callback: bool,
        lookback_minutes: int,
    ) -> dict[str, Any]:
        incident_id = f"incident-{datetime.now(_UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        incident = {
            "incident_id": incident_id,
            "status": "queued",
            "source": source,
            "is_mock_callback": is_mock_callback,
            "data_mode": config.aiops_data_mode,
            "lookback_minutes": lookback_minutes,
            "alert": alert,
            "events": [],
            "report": "",
            "error": None,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        self._incidents[incident_id] = incident
        self._persist(incident)
        return incident

    def start(self, incident_id: str) -> None:
        task = asyncio.create_task(self._run(incident_id), name=f"aiops:{incident_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, incident_id: str) -> None:
        incident = self._incidents[incident_id]
        incident["status"] = "running"
        incident["updated_at"] = self._now()
        self._persist(incident)
        try:
            async for event in aiops_service.diagnose(
                session_id=incident_id,
                alerts=[incident["alert"]],
                lookback_minutes=incident["lookback_minutes"],
                alert_source=incident["source"],
            ):
                incident["events"].append(event)
                if event.get("type") == "report":
                    incident["report"] = event.get("report", "")
                elif event.get("type") == "complete":
                    diagnosis = event.get("diagnosis") or {}
                    incident["report"] = diagnosis.get("report") or incident["report"]
                elif event.get("type") == "error":
                    incident["error"] = event.get("message", "诊断失败")
                incident["updated_at"] = self._now()
                self._persist(incident)

            incident["status"] = "failed" if incident["error"] else "completed"
        except Exception as exc:
            logger.exception(f"后台诊断失败: {incident_id}")
            incident["status"] = "failed"
            incident["error"] = str(exc)
        incident["updated_at"] = self._now()
        self._persist(incident)

    def _persist(self, incident: dict[str, Any]) -> None:
        incident_id = incident["incident_id"]
        json_path = self.report_dir / f"{incident_id}.json"
        json_path.write_text(
            json.dumps(incident, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        if incident.get("report"):
            report_header = (
                f"> 事件 ID: `{incident_id}`  \n"
                f"> 告警来源: `{incident['source']}`  \n"
                f"> 回调类型: `{'Mock' if incident['is_mock_callback'] else 'Real CLS'}`  \n"
                f"> 数据模式: `{incident['data_mode']}`\n\n"
            )
            (self.report_dir / f"{incident_id}.md").write_text(
                report_header + incident["report"], encoding="utf-8"
            )

    def get(self, incident_id: str) -> dict[str, Any] | None:
        return self._incidents.get(incident_id)

    def has_active(self) -> bool:
        return any(
            incident.get("status") in {"queued", "running"}
            for incident in self._incidents.values()
        )

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        incidents = sorted(
            self._incidents.values(), key=lambda item: item["created_at"], reverse=True
        )
        return [
            {
                key: item.get(key)
                for key in (
                    "incident_id",
                    "status",
                    "source",
                    "is_mock_callback",
                    "data_mode",
                    "created_at",
                    "updated_at",
                    "error",
                )
            }
            for item in incidents[:limit]
        ]


incident_service = IncidentService()
