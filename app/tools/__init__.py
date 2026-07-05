"""工具模块 - 供 Agent 调用的各种工具"""

from __future__ import annotations

from typing import Any

from app.config import config
from app.tools.knowledge_tool import retrieve_knowledge
from app.tools.tavily_search_tool import tavily_web_search
from app.tools.time_tool import get_current_time


def with_optional_tavily(tools: list[Any]) -> list[Any]:
    """在已选本地工具列表末尾追加 Tavily（仅当配置了 TAVILY_API_KEY）。"""
    if (config.tavily_api_key or "").strip():
        return [*tools, tavily_web_search]
    return list(tools)


__all__ = [
    "retrieve_knowledge",
    "get_current_time",
    "tavily_web_search",
    "with_optional_tavily",
]
