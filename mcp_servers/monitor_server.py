"""Tencent Cloud TMP/Prometheus MCP server with Alertmanager support."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import httpx
from fastmcp import FastMCP

from app.config import config
from mcp_servers.aiops_common import parse_time, render_metric_query, resolve_service, result

logger = logging.getLogger("Monitor_MCP_Server")
mcp = FastMCP("Monitor")
_UTC = timezone.utc  # noqa: UP017 - compatible with editors still using Python 3.10 stubs


def _auth(username: str, password: str) -> httpx.BasicAuth | None:
    return httpx.BasicAuth(username, password) if username else None


async def _prometheus_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    if not config.prometheus_url:
        raise RuntimeError("PROMETHEUS_URL 未配置")
    url = f"{config.prometheus_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(
        timeout=config.aiops_http_timeout_seconds,
        verify=config.aiops_verify_tls,
        auth=_auth(config.prometheus_username, config.prometheus_password),
    ) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = cast(dict[str, Any], response.json())
    if payload.get("status") != "success":
        raise RuntimeError(payload.get("error") or "Prometheus query failed")
    return payload


def _mock_metric(service_name: str, metric: str, start: datetime, step: int) -> dict[str, Any]:
    profiles = {
        "cpu": [34.0, 42.0, 68.0, 91.0, 94.0, 88.0],
        "memory": [48.0, 50.0, 53.0, 55.0, 56.0, 57.0],
        "availability": [1.0, 1.0, 1.0, 0.0, 0.0, 1.0],
        "error_rate": [0.002, 0.004, 0.012, 0.19, 0.27, 0.08],
        "latency_p95": [0.18, 0.21, 0.42, 1.8, 2.4, 0.76],
    }
    values = profiles.get(metric, profiles["cpu"])
    points = [
        [int((start + timedelta(seconds=index * step)).timestamp()), str(value)]
        for index, value in enumerate(values)
    ]
    return {
        "resultType": "matrix",
        "result": [
            {
                "metric": {"service": resolve_service(service_name)["name"], "mock": "true"},
                "values": points,
            }
        ],
    }


async def query_prometheus_impl(query: str, time_value: str | None = None) -> dict[str, Any]:
    query_meta = {"query": query, "time": time_value}
    if config.aiops_data_mode == "mock":
        normalized = query.lower()
        if "5.." in normalized or "error" in normalized:
            value = "0.27"
        elif "cpu" in normalized:
            value = "94"
        elif "memory" in normalized:
            value = "57"
        elif "latency" in normalized or "duration" in normalized:
            value = "2.4"
        else:
            value = "1"
        data = {
            "resultType": "vector",
            "result": [
                {"metric": {"mock": "true"}, "value": [int(datetime.now().timestamp()), value]}
            ],
        }
        return result("tencent-cloud-tmp", data, query=query_meta)
    try:
        params = {"query": query}
        if time_value:
            params["time"] = time_value
        payload = await _prometheus_get("/api/v1/query", params)
        return result(
            "tencent-cloud-tmp",
            payload.get("data"),
            warning="; ".join(payload.get("warnings", [])) or None,
            query=query_meta,
        )
    except Exception as exc:
        logger.exception("Prometheus instant query failed")
        return result("tencent-cloud-tmp", None, status="error", error=str(exc), query=query_meta)


async def query_prometheus_range_impl(
    query: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    step_seconds: int = 60,
    mock_metric: str = "cpu",
    mock_service: str = "unknown",
) -> dict[str, Any]:
    start = parse_time(start_time, default_minutes_ago=60)
    end = parse_time(end_time)
    if start >= end:
        return result(
            "tencent-cloud-tmp", None, status="error", error="start_time 必须早于 end_time"
        )
    step_seconds = max(15, min(step_seconds, 3600))
    query_meta = {
        "query": query,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step_seconds": step_seconds,
    }
    if config.aiops_data_mode == "mock":
        return result(
            "tencent-cloud-tmp",
            _mock_metric(mock_service, mock_metric, start, step_seconds),
            query=query_meta,
        )
    try:
        payload = await _prometheus_get(
            "/api/v1/query_range",
            {
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step_seconds,
            },
        )
        return result(
            "tencent-cloud-tmp",
            payload.get("data"),
            warning="; ".join(payload.get("warnings", [])) or None,
            query=query_meta,
        )
    except Exception as exc:
        logger.exception("Prometheus range query failed")
        return result("tencent-cloud-tmp", None, status="error", error=str(exc), query=query_meta)


async def query_service_metric_impl(
    service_name: str,
    metric: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    step_seconds: int = 60,
) -> dict[str, Any]:
    try:
        query = render_metric_query(service_name, metric)
    except Exception as exc:
        return result("tencent-cloud-tmp", None, status="error", error=str(exc))
    return await query_prometheus_range_impl(
        query,
        start_time,
        end_time,
        step_seconds,
        mock_metric=metric,
        mock_service=service_name,
    )


def _mock_alerts() -> list[dict[str, Any]]:
    now = datetime.now(_UTC)
    return [
        {
            "status": "firing",
            "labels": {
                "alertname": "VideoGatewayHighErrorRate",
                "severity": "critical",
                "service": "video-gateway",
                "instance": "video-gateway-01",
            },
            "annotations": {
                "summary": "视频网关错误率持续升高",
                "description": "5xx 错误率超过 20%，请检查上游节点和连接超时。",
            },
            "startsAt": (now - timedelta(minutes=18)).isoformat(),
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "mock://prometheus/graph",
            "fingerprint": "mock-video-gateway-alert",
        }
    ]


async def get_active_alerts_impl() -> dict[str, Any]:
    if config.aiops_data_mode == "mock":
        return result("alertmanager", _mock_alerts(), query={"active": True})
    if not config.alertmanager_url:
        return result("alertmanager", [], status="unavailable", error="ALERTMANAGER_URL 未配置")
    try:
        url = f"{config.alertmanager_url.rstrip('/')}/api/v2/alerts"
        params = {"active": "true", "silenced": "false", "inhibited": "false"}
        async with httpx.AsyncClient(
            timeout=config.aiops_http_timeout_seconds,
            verify=config.aiops_verify_tls,
            auth=_auth(config.alertmanager_username, config.alertmanager_password),
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            alerts = response.json()
        return result("alertmanager", alerts, query=params)
    except Exception as exc:
        logger.exception("Alertmanager query failed")
        return result("alertmanager", [], status="error", error=str(exc))


@mcp.tool()
async def get_monitor_status() -> dict[str, Any]:
    """Return TMP and Alertmanager configuration readiness without exposing credentials."""
    return result(
        "tencent-cloud-tmp",
        {
            "prometheus_configured": bool(config.prometheus_url),
            "alertmanager_configured": bool(config.alertmanager_url),
        },
    )


@mcp.tool()
async def query_prometheus(query: str, time: str | None = None) -> dict[str, Any]:
    """Execute an arbitrary instant PromQL query against Tencent Cloud TMP."""
    return await query_prometheus_impl(query, time)


@mcp.tool()
async def query_prometheus_range(
    query: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    step_seconds: int = 60,
) -> dict[str, Any]:
    """Execute an arbitrary range PromQL query against Tencent Cloud TMP."""
    return await query_prometheus_range_impl(query, start_time, end_time, step_seconds)


@mcp.tool()
async def query_service_metric(
    service_name: str,
    metric: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    step_seconds: int = 60,
) -> dict[str, Any]:
    """Query a configured service metric: cpu, memory, availability, error_rate, or latency_p95."""
    return await query_service_metric_impl(service_name, metric, start_time, end_time, step_seconds)


@mcp.tool()
async def query_cpu_metrics(
    service_name: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    interval: str = "1m",
) -> dict[str, Any]:
    """Compatibility tool for service CPU metrics backed by TMP PromQL."""
    step = 60 if interval == "1m" else 300 if interval == "5m" else 3600
    return await query_service_metric_impl(service_name, "cpu", start_time, end_time, step)


@mcp.tool()
async def query_memory_metrics(
    service_name: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    interval: str = "1m",
) -> dict[str, Any]:
    """Compatibility tool for service memory metrics backed by TMP PromQL."""
    step = 60 if interval == "1m" else 300 if interval == "5m" else 3600
    return await query_service_metric_impl(service_name, "memory", start_time, end_time, step)


@mcp.tool()
async def get_active_alerts() -> dict[str, Any]:
    """Fetch currently active alerts from Alertmanager."""
    return await get_active_alerts_impl()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8004, path="/mcp")
