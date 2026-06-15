# AIOps MCP Servers

Lab Agent 通过两个 MCP 服务接入腾讯云日志与监控数据：

- `cls_server.py`：腾讯云 CLS Topic 查询和 CQL 日志检索，端口 `8003`。
- `monitor_server.py`：腾讯云 TMP PromQL 查询与 Alertmanager 活跃告警，端口 `8004`。

HTTP 与 stdio 入口复用同一实现：

```bash
python -m mcp_servers.cls_server
python -m mcp_servers.monitor_server

python -m mcp_servers.cls_stdio
python -m mcp_servers.monitor_stdio
```

## 数据模式

`AIOPS_DATA_MODE=mock` 为默认演示模式。所有返回值都带有：

```json
{
  "mode": "mock",
  "is_mock": true,
  "warning": "Mock 演示数据，不代表真实生产环境。"
}
```

设置 `AIOPS_DATA_MODE=real` 后只查询真实数据。配置缺失或云接口失败会返回明确错误，不会静默降级为 Mock。

## CLS 工具

- `get_cls_status`
- `list_log_topics`
- `query_cls_logs`：通用 Topic + CQL 查询
- `search_service_logs`：按资源映射查询服务日志

真实模式需要：

```dotenv
TENCENTCLOUD_SECRET_ID=...
TENCENTCLOUD_SECRET_KEY=...
TENCENTCLOUD_REGION=ap-guangzhou
```

## TMP 与告警工具

- `get_monitor_status`
- `query_prometheus`：通用即时 PromQL
- `query_prometheus_range`：通用区间 PromQL
- `query_service_metric`：使用资源映射查询常用指标
- `query_cpu_metrics` / `query_memory_metrics`：兼容工具
- `get_active_alerts`：拉取 Alertmanager firing 告警

真实模式需要：

```dotenv
PROMETHEUS_URL=https://your-tmp-prometheus-endpoint
PROMETHEUS_USERNAME=...
PROMETHEUS_PASSWORD=...
ALERTMANAGER_URL=https://your-alertmanager-endpoint
```

服务到 CLS Topic、CQL 和 PromQL 的映射位于根目录 `aiops-resources.yml`。
