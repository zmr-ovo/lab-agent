# 变更记录

本文档说明各版本的版本号与主要改动。

## [1.2.2] — 2026-04-12

### 新增

- **RAG 宽召回 + FlashRank 本地重排**：Milvus 先按 `rag_fetch_k` 条数召回，再用 FlashRank cross-encoder 重排，最终只保留 `rag_top_k` 条进入上下文。
- 依赖 **`flashrank`**（轻量 CPU 推理，首次运行会下载小模型）。

### 配置（`app/config.py` / 环境变量）

| 变量 | 说明 | 默认 |
|------|------|------|
| `RAG_FETCH_K` | 向量宽召回条数（≥ `RAG_TOP_K`） | `20` |
| `RAG_TOP_K` | 重排后交给模型的条数 | `3` |
| `RAG_RERANK_ENABLED` | 是否启用 FlashRank | `true` |
| `RAG_FLASHRANK_MAX_LENGTH` | FlashRank `max_length` | `512` |

### 代码结构

- **`app/services/rerank_service.py`**：`rerank_documents()`，失败时降级为原向量顺序截断。
- **`app/tools/knowledge_tool.py`**：按开关选择 `fetch_k` / `top_k`，并打日志 `rerank=on|off, fetch_k=…, 最终 n 条`。

### 备注

- 关闭重排、与 1.2.1 行为接近：设置 `RAG_RERANK_ENABLED=false`（仍使用 `rag_top_k` 召回）。
- 若使用 `uv`，请在依赖变更后执行 `uv lock` / `uv sync` 更新锁文件。

---

## [1.2.1] — 初始导入

- 首版代码入库：FastAPI、RAG（Milvus + LangChain `create_agent`）、AIOps（LangGraph）、静态前端、MCP 等。
- `.env` 不纳入版本库，密钥通过本地环境配置。
