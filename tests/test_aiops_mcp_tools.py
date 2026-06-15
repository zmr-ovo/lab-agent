import pytest

from app.config import config
from mcp_servers import cls_server, monitor_server


@pytest.mark.asyncio
async def test_mock_tools_are_explicit_and_deterministic(monkeypatch):
    monkeypatch.setattr(config, "aiops_data_mode", "mock")

    logs_first = await cls_server.query_cls_logs_impl("video-gateway")
    logs_second = await cls_server.query_cls_logs_impl("video-gateway")
    alerts = await monitor_server.get_active_alerts_impl()
    metric = await monitor_server.query_service_metric_impl("video-gateway", "error_rate")

    assert logs_first["is_mock"] is True
    assert "Mock" in logs_first["warning"]
    assert [item["message"] for item in logs_first["data"]] == [
        item["message"] for item in logs_second["data"]
    ]
    assert alerts["data"][0]["labels"]["service"] == "video-gateway"
    assert metric["provider"] == "tencent-cloud-tmp"
    assert metric["data"]["resultType"] == "matrix"

    instant = await monitor_server.query_prometheus_impl(
        'sum(rate(http_requests_total{status=~"5.."}[5m]))'
    )
    assert instant["data"]["result"][0]["value"][1] == "0.27"


@pytest.mark.asyncio
async def test_real_cls_missing_topic_does_not_fallback_to_mock(monkeypatch):
    monkeypatch.setattr(config, "aiops_data_mode", "real")
    monkeypatch.setattr(config, "cls_topic_id", "")
    monkeypatch.setattr(cls_server, "resolve_service", lambda _: {"name": "unknown"})

    response = await cls_server.query_cls_logs_impl("unknown")

    assert response["status"] == "error"
    assert response["is_mock"] is False
    assert response["data"] == []
    assert "topic_id" in response["error"]


@pytest.mark.asyncio
async def test_real_cls_results_do_not_require_sql_analysis(monkeypatch):
    monkeypatch.setattr(config, "aiops_data_mode", "real")
    monkeypatch.setattr(config, "cls_topic_id", "topic-id")

    async def fake_call_cls(action, payload):
        assert action == "SearchLog"
        return {
            "Results": [
                {
                    "LogJson": (
                        '{"service":"lab-agent","level":"ERROR",'
                        '"status_code":"503"}'
                    )
                }
            ]
        }

    monkeypatch.setattr(cls_server, "_call_cls", fake_call_cls)
    response = await cls_server.query_cls_logs_impl("lab-agent")

    assert response["data"][0]["status_code"] == "503"
    assert "warning" not in response


@pytest.mark.asyncio
async def test_service_log_search_builds_status_code_or_query(monkeypatch):
    captured = {}

    async def fake_query(service_name, **kwargs):
        captured.update(kwargs)
        return {"status": "success", "data": []}

    monkeypatch.setattr(cls_server, "query_cls_logs_impl", fake_query)

    await cls_server.search_service_logs_impl(
        "lab-agent",
        log_level="ERROR",
        keyword="503 or 504",
        lookback_minutes=15,
    )

    assert captured["query"] == (
        'service:"lab-agent" AND level:"ERROR" AND '
        "(status_code:503 OR status_code:504)"
    )


@pytest.mark.asyncio
async def test_real_tmp_uses_query_range_and_returns_provider_data(monkeypatch):
    monkeypatch.setattr(config, "aiops_data_mode", "real")

    async def fake_get(path, params):
        assert path == "/api/v1/query_range"
        assert params["query"] == "up"
        return {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }

    monkeypatch.setattr(monitor_server, "_prometheus_get", fake_get)
    response = await monitor_server.query_prometheus_range_impl("up")

    assert response["status"] == "success"
    assert response["is_mock"] is False
    assert response["data"]["resultType"] == "matrix"


@pytest.mark.asyncio
async def test_real_alertmanager_missing_config_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "aiops_data_mode", "real")
    monkeypatch.setattr(config, "alertmanager_url", "")

    response = await monitor_server.get_active_alerts_impl()

    assert response["status"] == "unavailable"
    assert response["is_mock"] is False
    assert response["data"] == []
