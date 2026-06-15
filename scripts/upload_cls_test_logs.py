"""Upload structured AIOps test logs to Tencent Cloud CLS."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import socket
import time
import uuid
from collections.abc import Iterable, Mapping
from urllib.parse import quote

import httpx

from app.config import config


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field(field_number: int, wire_type: int) -> bytes:
    return _varint((field_number << 3) | wire_type)


def _bytes_field(field_number: int, value: bytes) -> bytes:
    return _field(field_number, 2) + _varint(len(value)) + value


def _text_field(field_number: int, value: str) -> bytes:
    return _bytes_field(field_number, value.encode("utf-8"))


def _encode_content(key: str, value: object) -> bytes:
    return _text_field(1, key) + _text_field(2, str(value))


def _encode_log(timestamp_ms: int, fields: Mapping[str, object]) -> bytes:
    payload = _field(1, 0) + _varint(timestamp_ms)
    for key, value in fields.items():
        payload += _bytes_field(2, _encode_content(key, value))
    return payload


def encode_log_group_list(
    logs: Iterable[Mapping[str, object]],
    *,
    source: str,
    filename: str = "lab-agent-local-test",
) -> bytes:
    now_ms = int(time.time() * 1000)
    group = b""
    for index, fields in enumerate(logs):
        group += _bytes_field(1, _encode_log(now_ms + index, fields))
    group += _text_field(3, filename)
    group += _text_field(4, source)
    return _bytes_field(1, group)


def build_authorization(
    *,
    secret_id: str,
    secret_key: str,
    host: str,
    topic_id: str,
    start_time: int | None = None,
    lifetime_seconds: int = 600,
) -> str:
    start = start_time or int(time.time())
    key_time = f"{start};{start + lifetime_seconds}"
    content_type = "application/x-protobuf"
    formatted_parameters = f"topic_id={quote(topic_id, safe='')}"
    formatted_headers = (
        f"content-type={quote(content_type, safe='')}&host={quote(host, safe='')}"
    )
    request_info = f"post\n/structuredlog\n{formatted_parameters}\n{formatted_headers}\n"
    string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(request_info.encode()).hexdigest()}\n"
    sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
    return (
        "q-sign-algorithm=sha1"
        f"&q-ak={secret_id}"
        f"&q-sign-time={key_time}"
        f"&q-key-time={key_time}"
        "&q-header-list=content-type;host"
        "&q-url-param-list=topic_id"
        f"&q-signature={signature}"
    )


def fault_logs(service: str) -> list[dict[str, object]]:
    trace_id = uuid.uuid4().hex
    common = {"service": service, "host": socket.gethostname(), "trace_id": trace_id}
    return [
        {
            **common,
            "level": "INFO",
            "message": "health check passed",
            "status_code": 200,
            "duration_ms": 28,
        },
        {
            **common,
            "level": "WARN",
            "message": "upstream response latency increased",
            "status_code": 200,
            "duration_ms": 1850,
        },
        {
            **common,
            "level": "ERROR",
            "message": "upstream connection timeout after 3000ms",
            "status_code": 504,
            "duration_ms": 3000,
        },
        {
            **common,
            "level": "ERROR",
            "message": "request failed: no healthy upstream endpoints",
            "status_code": 503,
            "duration_ms": 3012,
        },
    ]


# Backward-compatible alias for older local commands/tests.
_test_logs = fault_logs


def healthy_logs(service: str) -> list[dict[str, object]]:
    trace_id = uuid.uuid4().hex
    common = {"service": service, "host": socket.gethostname(), "trace_id": trace_id}
    return [
        {
            **common,
            "level": "INFO",
            "message": "health check passed",
            "status_code": 200,
            "duration_ms": 24,
        },
        {
            **common,
            "level": "INFO",
            "message": "request completed successfully",
            "status_code": 200,
            "duration_ms": 43,
        },
    ]


def upload_logs(logs: Iterable[Mapping[str, object]]) -> int:
    """Upload logs and return the accepted record count."""
    _validate_config()
    records = list(logs)
    body = encode_log_group_list(records, source=socket.gethostname())
    host = f"{config.tencentcloud_region}.cls.tencentcs.com"
    authorization = build_authorization(
        secret_id=config.tencentcloud_secret_id,
        secret_key=config.tencentcloud_secret_key,
        host=host,
        topic_id=config.cls_topic_id,
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/x-protobuf",
        "Host": host,
    }
    with httpx.Client(
        timeout=config.aiops_http_timeout_seconds,
        verify=config.aiops_verify_tls,
    ) as client:
        response = client.post(
            f"https://{host}/structuredlog",
            params={"topic_id": config.cls_topic_id},
            headers=headers,
            content=body,
        )
    if response.is_error:
        detail = response.text.strip() or response.reason_phrase
        raise RuntimeError(f"CLS 上传失败: HTTP {response.status_code} {detail}")
    return len(records)


def _validate_config() -> None:
    missing = [
        name
        for name, value in (
            ("TENCENTCLOUD_SECRET_ID", config.tencentcloud_secret_id),
            ("TENCENTCLOUD_SECRET_KEY", config.tencentcloud_secret_key),
            ("TENCENTCLOUD_REGION", config.tencentcloud_region),
            ("CLS_TOPIC_ID", config.cls_topic_id),
        )
        if not str(value).strip()
    ]
    if missing:
        raise SystemExit(f"缺少配置: {', '.join(missing)}")
    if not config.tencentcloud_secret_id.startswith("AKID"):
        raise SystemExit(
            "TENCENTCLOUD_SECRET_ID 格式不正确：请填写 CAM 子用户的 API SecretId，"
            "不要填写用户名、UIN 或日志主题 ID"
        )
    if len(config.tencentcloud_secret_key) < 32:
        raise SystemExit("TENCENTCLOUD_SECRET_KEY 格式不正确：密钥可能复制不完整")


def main() -> None:
    parser = argparse.ArgumentParser(description="上传一组 Lab Agent CLS 排障测试日志")
    parser.add_argument("--service", default="lab-agent", help="写入日志的 service 字段")
    parser.add_argument("--dry-run", action="store_true", help="仅检查并编码，不发送请求")
    args = parser.parse_args()

    _validate_config()
    logs = fault_logs(args.service)
    body = encode_log_group_list(logs, source=socket.gethostname())
    if args.dry_run:
        print(f"配置检查通过，已编码 {len(logs)} 条日志，共 {len(body)} 字节；未发送。")
        return

    try:
        count = upload_logs(logs)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"CLS 上传成功：{count} 条测试日志，service={args.service}")


if __name__ == "__main__":
    main()
