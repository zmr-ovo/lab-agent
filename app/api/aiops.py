"""
AIOps 智能运维接口
"""

import json
import secrets
from asyncio import to_thread
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.config import config
from app.models.aiops import AIOpsRequest
from app.services.aiops_service import aiops_service
from app.services.incident_service import incident_service
from scripts.upload_cls_test_logs import fault_logs, upload_logs

router = APIRouter()
_UTC = timezone.utc  # noqa: UP017 - compatible with Python 3.10 editor stubs


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_cls_alert(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept Alertmanager-compatible or common CLS callback payloads."""
    raw_nested = payload.get("alert")
    raw_labels = payload.get("labels")
    raw_annotations = payload.get("annotations")
    nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
    label_values: dict[str, Any] = raw_labels if isinstance(raw_labels, dict) else {}
    annotation_values: dict[str, Any] = (
        raw_annotations if isinstance(raw_annotations, dict) else {}
    )
    combined = {**payload, **nested}
    labels = {str(key): str(value) for key, value in label_values.items()}
    annotations = {str(key): str(value) for key, value in annotation_values.items()}
    labels.setdefault(
        "alertname",
        _first_string(combined, "alertname", "alarmName", "alarm_name", "policyName", "name")
        or "CLSLogAlert",
    )
    labels.setdefault("service", _first_string(combined, "service", "service_name") or "lab-agent")
    labels.setdefault("severity", _first_string(combined, "severity", "level") or "warning")
    annotations.setdefault(
        "summary",
        _first_string(combined, "summary", "title", "subject") or "CLS 日志告警触发",
    )
    annotations.setdefault(
        "description",
        _first_string(combined, "description", "message", "content")
        or json.dumps(payload, ensure_ascii=False, default=str)[:2000],
    )
    return {
        "status": _first_string(combined, "status") or "firing",
        "labels": labels,
        "annotations": annotations,
        "startsAt": _first_string(combined, "startsAt", "startTime", "triggerTime"),
        "generatorURL": _first_string(combined, "generatorURL", "url", "consoleUrl"),
        "raw_cls_payload": payload,
    }


def _verify_webhook_token(token: str | None, authorization: str | None) -> None:
    expected = config.aiops_webhook_token.strip()
    if not expected:
        return
    supplied = token or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid webhook token")


def _ensure_local_demo_request(request: Request) -> None:
    forwarded_ip = request.headers.get("cf-connecting-ip") or request.headers.get(
        "x-forwarded-for"
    )
    if forwarded_ip:
        raise HTTPException(status_code=403, detail="AIOps demo can only be started locally")
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="AIOps demo can only be started locally")


@router.post("/aiops/demo", status_code=202)
async def start_aiops_demo(request: Request):
    """Upload a real CLS fault sample and start a clearly labeled Mock callback diagnosis."""
    _ensure_local_demo_request(request)
    if incident_service.has_active():
        raise HTTPException(status_code=409, detail="another AIOps diagnosis is still running")
    try:
        uploaded_count = await to_thread(upload_logs, fault_logs("lab-agent"))
    except (RuntimeError, SystemExit) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    alert = {
        "status": "firing",
        "labels": {
            "alertname": "LabAgentErrorAlert",
            "service": "lab-agent",
            "severity": "warning",
        },
        "annotations": {
            "summary": "CLS 检测到本地演示服务错误日志",
            "description": (
                "演示流程已写入真实 CLS 的 503/504 错误日志，并使用 Mock 回调启动自动排障。"
                "请优先使用 CLS 日志完成根因分析；未配置 TMP 时如实说明指标不可用。"
            ),
            "recommended_cls_query": (
                'service:"lab-agent" AND level:"ERROR" AND '
                "(status_code:503 OR status_code:504)"
            ),
        },
        "startsAt": datetime.now(_UTC).isoformat(),
    }
    incident = incident_service.create(
        alert=alert,
        source="web-ui-mock-callback",
        is_mock_callback=True,
        lookback_minutes=15,
    )
    incident_service.start(incident["incident_id"])
    return {
        "accepted": True,
        "incident_id": incident["incident_id"],
        "status": incident["status"],
        "uploaded_log_count": uploaded_count,
        "log_source": "real-tencent-cls",
        "callback_mode": "mock",
        "status_url": f"/api/aiops/incidents/{incident['incident_id']}",
        "report_url": f"/api/aiops/incidents/{incident['incident_id']}/report",
    }


@router.post("/aiops/webhook/cls", status_code=202)
async def cls_alert_webhook(
    request: Request,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    mock_callback: bool = Query(default=False),
    lookback_minutes: int = Query(default=15, ge=5, le=1440),
):
    """Receive a CLS callback and start diagnosis in the background."""
    _verify_webhook_token(token, authorization)
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="request body must be JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    alert = _normalize_cls_alert(payload)
    incident = incident_service.create(
        alert=alert,
        source="local-mock-callback" if mock_callback else "tencent-cls-webhook",
        is_mock_callback=mock_callback,
        lookback_minutes=lookback_minutes,
    )
    incident_service.start(incident["incident_id"])
    return {
        "accepted": True,
        "incident_id": incident["incident_id"],
        "status": incident["status"],
        "is_mock_callback": mock_callback,
        "status_url": f"/api/aiops/incidents/{incident['incident_id']}",
    }


@router.get("/aiops/incidents")
async def list_incidents(limit: int = Query(default=20, ge=1, le=100)):
    return {"incidents": incident_service.list(limit)}


@router.get("/aiops/incidents/{incident_id}")
async def get_incident(incident_id: str):
    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


@router.get("/aiops/incidents/{incident_id}/report", response_class=PlainTextResponse)
async def get_incident_report(incident_id: str):
    incident = incident_service.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    if not incident.get("report"):
        raise HTTPException(status_code=409, detail=f"incident status is {incident['status']}")
    return PlainTextResponse(incident["report"], media_type="text/markdown; charset=utf-8")


@router.post("/aiops")
async def diagnose_stream(request: AIOpsRequest):
    """
    AIOps 故障诊断接口（流式 SSE）

    **功能说明：**
    - 自动获取当前系统的活动告警
    - 使用 Plan-Execute-Replan 模式进行智能诊断
    - 流式返回诊断过程和结果

    **SSE 事件类型：**

    1. `status` - 状态更新
       ```json
       {
         "type": "status",
         "stage": "fetching_alerts",
         "message": "正在获取系统告警信息..."
       }
       ```

    2. `plan` - 诊断计划制定完成
       ```json
       {
         "type": "plan",
         "stage": "plan_created",
         "message": "诊断计划已制定，共 6 个步骤",
         "target_alert": {...},
         "plan": ["步骤1: ...", "步骤2: ..."]
       }
       ```

    3. `step_complete` - 步骤执行完成
       ```json
       {
         "type": "step_complete",
         "stage": "step_executed",
         "message": "步骤执行完成 (2/6)",
         "current_step": "查询系统日志",
         "result_preview": "...",
         "remaining_steps": 4
       }
       ```

    4. `report` - 最终诊断报告
       ```json
       {
         "type": "report",
         "stage": "final_report",
         "message": "最终诊断报告已生成",
         "report": "# 故障诊断报告\\n...",
         "evidence": {...}
       }
       ```

    5. `complete` - 诊断完成
       ```json
       {
         "type": "complete",
         "stage": "diagnosis_complete",
         "message": "诊断流程完成",
         "diagnosis": {...}
       }
       ```

    6. `error` - 错误信息
       ```json
       {
         "type": "error",
         "stage": "error",
         "message": "诊断过程发生错误: ..."
       }
       ```

    **使用示例：**
    ```bash
    curl -X POST "http://localhost:9900/api/aiops" \\
      -H "Content-Type: application/json" \\
      -d '{"session_id": "session-123"}' \\
      --no-buffer
    ```

    **前端使用示例：**
    ```javascript
    const eventSource = new EventSource('/api/aiops');

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'plan') {
        console.log('诊断计划:', data.plan);
      } else if (data.type === 'step_complete') {
        console.log('步骤完成:', data.current_step);
      } else if (data.type === 'report') {
        console.log('最终报告:', data.report);
      } else if (data.type === 'complete') {
        console.log('诊断完成');
        eventSource.close();
      }
    };
    ```

    Args:
        request: AIOps 诊断请求

    Returns:
        SSE 事件流
    """
    session_id = request.session_id or "default"
    logger.info(f"[会话 {session_id}] 收到 AIOps 诊断请求（流式）")

    async def event_generator():
        try:
            supplied_alerts = [
                alert.model_dump(by_alias=True, mode="json") for alert in request.alerts
            ]
            if request.alert is not None:
                supplied_alerts.insert(0, request.alert.model_dump(by_alias=True, mode="json"))
            async for event in aiops_service.diagnose(
                session_id=session_id,
                alerts=supplied_alerts,
                lookback_minutes=request.lookback_minutes,
            ):
                # 发送事件
                yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

                # 如果是完成或错误事件，结束流
                if event.get("type") in ["complete", "error"]:
                    break

            logger.info(f"[会话 {session_id}] AIOps 诊断流式响应完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] AIOps 诊断流式响应异常: {e}", exc_info=True)
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "error", "stage": "exception", "message": f"诊断异常: {str(e)}"},
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(event_generator())
