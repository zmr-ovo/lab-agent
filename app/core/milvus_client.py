"""Milvus 客户端工厂模块"""

from loguru import logger
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    MilvusClient,
    MilvusException,
    connections,
    utility,
)

from app.config import config


class MilvusClientManager:
    """Milvus 客户端管理器"""

    # 常量定义
    COLLECTION_NAME: str = "biz"
    PRIMARY_FIELD: str = "id"
    DENSE_VECTOR_FIELD: str = "vector"
    SPARSE_VECTOR_FIELD: str = "sparse_vector"
    CONTENT_FIELD: str = "content"
    METADATA_FIELD: str = "metadata"
    BM25_FUNCTION_NAME: str = "content_bm25"
    VECTOR_DIM: int = 1024  # 统一使用 1024 维
    ID_MAX_LENGTH: int = 100
    CONTENT_MAX_LENGTH: int = 8000
    DEFAULT_SHARD_NUMBER: int = 2

    def __init__(self) -> None:
        """初始化 Milvus 客户端管理器"""
        self._client: MilvusClient | None = None
        self._collection: Collection | None = None

    def connect(self) -> MilvusClient:
        """
        连接到 Milvus 服务器并初始化 collection

        Returns:
            MilvusClient: Milvus 客户端实例

        Raises:
            RuntimeError: 连接或初始化失败时抛出
        """
        # 幂等：导入阶段可能已由检索服务提前连接，避免重复初始化
        if self._collection is not None and self._client is not None:
            logger.debug("Milvus 已连接，跳过重复 connect")
            return self._client

        try:
            logger.info(f"正在连接到 Milvus: {config.milvus_host}:{config.milvus_port}")

            # 建立连接
            connections.connect(
                alias="default",
                host=config.milvus_host,
                port=str(config.milvus_port),
                timeout=config.milvus_timeout / 1000,  # 转换为秒
            )

            # 创建客户端
            uri = f"http://{config.milvus_host}:{config.milvus_port}"
            self._client = MilvusClient(uri=uri)

            logger.info("成功连接到 Milvus")

            # 检查并创建 collection
            if not self._collection_exists():
                logger.info(f"collection '{self.COLLECTION_NAME}' 不存在，正在创建...")
                self._create_collection()
                logger.info(f"成功创建 collection '{self.COLLECTION_NAME}'")
            else:
                logger.info(f"collection '{self.COLLECTION_NAME}' 已存在")
                self._collection = Collection(self.COLLECTION_NAME)
                if self._schema_requires_recreate():
                    logger.warning(
                        f"collection '{self.COLLECTION_NAME}' schema 与原生混合检索不兼容，"
                        "正在重建。请在启动后重新上传知识库文档。"
                    )
                    _ = utility.drop_collection(self.COLLECTION_NAME)
                    self._create_collection()
                    logger.info(f"成功重建 collection '{self.COLLECTION_NAME}'")
                else:
                    self._ensure_indexes()

            # 加载 collection
            self._load_collection()

            return self._client

        except MilvusException as e:
            logger.error(f"Milvus 操作失败: {e}")
            self.close()
            raise RuntimeError(f"Milvus 操作失败: {e}") from e
        except ConnectionError as e:
            logger.error(f"连接 Milvus 失败: {e}")
            self.close()
            raise RuntimeError(f"连接 Milvus 失败: {e}") from e
        except Exception as e:
            logger.error(f"连接 Milvus 失败: {e}")
            self.close()
            raise RuntimeError(f"连接 Milvus 失败: {e}") from e

    def _collection_exists(self) -> bool:
        """检查 collection 是否存在"""
        # pymilvus 的类型标注可能不准确，实际返回 bool
        result = utility.has_collection(self.COLLECTION_NAME)
        return bool(result)

    def _create_collection(self) -> None:
        """创建支持 dense + BM25 sparse 混合检索的 biz collection"""
        # 定义字段
        fields = [
            FieldSchema(
                name=self.PRIMARY_FIELD,
                dtype=DataType.VARCHAR,
                max_length=self.ID_MAX_LENGTH,
                is_primary=True,
            ),
            FieldSchema(
                name=self.DENSE_VECTOR_FIELD,
                dtype=DataType.FLOAT_VECTOR,
                dim=self.VECTOR_DIM,
            ),
            FieldSchema(
                name=self.SPARSE_VECTOR_FIELD,
                dtype=DataType.SPARSE_FLOAT_VECTOR,
            ),
            FieldSchema(
                name=self.CONTENT_FIELD,
                dtype=DataType.VARCHAR,
                max_length=self.CONTENT_MAX_LENGTH,
                enable_analyzer=True,
            ),
            FieldSchema(
                name=self.METADATA_FIELD,
                dtype=DataType.JSON,
            ),
        ]
        bm25_function = Function(
            name=self.BM25_FUNCTION_NAME,
            input_field_names=[self.CONTENT_FIELD],
            output_field_names=[self.SPARSE_VECTOR_FIELD],
            function_type=FunctionType.BM25,
        )

        # 创建 schema
        schema = CollectionSchema(
            fields=fields,
            description="Business knowledge collection",
            enable_dynamic_field=False,
            functions=[bm25_function],
        )

        # 创建 collection
        self._collection = Collection(
            name=self.COLLECTION_NAME,
            schema=schema,
            num_shards=self.DEFAULT_SHARD_NUMBER,
        )

        # 创建索引
        self._create_indexes()

    def _create_indexes(self) -> None:
        """为 dense vector 和 BM25 sparse vector 创建索引"""
        if self._collection is None:
            raise RuntimeError("Collection 未初始化")

        dense_index_params = {
            "metric_type": config.milvus_metric_type.upper(),  # COSINE / L2 / IP
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128},
        }
        _ = self._collection.create_index(
            field_name=self.DENSE_VECTOR_FIELD,
            index_params=dense_index_params,
        )
        logger.info(
            f"成功为 {self.DENSE_VECTOR_FIELD} 字段创建索引 "
            f"(metric={config.milvus_metric_type.upper()})"
        )

        sparse_index_params = {
            "metric_type": "BM25",
            "index_type": "SPARSE_INVERTED_INDEX",
            "params": {
                "inverted_index_algo": "DAAT_MAXSCORE",
                "bm25_k1": 1.2,
                "bm25_b": 0.75,
            },
        }
        _ = self._collection.create_index(
            field_name=self.SPARSE_VECTOR_FIELD,
            index_params=sparse_index_params,
        )
        logger.info(f"成功为 {self.SPARSE_VECTOR_FIELD} 字段创建 BM25 稀疏索引")

    def _schema_requires_recreate(self) -> bool:
        """检查现有 collection 是否满足原生混合检索 schema。"""
        if self._collection is None:
            return True

        fields = {field.name: field for field in self._collection.schema.fields}
        required_fields = {
            self.PRIMARY_FIELD,
            self.DENSE_VECTOR_FIELD,
            self.SPARSE_VECTOR_FIELD,
            self.CONTENT_FIELD,
            self.METADATA_FIELD,
        }
        missing = required_fields.difference(fields)
        if missing:
            logger.warning(f"Milvus schema 缺少字段: {sorted(missing)}")
            return True

        dense_field = fields[self.DENSE_VECTOR_FIELD]
        if dense_field.dtype != DataType.FLOAT_VECTOR:
            logger.warning(f"{self.DENSE_VECTOR_FIELD} 字段类型不是 FLOAT_VECTOR")
            return True
        existing_dim = getattr(dense_field, "params", {}).get("dim")
        if existing_dim != self.VECTOR_DIM:
            logger.warning(
                f"检测到向量维度不匹配！当前: {existing_dim}, 配置: {self.VECTOR_DIM}"
            )
            return True

        sparse_field = fields[self.SPARSE_VECTOR_FIELD]
        if sparse_field.dtype != DataType.SPARSE_FLOAT_VECTOR:
            logger.warning(f"{self.SPARSE_VECTOR_FIELD} 字段类型不是 SPARSE_FLOAT_VECTOR")
            return True

        content_field = fields[self.CONTENT_FIELD]
        if content_field.dtype != DataType.VARCHAR:
            logger.warning(f"{self.CONTENT_FIELD} 字段类型不是 VARCHAR")
            return True
        if not getattr(content_field, "params", {}).get("enable_analyzer"):
            logger.warning(f"{self.CONTENT_FIELD} 字段未启用 analyzer，无法支持 BM25")
            return True

        functions = getattr(self._collection.schema, "functions", []) or []
        has_bm25 = any(
            function.get("name") == self.BM25_FUNCTION_NAME
            and str(function.get("type")).upper().endswith("BM25")
            and function.get("input_field_names") == [self.CONTENT_FIELD]
            and function.get("output_field_names") == [self.SPARSE_VECTOR_FIELD]
            for function in functions
        )
        if not has_bm25:
            logger.warning("Milvus schema 缺少 content -> sparse_vector 的 BM25 Function")
            return True

        logger.info("Milvus hybrid search schema 匹配")
        return False

    def _ensure_indexes(self) -> None:
        """确保 dense 和 sparse 索引存在且 metric 与配置一致。"""
        if self._collection is None:
            return

        desired_dense_metric = config.milvus_metric_type.upper()
        desired = {
            self.DENSE_VECTOR_FIELD: desired_dense_metric,
            self.SPARSE_VECTOR_FIELD: "BM25",
        }

        try:
            current: dict[str, str] = {}
            for idx in self._collection.indexes:
                field_name = idx.field_name
                if field_name in desired:
                    current[field_name] = str((idx.params or {}).get("metric_type", "")).upper()
        except Exception as e:
            logger.warning(f"读取现有索引信息失败，跳过 metric 校验: {e}")
            return

        if current == desired:
            logger.info(
                f"向量索引 metric 匹配: dense={desired_dense_metric}, sparse=BM25"
            )
            return

        logger.warning(
            f"检测到向量索引不完整或 metric 不匹配！当前: {current}, 期望: {desired}，"
            "正在重建索引..."
        )
        try:
            self._collection.release()
        except Exception:
            pass
        self._collection.drop_index()
        self._create_indexes()
        logger.info("成功重建 dense+sparse 向量索引")

    def _load_collection(self) -> None:
        """加载 collection 到内存"""
        if self._collection is None:
            self._collection = Collection(self.COLLECTION_NAME)

        # 检查 collection 是否已加载（兼容多版本）
        try:
            # 方法 1: 尝试使用 utility.load_state（新版本）
            load_state = utility.load_state(self.COLLECTION_NAME)
            # load_state 返回字符串或枚举，如 "Loaded" 或 "NotLoad"
            state_name = getattr(load_state, "name", str(load_state))
            if state_name != "Loaded":
                self._collection.load()
                logger.info(f"成功加载 collection '{self.COLLECTION_NAME}'")
            else:
                logger.info(f"Collection '{self.COLLECTION_NAME}' 已加载")
        except AttributeError:
            # 方法 2: 直接尝试加载，捕获 "already loaded" 异常
            try:
                self._collection.load()
                logger.info(f"成功加载 collection '{self.COLLECTION_NAME}'")
            except MilvusException as e:
                error_msg = str(e).lower()
                if "already loaded" in error_msg or "loaded" in error_msg:
                    logger.info(f"Collection '{self.COLLECTION_NAME}' 已加载")
                else:
                    raise
        except Exception as e:
            logger.error(f"加载 collection 失败: {e}")
            raise

    def get_collection(self) -> Collection:
        """
        获取 collection 实例

        Returns:
            Collection: collection 实例

        Raises:
            RuntimeError: collection 未初始化时抛出
        """
        if self._collection is None:
            raise RuntimeError("Collection 未初始化，请先调用 connect()")
        return self._collection

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            bool: True 表示健康，False 表示异常
        """
        try:
            if self._client is None:
                return False

            # 尝试列出 connections
            _ = connections.list_connections()
            return True

        except (MilvusException, ConnectionError) as e:
            logger.error(f"Milvus 健康检查失败: {e}")
            return False
        except Exception as e:
            logger.error(f"Milvus 健康检查失败: {e}")
            return False

    def close(self) -> None:
        """关闭连接"""
        errors = []

        try:
            if self._collection is not None:
                self._collection.release()
                self._collection = None
        except Exception as e:
            errors.append(f"释放 collection 失败: {e}")

        try:
            if connections.has_connection("default"):
                connections.disconnect("default")
        except Exception as e:
            errors.append(f"断开连接失败: {e}")

        self._client = None

        if errors:
            error_msg = "; ".join(errors)
            logger.error(f"关闭 Milvus 连接时出现错误: {error_msg}")
        else:
            logger.info("已关闭 Milvus 连接")

    def __enter__(self) -> "MilvusClientManager":
        """上下文管理器入口"""
        _ = self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object
    ) -> None:
        """上下文管理器退出"""
        self.close()


# 全局单例
milvus_manager = MilvusClientManager()
