"""Tavily 公网检索工具：仅请求官方 Search API，不抓取任意 URL。"""

from __future__ import annotations

from typing import Any

import httpx
from langchain_core.tools import tool
from loguru import logger

from app.config import config

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _truncate(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _format_results(data: dict[str, Any], max_results: int) -> str:
    lines: list[str] = []
    answer = data.get("answer")
    if isinstance(answer, str) and answer.strip():
        lines.append("【摘要】")
        lines.append(_truncate(answer, 1200))
        lines.append("")

    results = data.get("results") or []
    if not isinstance(results, list) or not results:
        if lines:
            return "\n".join(lines)
        return "未返回检索条目。"

    lines.append("【来源条目】")
    for i, item in enumerate(results[:max_results], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip() or "(无标题)"
        url = str(item.get("url") or "").strip()
        content = _truncate(str(item.get("content") or ""), 500)
        lines.append(f"{i}. {title}")
        if url:
            lines.append(f"   URL: {url}")
        if content:
            lines.append(f"   摘录: {content}")
        lines.append("")

    return "\n".join(lines).rstrip()


@tool
def tavily_web_search(query: str) -> str:
    """使用 Tavily 在公网上检索与问题相关的最新网页信息。

    使用时机：在已通过知识库检索仍无法得到足够依据、或用户明确要求
    时效新闻/外部资料时使用；回答中应区分「知识库内容」与「公网检索结果」。
    """
    q = (query or "").strip()
    if not q:
        return "搜索查询不能为空。"

    api_key = (config.tavily_api_key or "").strip()
    if not api_key:
        return "Tavily 未配置（缺少环境变量 TAVILY_API_KEY），无法进行联网搜索。"

    max_results = max(1, min(int(config.tavily_max_results), 10))
    timeout = float(config.tavily_timeout_seconds)

    payload: dict[str, Any] = {
        "api_key": api_key,
        "query": q,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": True,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(TAVILY_SEARCH_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"Tavily HTTP 错误: {e.response.status_code}")
        return f"联网搜索失败（HTTP {e.response.status_code}），请稍后重试。"
    except httpx.RequestError as e:
        logger.warning(f"Tavily 请求异常: {e}")
        return "联网搜索请求失败（网络或超时），请稍后重试。"
    except ValueError as e:
        logger.warning(f"Tavily 响应非 JSON: {e}")
        return "联网搜索返回格式异常，请稍后重试。"

    if not isinstance(data, dict):
        return "联网搜索返回格式异常。"

    if data.get("error"):
        err = str(data.get("error"))
        logger.warning(f"Tavily API 错误: {err}")
        return f"联网搜索失败: {err}"

    logger.info(f"Tavily 搜索完成: query_len={len(q)}, max_results={max_results}")
    return _format_results(data, max_results)
