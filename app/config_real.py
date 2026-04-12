"""真实环境 MCP / 腾讯云 / Prometheus 扩展配置（独立文件，不替换 app.config）。

用法：
1. 复制 `.env.real.example` 为 `.env.real`，填入密钥与地址。
2. 在需要走本配置的代码里改为：
     from app.config_real import config_real as config
   或仅取 MCP：
     from app.config_real import config_real
     servers = config_real.mcp_servers

环境文件加载顺序：先 `.env`，再 `.env.real`（后者覆盖同名键）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

from app.config import Settings


def _comma_split_args(value: str) -> List[str]:
    if not value or not value.strip():
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


class RealSettings(Settings):
    """在默认 Settings 上增加真实 CLS / TMP 等字段，并生成完整 MCP connections。"""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.real"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 腾讯云 CLS（日志上传或真 CLS MCP 进程可读） ----------
    tencentcloud_secret_id: str = ""
    tencentcloud_secret_key: str = ""
    tencentcloud_region: str = "ap-guangzhou"
    tencentcloud_api_base_host: str = "tencentcloudapi.com"
    cls_topic_id: str = ""
    cls_max_length: int = 15000

    # ---------- Prometheus / TMP（监控 MCP 子进程可读） ----------
    prometheus_url: str = ""
    prometheus_username: str = ""
    prometheus_password: str = ""

    # ---------- stdio 子进程启动（仅当 transport=stdio 时使用） ----------
    mcp_cls_stdio_command: str = "python3"
    mcp_cls_stdio_args: str = "-m,mcp_servers.cls_stdio"
    mcp_monitor_stdio_command: str = "python3"
    mcp_monitor_stdio_args: str = "-m,mcp_servers.monitor_stdio"

    @field_validator("mcp_cls_stdio_args", "mcp_monitor_stdio_args", mode="before")
    @classmethod
    def _strip_stdio_args(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    def _cls_subprocess_env(self) -> Dict[str, str] | None:
        extra: Dict[str, str] = {}
        if self.tencentcloud_secret_id:
            extra["TENCENTCLOUD_SECRET_ID"] = self.tencentcloud_secret_id
        if self.tencentcloud_secret_key:
            extra["TENCENTCLOUD_SECRET_KEY"] = self.tencentcloud_secret_key
        if self.tencentcloud_region:
            extra["TENCENTCLOUD_REGION"] = self.tencentcloud_region
        if self.tencentcloud_api_base_host:
            extra["TENCENTCLOUD_API_BASE_HOST"] = self.tencentcloud_api_base_host
        if self.cls_topic_id:
            extra["CLS_TOPIC_ID"] = self.cls_topic_id
        extra["CLS_MAX_LENGTH"] = str(self.cls_max_length)
        if not extra:
            return None
        merged = dict(os.environ)
        merged.update(extra)
        return merged

    def _monitor_subprocess_env(self) -> Dict[str, str] | None:
        extra: Dict[str, str] = {}
        if self.prometheus_url:
            extra["PROMETHEUS_URL"] = self.prometheus_url
        if self.prometheus_username:
            extra["PROMETHEUS_USERNAME"] = self.prometheus_username
        if self.prometheus_password:
            extra["PROMETHEUS_PASSWORD"] = self.prometheus_password
        if not extra:
            return None
        merged = dict(os.environ)
        merged.update(extra)
        return merged

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        """与 langchain_mcp_adapters 对齐：stdio 需 command + args；HTTP 类需 url。"""
        t_cls = (self.mcp_cls_transport or "").lower().replace("_", "-")
        t_mon = (self.mcp_monitor_transport or "").lower().replace("_", "-")

        cls: Dict[str, Any]
        if t_cls == "stdio":
            cls = {
                "transport": "stdio",
                "command": self.mcp_cls_stdio_command,
                "args": _comma_split_args(self.mcp_cls_stdio_args),
            }
            env = self._cls_subprocess_env()
            if env is not None:
                cls["env"] = env
        else:
            cls = {"transport": self.mcp_cls_transport, "url": self.mcp_cls_url}

        monitor: Dict[str, Any]
        if t_mon == "stdio":
            monitor = {
                "transport": "stdio",
                "command": self.mcp_monitor_stdio_command,
                "args": _comma_split_args(self.mcp_monitor_stdio_args),
            }
            env = self._monitor_subprocess_env()
            if env is not None:
                monitor["env"] = env
        else:
            monitor = {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }

        return {"cls": cls, "monitor": monitor}


config_real = RealSettings()
