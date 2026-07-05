"""Native Milvus vector store manager for write and hybrid search."""

import time
import uuid
from typing import Any, cast

from langchain_core.documents import Document
from loguru import logger
from pymilvus import AnnSearchRequest, RRFRanker, WeightedRanker
from pymilvus.orm.mutation import MutationResult

from app.config import config
from app.core.milvus_client import milvus_manager
from app.services.vector_embedding_service import vector_embedding_service


class VectorStoreManager:
    """基于原生 PyMilvus 的唯一检索入口"""

    def __init__(self) -> None:
        self.collection_name = milvus_manager.COLLECTION_NAME

    def add_documents(self, documents: list[Document]) -> list[str]:
        """
        批量添加文档到 Milvus。

        Dense 向量由 DashScope embedding 生成；BM25 sparse 向量由 Milvus Function
        根据 content 字段自动生成。
        """
        if not documents:
            return []

        try:
            start_time = time.time()
            collection = self._get_collection()
            ids = [str(uuid.uuid4()) for _ in documents]
            texts = [doc.page_content for doc in documents]
            dense_vectors = vector_embedding_service.embed_documents(texts)

            entities = [
                {
                    milvus_manager.PRIMARY_FIELD: doc_id,
                    milvus_manager.DENSE_VECTOR_FIELD: dense_vector,
                    milvus_manager.CONTENT_FIELD: doc.page_content,
                    milvus_manager.METADATA_FIELD: doc.metadata,
                }
                for doc_id, dense_vector, doc in zip(ids, dense_vectors, documents, strict=True)
            ]
            result = collection.insert(entities)
            collection.flush()

            elapsed = time.time() - start_time
            logger.info(
                f"批量添加 {len(documents)} 个文档到 Milvus 完成, "
                f"insert_count={getattr(result, 'insert_count', len(ids))}, "
                f"耗时: {elapsed:.2f}秒, 平均: {elapsed / len(documents):.2f}秒/个"
            )
            return ids
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            raise

    def delete_by_source(self, file_path: str) -> int:
        """
        删除指定来源文件的所有分片。
        """
        try:
            collection = self._get_collection()
            escaped_file_path = file_path.replace("\\", "\\\\").replace('"', '\\"')
            expr = f'{milvus_manager.METADATA_FIELD}["_source"] == "{escaped_file_path}"'

            result = cast(MutationResult, collection.delete(expr))
            deleted_count = int(result.delete_count)
            collection.flush()

            logger.info(f"删除文件旧数据: {file_path}, 删除数量: {deleted_count}")
            return deleted_count
        except Exception as e:
            logger.warning(f"删除旧数据失败 (可能是首次索引): {e}")
            return 0

    def hybrid_search(self, query: str, k: int = 3) -> list[Document]:
        """
        使用 Milvus 原生 hybrid_search 执行 dense 语义检索 + BM25 sparse 检索。
        """
        if not query or not query.strip():
            return []

        try:
            collection = self._get_collection()
            limit = max(k, 1)
            query_vector = vector_embedding_service.embed_query(query)

            dense_req = AnnSearchRequest(
                data=[query_vector],
                anns_field=milvus_manager.DENSE_VECTOR_FIELD,
                param={
                    "metric_type": config.milvus_metric_type.upper(),
                    "params": {"nprobe": 10},
                },
                limit=limit,
            )
            sparse_req = AnnSearchRequest(
                data=[query],
                anns_field=milvus_manager.SPARSE_VECTOR_FIELD,
                param={
                    "metric_type": "BM25",
                    "params": {
                        "drop_ratio_search": config.milvus_sparse_drop_ratio_search,
                    },
                },
                limit=limit,
            )

            ranker = self._build_ranker()
            results = collection.hybrid_search(
                reqs=[dense_req, sparse_req],
                rerank=ranker,
                limit=limit,
                output_fields=[
                    milvus_manager.CONTENT_FIELD,
                    milvus_manager.METADATA_FIELD,
                ],
            )
            first_hits: Any = next(iter(cast(Any, results)), [])
            docs = self._hits_to_documents(first_hits)
            logger.debug(
                f"Milvus 混合检索完成: query='{query}', ranker={config.milvus_hybrid_ranker}, "
                f"结果数={len(docs)}"
            )
            return docs
        except Exception as e:
            logger.error(f"Milvus 混合检索失败: {e}")
            return []

    def similarity_search(self, query: str, k: int = 3) -> list[Document]:
        """兼容旧调用名；实际统一走 Milvus 原生混合检索。"""
        return self.hybrid_search(query, k=k)

    def _get_collection(self):
        _ = milvus_manager.connect()
        return milvus_manager.get_collection()

    def _build_ranker(self):
        if config.milvus_hybrid_ranker == "rrf":
            return RRFRanker()
        return WeightedRanker(
            config.milvus_dense_weight,
            config.milvus_sparse_weight,
        )

    def _hits_to_documents(self, hits: Any) -> list[Document]:
        docs: list[Document] = []
        for hit in hits:
            entity = hit.entity
            content = entity.get(milvus_manager.CONTENT_FIELD)
            metadata = entity.get(milvus_manager.METADATA_FIELD) or {}
            if not isinstance(metadata, dict):
                metadata = {"_raw_metadata": metadata}
            metadata = dict(metadata)
            metadata["_milvus_id"] = str(hit.id)
            metadata["_score"] = float(hit.score)
            docs.append(Document(page_content=content or "", metadata=metadata))
        return docs


# 全局单例
vector_store_manager = VectorStoreManager()
