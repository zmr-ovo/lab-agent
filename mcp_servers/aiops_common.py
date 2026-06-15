"""Shared configuration and response helpers for AIOps MCP servers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template
from typing import Any

import yaml  # type: ignore[import-untyped]

from app.config import config

_UTC = timezone.utc  # noqa: UP017 - compatible with editors still using Python 3.10 stubs


def load_resource_config() -> dict[str, Any]:
    path = Path(config.aiops_resource_config)
    if not path.exists():
        return {"version": 1, "defaults": {}, "services": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"AIOps resource config must be a mapping: {path}")
    data.setdefault("defaults", {})
    data.setdefault("services", {})
    return data


def resolve_service(service_name: str) -> dict[str, Any]:
    resources = load_resource_config()
    services = resources.get("services", {})
    normalized = service_name.strip().lower()
    for canonical, raw in services.items():
        item = dict(raw or {})
        aliases = [str(value).lower() for value in item.get("aliases", [])]
        if normalized == canonical.lower() or normalized in aliases:
            return {"name": canonical, **item}
    return {"name": service_name}


def render_metric_query(service_name: str, metric: str) -> str:
    resources = load_resource_config()
    service = resolve_service(service_name)
    metrics = dict(resources.get("defaults", {}).get("metrics", {}))
    metrics.update(service.get("metrics", {}))
    template = metrics.get(metric)
    if not template:
        raise ValueError(f"No PromQL template configured for metric '{metric}'")
    return Template(str(template)).safe_substitute(service=service["name"])


def parse_time(value: str | int | float | None, default_minutes_ago: int = 0) -> datetime:
    if value is None:
        return datetime.now(_UTC) - timedelta(minutes=default_minutes_ago)
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=_UTC)
    text = value.strip()
    if text.isdigit():
        return parse_time(int(text), default_minutes_ago)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC)
    return parsed.astimezone(_UTC)


def result(
    provider: str,
    data: Any = None,
    *,
    status: str = "success",
    warning: str | None = None,
    error: str | None = None,
    query: Any = None,
) -> dict[str, Any]:
    is_mock = config.aiops_data_mode == "mock"
    payload: dict[str, Any] = {
        "status": status,
        "mode": config.aiops_data_mode,
        "is_mock": is_mock,
        "provider": provider,
        "data": data,
    }
    if query is not None:
        payload["query"] = query
    if is_mock:
        payload["warning"] = warning or "Mock 演示数据，不代表真实生产环境。"
    elif warning:
        payload["warning"] = warning
    if error:
        payload["error"] = error
    return payload
