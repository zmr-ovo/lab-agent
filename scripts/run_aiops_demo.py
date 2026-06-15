"""Continuously upload CLS logs and optionally mock the cloud callback locally."""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import config
from scripts.upload_cls_test_logs import fault_logs, healthy_logs, upload_logs

_UTC = timezone.utc  # noqa: UP017 - compatible with Python 3.10 editor stubs


def _trigger_local_callback(base_url: str, service: str) -> str:
    payload: dict[str, Any] = {
        "status": "firing",
        "labels": {
            "alertname": "LabAgentErrorAlert",
            "service": service,
            "severity": "warning",
        },
        "annotations": {
            "summary": "CLS 检测到本地演示服务错误日志",
            "description": "最近 5 分钟 ERROR 日志数达到告警阈值，请执行自动排障。",
        },
        "startsAt": datetime.now(_UTC).isoformat(),
    }
    params: dict[str, str] = {"mock_callback": "true", "lookback_minutes": "15"}
    if config.aiops_webhook_token:
        params["token"] = config.aiops_webhook_token
    with httpx.Client(timeout=20) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/api/aiops/webhook/cls", params=params, json=payload
        )
        response.raise_for_status()
        result = response.json()
    return str(result["incident_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 CLS → 告警 → Agent 报告闭环演示")
    parser.add_argument("--service", default="lab-agent")
    parser.add_argument("--interval", type=float, default=10, help="每批日志之间的秒数")
    parser.add_argument("--healthy-batches", type=int, default=2, help="每轮故障前的正常批次数")
    parser.add_argument("--cycles", type=int, default=1, help="演示轮数；0 表示持续运行")
    parser.add_argument(
        "--callback-mode",
        choices=("local-mock", "cls"),
        default="local-mock",
        help="local-mock 直接模拟云回调；cls 等待真实 CLS 告警回调",
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:9900")
    args = parser.parse_args()

    cycle = 0
    print(
        f"AIOps 演示启动：service={args.service}, callback={args.callback_mode}, "
        f"interval={args.interval}s"
    )
    try:
        while args.cycles == 0 or cycle < args.cycles:
            cycle += 1
            for batch in range(args.healthy_batches):
                count = upload_logs(healthy_logs(args.service))
                print(f"[轮次 {cycle}] 正常日志批次 {batch + 1}: 已上传 {count} 条")
                time.sleep(max(0, args.interval))

            count = upload_logs(fault_logs(args.service))
            print(f"[轮次 {cycle}] 故障日志: 已上传 {count} 条，包含 2 条 ERROR")
            if args.callback_mode == "local-mock":
                incident_id = _trigger_local_callback(args.api_url, args.service)
                print(
                    f"[轮次 {cycle}] 已发送明确标识的 Mock 回调，incident_id={incident_id}\n"
                    f"查看状态: {args.api_url.rstrip('/')}/api/aiops/incidents/{incident_id}\n"
                    f"查看报告: {args.api_url.rstrip('/')}/api/aiops/incidents/{incident_id}/report"
                )
            else:
                print(f"[轮次 {cycle}] 等待 CLS 告警策略通过公网 Webhook 回调 Lab Agent")
            time.sleep(max(0, args.interval))
    except KeyboardInterrupt:
        print("\n演示已停止。")
    except (httpx.HTTPError, RuntimeError) as exc:
        raise SystemExit(f"演示失败: {exc}") from exc


if __name__ == "__main__":
    main()
