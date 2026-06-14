"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

from pathlib import Path
from typing import Dict, Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录下的 .env（不依赖进程当前工作目录，避免 nohup / systemd 等 cwd 不对时读不到配置）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "SuperBizAgent"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900

    # DashScope 配置
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_model: str = "qwen-max"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）

    # Milvus 配置
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒

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

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }


# 全局配置实例
config = Settings()
