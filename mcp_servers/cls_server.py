"""Tencent Cloud CLS MCP server with explicit real/mock modes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import httpx
from fastmcp import FastMCP

from app.config import config
from mcp_servers.aiops_common import parse_time, resolve_service, result

logger = logging.getLogger("CLS_MCP_Server")
mcp = FastMCP("CLS")
_UTC = timezone.utc  # noqa: UP017 - compatible with editors still using Python 3.10 stubs
_STATUS_CODE_PATTERN = re.compile(r"(?<!\d)[1-5]\d{2}(?!\d)")


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _cls_endpoint() -> str:
    host = str(config.tencentcloud_api_base_host).strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    if not host.startswith("cls."):
        host = f"cls.{host}"
    return f"https://{host}"


async def _call_cls(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not config.tencentcloud_secret_id or not config.tencentcloud_secret_key:
        raise RuntimeError("TENCENTCLOUD_SECRET_ID/SECRET_KEY 未配置")

    service = "cls"
    host = _cls_endpoint().split("://", 1)[1]
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, tz=_UTC).strftime("%Y-%m-%d")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            "",
            canonical_headers,
            signed_headers,
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
        ]
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _sign(("TC3" + config.tencentcloud_secret_key).encode("utf-8"), date)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={config.tencentcloud_secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": "2020-10-16",
        "X-TC-Region": config.tencentcloud_region,
    }
    async with httpx.AsyncClient(
        timeout=config.aiops_http_timeout_seconds,
        verify=config.aiops_verify_tls,
    ) as client:
        response = await client.post(_cls_endpoint(), headers=headers, content=body)
        response.raise_for_status()
        response_payload = cast(dict[str, Any], response.json())
        data = cast(dict[str, Any], response_payload.get("Response", {}))
    if data.get("Error"):
        error = data["Error"]
        raise RuntimeError(f"{error.get('Code')}: {error.get('Message')}")
    return data


def _mock_topics() -> list[dict[str, Any]]:
    return [
        {
            "topic_id": "mock-video-gateway-topic",
            "topic_name": "video-gateway",
            "service_name": "video-gateway",
            "region": config.tencentcloud_region,
        },
        {
            "topic_id": "mock-media-relay-topic",
            "topic_name": "media-relay",
            "service_name": "media-relay",
            "region": config.tencentcloud_region,
        },
    ]


def _mock_logs(service_name: str, start: datetime, limit: int) -> list[dict[str, Any]]:
    service = resolve_service(service_name)["name"]
    samples = [
        ("INFO", "health check passed"),
        ("WARN", "upstream response latency increased to 1840ms"),
        ("ERROR", "upstream connection timeout after 3000ms"),
        ("ERROR", "request failed: no healthy upstream endpoints"),
    ]
    logs = []
    for index, (level, message) in enumerate(samples[:limit]):
        timestamp = start.timestamp() + index * 60
        logs.append(
            {
                "timestamp": datetime.fromtimestamp(timestamp, tz=_UTC).isoformat(),
                "level": level,
                "service": service,
                "message": message,
            }
        )
    return logs


async def list_log_topics_impl(name_keyword: str | None = None, limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    if config.aiops_data_mode == "mock":
        topics = _mock_topics()
        if name_keyword:
            keyword = name_keyword.lower()
            topics = [item for item in topics if keyword in item["topic_name"].lower()]
        return result("tencent-cloud-cls", topics[:limit], query={"name_keyword": name_keyword})
    try:
        payload: dict[str, Any] = {"Limit": limit, "Offset": 0}
        if name_keyword:
            payload["Filters"] = [{"Key": "topicName", "Values": [name_keyword]}]
        response = await _call_cls("DescribeTopics", payload)
        topics = [
            {
                "topic_id": item.get("TopicId"),
                "topic_name": item.get("TopicName"),
                "logset_id": item.get("LogsetId"),
                "status": item.get("Status"),
                "create_time": item.get("CreateTime"),
            }
            for item in response.get("Topics", [])
        ]
        return result("tencent-cloud-cls", topics, query=payload)
    except Exception as exc:
        logger.exception("CLS DescribeTopics failed")
        return result("tencent-cloud-cls", [], status="error", error=str(exc))


async def query_cls_logs_impl(
    service_name: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    query: str | None = None,
    topic_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    start = parse_time(start_time, default_minutes_ago=60)
    end = parse_time(end_time)
    if start >= end:
        return result("tencent-cloud-cls", [], status="error", error="start_time 必须早于 end_time")
    limit = max(1, min(limit, config.cls_max_results))
    service = resolve_service(service_name)
    resolved_topic = topic_id or service.get("cls_topic_id") or config.cls_topic_id
    resolved_query = query or service.get("cls_query") or "*"
    query_meta = {
        "service_name": service["name"],
        "topic_id": resolved_topic,
        "query": resolved_query,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "limit": limit,
    }
    if config.aiops_data_mode == "mock":
        return result(
            "tencent-cloud-cls",
            _mock_logs(service["name"], start, limit),
            query=query_meta,
        )
    if not resolved_topic:
        return result(
            "tencent-cloud-cls",
            [],
            status="error",
            error=f"服务 {service_name} 未配置 CLS topic_id",
            query=query_meta,
        )
    try:
        payload = {
            "TopicId": resolved_topic,
            "From": int(start.timestamp() * 1000),
            "To": int(end.timestamp() * 1000),
            "Query": resolved_query,
            "Limit": limit,
            "Sort": "desc",
        }
        response = await _call_cls("SearchLog", payload)
        raw_results = response.get("Results", [])
        logs = []
        for item in raw_results:
            raw = item.get("LogJson") or item.get("Log") or item
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    raw = {"message": raw}
            logs.append(raw)
        warning = None if raw_results else "CLS 查询未返回日志记录。"
        return result("tencent-cloud-cls", logs, warning=warning, query=query_meta)
    except Exception as exc:
        logger.exception("CLS SearchLog failed")
        return result("tencent-cloud-cls", [], status="error", error=str(exc), query=query_meta)


@mcp.tool()
async def get_cls_status() -> dict[str, Any]:
    """Return CLS mode and configuration readiness without exposing secrets."""
    ready = bool(config.tencentcloud_secret_id and config.tencentcloud_secret_key)
    return result(
        "tencent-cloud-cls",
        {"configured": ready, "region": config.tencentcloud_region},
        status="success" if config.aiops_data_mode == "mock" or ready else "unavailable",
    )


@mcp.tool()
async def list_log_topics(name_keyword: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List Tencent Cloud CLS topics, optionally filtered by topic name."""
    return await list_log_topics_impl(name_keyword, limit)


