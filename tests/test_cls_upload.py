import pytest

from scripts import upload_cls_test_logs
from scripts.upload_cls_test_logs import build_authorization, encode_log_group_list, healthy_logs


def test_encode_log_group_list_contains_structured_fields() -> None:
    payload = encode_log_group_list(
        [{"service": "lab-agent", "level": "ERROR", "status_code": 503}],
        source="local-test",
    )

    assert payload
    assert b"lab-agent" in payload
    assert b"ERROR" in payload
    assert b"local-test" in payload


def test_build_authorization_does_not_expose_secret_key() -> None:
    authorization = build_authorization(
        secret_id="AKIDexample",
        secret_key="secret-value",
        host="ap-guangzhou.cls.tencentcs.com",
        topic_id="topic-id",
        start_time=1_700_000_000,
    )

    assert "q-ak=AKIDexample" in authorization
    assert "q-url-param-list=topic_id" in authorization
    assert "secret-value" not in authorization


def test_validate_config_rejects_non_api_secret_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload_cls_test_logs.config, "tencentcloud_secret_id", "100000000001")
    monkeypatch.setattr(upload_cls_test_logs.config, "tencentcloud_secret_key", "x" * 32)
    monkeypatch.setattr(upload_cls_test_logs.config, "tencentcloud_region", "ap-guangzhou")
    monkeypatch.setattr(upload_cls_test_logs.config, "cls_topic_id", "topic-id")

    with pytest.raises(SystemExit, match="SecretId"):
        upload_cls_test_logs._validate_config()


def test_healthy_logs_do_not_contain_errors() -> None:
    logs = healthy_logs("lab-agent")

    assert logs
    assert {item["level"] for item in logs} == {"INFO"}
