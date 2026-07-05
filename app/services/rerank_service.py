"""FlashRank 本地重排：对向量宽召回结果做 cross-encoder 精排。"""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.documents import Document
from loguru import logger

from app.config import config


class FlashRankRanker(Protocol):
    def rerank(self, request: Any) -> list[dict[str, Any]]: ...


_ranker: FlashRankRanker | None = None


def _get_ranker() -> FlashRankRanker:
    global _ranker
    if _ranker is None:
        from flashrank import Ranker

        _ranker = Ranker(max_length=config.rag_flashrank_max_length)
        logger.info(
            f"FlashRank Ranker 已初始化 (max_length={config.rag_flashrank_max_length})"
        )
    return _ranker


def rerank_documents(query: str, documents: list[Document], top_n: int) -> list[Document]:
    """
    按 query 对文档列表重排，保留 top_n 条。

    失败时降级为「原顺序截断 top_n」，不抛异常。
    """
    if not documents or top_n <= 0:
        return []
    if len(documents) <= top_n:
        return list(documents)

    try:
        from flashrank import RerankRequest

        ranker = _get_ranker()
        passages = [
            {"id": str(i), "text": (d.page_content or "")[:8000]}
            for i, d in enumerate(documents)
        ]
        request = RerankRequest(query=query, passages=passages)
        ranked = ranker.rerank(request)

        out: list[Document] = []
        for item in ranked[:top_n]:
            idx = int(item["id"])
            if idx < 0 or idx >= len(documents):
                continue
            base = documents[idx]
            score = item.get("score")
            meta = dict(base.metadata)
            if score is not None:
                try:
                    meta["_rerank_score"] = float(score)
                except (TypeError, ValueError):
                    meta["_rerank_score"] = score
            out.append(Document(page_content=base.page_content, metadata=meta))

        if len(out) < min(top_n, len(documents)):
            logger.warning("FlashRank 映射结果不完整，降级为原顺序截断")
            return list(documents)[:top_n]
        return out[:top_n]

    except Exception as e:
        logger.warning(f"FlashRank 重排失败，使用原向量顺序截断: {e}")
        return list(documents)[:top_n]
