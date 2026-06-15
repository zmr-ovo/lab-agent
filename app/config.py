"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录下的 .env（不依赖进程当前工作目录，避免 nohup / systemd 等 cwd 不对时读不到配置）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILES = (_PROJECT_ROOT / ".env", _PROJECT_ROOT / ".env.real")


def _comma_split_args(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=tuple(str(path) for path in _ENV_FILES),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "Lab Agent"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug_mode(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"dev", "development"}:
                return True
        return value

    # DashScope 配置
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_model: str = "qwen-max"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）

    # Milvus 配置
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒
    milvus_metric_type: str = "COSINE"
    """向量相似度度量：COSINE（余弦）/ L2（欧氏）/ IP（内积）。
    修改后，已存在 collection 的索引会在下次启动时自动按新 metric 重建（无需重新灌库）。"""

    # RAG 配置
    rag_top_k: int = 3
    """向量检索后最终交给模型的 chunk 条数。"""
    rag_fetch_k: int = 20
    """宽召回条数（应 ≥ rag_top_k）；仅在启用 FlashRank 时作为 Milvus 检索 k。"""
    rag_rerank_enabled: bool = True
    """是否用 FlashRank 对宽召回结果重排后截断为 rag_top_k。"""
    rag_flashrank_max_length: int = 512
    """FlashRank cross-encoder 输入长度上限（token 级预算，需覆盖 query+单段 passage）。"""
    rag_model: str = "qwen-max"  # 使用快速响应模型，不带扩展思考

    # Tavily 联网搜索（可选；未配置 API Key 时不注册该工具）
    tavily_api_key: str = ""
    tavily_max_results: int = 5
    tavily_timeout_seconds: float = 25.0

    @model_validator(mode="after")
    def _normalize_rag_fetch_k(self) -> "Settings":
        if self.rag_fetch_k < self.rag_top_k:
            self.rag_fetch_k = self.rag_top_k
        return self

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # MCP 服务配置
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    # AIOps 数据源。mock 用于演示；real 只返回真实数据或明确错误。
    aiops_data_mode: Literal["mock", "real"] = "mock"
    aiops_resource_config: str = str(_PROJECT_ROOT / "aiops-resources.yml")
    aiops_http_timeout_seconds: float = 20.0
    aiops_verify_tls: bool = True
    aiops_webhook_token: str = ""
    aiops_report_dir: str = str(_PROJECT_ROOT / "runtime" / "aiops_reports")

    # 腾讯云 CLS
    tencentcloud_secret_id: str = ""
    tencentcloud_secret_key: str = ""
    tencentcloud_region: str = "ap-guangzhou"
    tencentcloud_api_base_host: str = "tencentcloudapi.com"
    cls_topic_id: str = ""
    cls_max_results: int = 100

    # 腾讯云 TMP / 标准 Prometheus 与 Alertmanager
    prometheus_url: str = ""
    prometheus_username: str = ""
    prometheus_password: str = ""
    alertmanager_url: str = ""
    alertmanager_username: str = ""
    alertmanager_password: str = ""

    # stdio MCP 启动配置
    mcp_cls_stdio_command: str = "python3"
    mcp_cls_stdio_args: str = "-m,mcp_servers.cls_stdio"
    mcp_monitor_stdio_command: str = "python3"
    mcp_monitor_stdio_args: str = "-m,mcp_servers.monitor_stdio"

    @field_validator("mcp_cls_transport", "mcp_monitor_transport", mode="before")
    @classmethod
    def _normalize_transport(cls, value: Any) -> Any:
        return value.lower().replace("_", "-") if isinstance(value, str) else value

    @property
    def mcp_servers(self) -> dict[str, dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        cls_server = self._mcp_server_config(
            self.mcp_cls_transport,
            self.mcp_cls_url,
            self.mcp_cls_stdio_command,
            self.mcp_cls_stdio_args,
        )
        monitor_server = self._mcp_server_config(
            self.mcp_monitor_transport,
            self.mcp_monitor_url,
            self.mcp_monitor_stdio_command,
            self.mcp_monitor_stdio_args,
        )
        return {"cls": cls_server, "monitor": monitor_server}

    @staticmethod
    def _mcp_server_config(transport: str, url: str, command: str, args: str) -> dict[str, Any]:
        if transport == "stdio":
            return {
                "transport": "stdio",
                "command": command,
                "args": _comma_split_args(args),
                "env": dict(os.environ),
            }
        return {"transport": transport, "url": url}


# 全局配置实例
config = Settings()
