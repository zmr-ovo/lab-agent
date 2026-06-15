import yaml  # type: ignore[import-untyped]

from app.config import config
from mcp_servers.aiops_common import parse_time, render_metric_query, resolve_service


def test_service_alias_and_promql_rendering(tmp_path, monkeypatch):
    resource_file = tmp_path / "resources.yml"
    resource_file.write_text(
        yaml.safe_dump(
            {
                "defaults": {"metrics": {"cpu": 'cpu{service="$service"}'}},
                "services": {
                    "video-gateway": {
                        "aliases": ["gateway"],
                        "cls_topic_id": "topic-123",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "aiops_resource_config", str(resource_file))

    service = resolve_service("gateway")

    assert service["name"] == "video-gateway"
    assert service["cls_topic_id"] == "topic-123"
    assert render_metric_query("gateway", "cpu") == 'cpu{service="video-gateway"}'


def test_parse_time_accepts_milliseconds_and_naive_iso():
    milliseconds = parse_time(1_700_000_000_000)
    naive = parse_time("2026-06-15T10:00:00")

    assert milliseconds.utcoffset() is not None
    assert milliseconds.utcoffset().total_seconds() == 0
    assert naive.utcoffset() is not None
    assert naive.utcoffset().total_seconds() == 0