@mcp.tool()
async def query_cls_logs(
    service_name: str,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    query: str | None = None,
    topic_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query CLS logs with CQL using a service mapping or an explicit topic ID."""
    return await query_cls_logs_impl(service_name, start_time, end_time, query, topic_id, limit)


async def search_service_logs_impl(
    service_name: str,
    log_level: str | None = None,
    keyword: str | None = None,
    lookback_minutes: int = 60,
    limit: int = 100,
) -> dict[str, Any]:
    """Convenience CLS search for service logs, log level, and keyword."""
    clauses = []
    service = resolve_service(service_name)
    if service.get("cls_query"):
        clauses.append(str(service["cls_query"]))
    if log_level:
        clauses.append(f'level:"{log_level.upper()}"')
    if keyword:
        status_codes = list(dict.fromkeys(_STATUS_CODE_PATTERN.findall(keyword)))
        if status_codes:
            status_query = " OR ".join(f"status_code:{code}" for code in status_codes)
            clauses.append(f"({status_query})")
        else:
            escaped = keyword.replace('"', '\\"')
            clauses.append(f'"{escaped}"')
    query = " AND ".join(clauses) or "*"
    end = datetime.now(_UTC)
    start = end - timedelta(minutes=max(1, min(lookback_minutes, 1440)))
    return await query_cls_logs_impl(
        service_name,
        start_time=start.isoformat(),
        end_time=end.isoformat(),
        query=query,
        limit=limit,
    )


@mcp.tool()
async def search_service_logs(
    service_name: str,
    log_level: str | None = None,
    keyword: str | None = None,
    lookback_minutes: int = 60,
    limit: int = 100,
) -> dict[str, Any]:
    """Convenience CLS search for service logs, log level, and keyword."""
    return await search_service_logs_impl(
        service_name,
        log_level=log_level,
        keyword=keyword,
        lookback_minutes=lookback_minutes,
        limit=limit,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8003, path="/mcp")
