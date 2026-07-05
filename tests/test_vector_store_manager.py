from typing import Any

import app.services.vector_store_manager as store_module
from app.config import config
from app.services.vector_store_manager import VectorStoreManager


class FakeAnnSearchRequest:
    def __init__(
        self,
        data: list[Any],
        anns_field: str,
        param: dict[str, Any],
        limit: int,
    ) -> None:
        self.data = data
        self.anns_field = anns_field
        self.param = param
        self.limit = limit


class FakeWeightedRanker:
    def __init__(self, dense_weight: float, sparse_weight: float) -> None:
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight


class FakeRRFRanker:
    pass


class FakeEntity:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get(self, key: str) -> Any:
        return self._values.get(key)


class FakeHit:
    def __init__(self, hit_id: str, score: float, entity: FakeEntity) -> None:
        self.id = hit_id
        self.score = score
        self.entity = entity


class FakeCollection:
    def __init__(self, results: list[list[FakeHit]]) -> None:
        self.results = results
        self.hybrid_search_kwargs: dict[str, Any] | None = None

    def hybrid_search(self, **kwargs: Any) -> list[list[FakeHit]]:
        self.hybrid_search_kwargs = kwargs
        return self.results


def test_hybrid_search_builds_dense_sparse_requests_and_weighted_ranker(monkeypatch):
    query_vector = [0.1, 0.2, 0.3]
    collection = FakeCollection(
        [
            [
                FakeHit(
                    "chunk-1",
                    0.93,
                    FakeEntity(
                        {
                            store_module.milvus_manager.CONTENT_FIELD: "root cause content",
                            store_module.milvus_manager.METADATA_FIELD: {
                                "_source": "runbook.md",
                                "title": "Runbook",
                            },
                        }
                    ),
                )
            ]
        ]
    )
    manager = VectorStoreManager()

    monkeypatch.setattr(manager, "_get_collection", lambda: collection)
    monkeypatch.setattr(store_module.vector_embedding_service, "embed_query", lambda _: query_vector)
    monkeypatch.setattr(store_module, "AnnSearchRequest", FakeAnnSearchRequest)
    monkeypatch.setattr(store_module, "WeightedRanker", FakeWeightedRanker)
    monkeypatch.setattr(config, "milvus_hybrid_ranker", "weighted")
    monkeypatch.setattr(config, "milvus_metric_type", "cosine")
    monkeypatch.setattr(config, "milvus_dense_weight", 0.7)
    monkeypatch.setattr(config, "milvus_sparse_weight", 0.3)
    monkeypatch.setattr(config, "milvus_sparse_drop_ratio_search", 0.15)

    docs = manager.hybrid_search("why is video-gateway failing", k=5)

    assert len(docs) == 1
    assert docs[0].page_content == "root cause content"
    assert docs[0].metadata["_source"] == "runbook.md"
    assert docs[0].metadata["title"] == "Runbook"
    assert docs[0].metadata["_milvus_id"] == "chunk-1"
    assert docs[0].metadata["_score"] == 0.93

    assert collection.hybrid_search_kwargs is not None
    kwargs = collection.hybrid_search_kwargs
    assert kwargs["limit"] == 5
    assert kwargs["output_fields"] == [
        store_module.milvus_manager.CONTENT_FIELD,
        store_module.milvus_manager.METADATA_FIELD,
    ]

    dense_req, sparse_req = kwargs["reqs"]
    assert dense_req.data == [query_vector]
    assert dense_req.anns_field == store_module.milvus_manager.DENSE_VECTOR_FIELD
    assert dense_req.param == {"metric_type": "COSINE", "params": {"nprobe": 10}}
    assert dense_req.limit == 5

    assert sparse_req.data == ["why is video-gateway failing"]
    assert sparse_req.anns_field == store_module.milvus_manager.SPARSE_VECTOR_FIELD
    assert sparse_req.param == {
        "metric_type": "BM25",
        "params": {"drop_ratio_search": 0.15},
    }
    assert sparse_req.limit == 5

    ranker = kwargs["rerank"]
    assert isinstance(ranker, FakeWeightedRanker)
    assert ranker.dense_weight == 0.7
    assert ranker.sparse_weight == 0.3


def test_hybrid_search_can_use_rrf_ranker(monkeypatch):
    collection = FakeCollection([])
    manager = VectorStoreManager()

    monkeypatch.setattr(manager, "_get_collection", lambda: collection)
    monkeypatch.setattr(store_module.vector_embedding_service, "embed_query", lambda _: [0.1])
    monkeypatch.setattr(store_module, "AnnSearchRequest", FakeAnnSearchRequest)
    monkeypatch.setattr(store_module, "RRFRanker", FakeRRFRanker)
    monkeypatch.setattr(config, "milvus_hybrid_ranker", "rrf")

    assert manager.hybrid_search("latency spike", k=2) == []
    assert collection.hybrid_search_kwargs is not None
    assert isinstance(collection.hybrid_search_kwargs["rerank"], FakeRRFRanker)


def test_hybrid_search_returns_empty_for_blank_query(monkeypatch):
    manager = VectorStoreManager()
    monkeypatch.setattr(
        manager,
        "_get_collection",
        lambda: (_ for _ in ()).throw(AssertionError("Milvus should not be called")),
    )

    assert manager.hybrid_search("   ", k=3) == []


def test_hits_to_documents_wraps_non_dict_metadata():
    manager = VectorStoreManager()
    hit = FakeHit(
        "chunk-2",
        0.42,
        FakeEntity(
            {
                store_module.milvus_manager.CONTENT_FIELD: "plain content",
                store_module.milvus_manager.METADATA_FIELD: "raw metadata",
            }
        ),
    )

    docs = manager._hits_to_documents([hit])

    assert len(docs) == 1
    assert docs[0].page_content == "plain content"
    assert docs[0].metadata["_raw_metadata"] == "raw metadata"
    assert docs[0].metadata["_milvus_id"] == "chunk-2"
    assert docs[0].metadata["_score"] == 0.42
