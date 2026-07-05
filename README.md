# Lab Agent

Lab Agent 是一个面向实验室场景的智能运维与知识服务原型，集成 RAG 知识库、多轮对话、流式输出和 AIOps 分步诊断。

## 主要能力

- RAG 知识问答：上传 Markdown/TXT 文档，自动切分、向量化并写入 Milvus。
- 混合检索重排：PyMilvus 原生 `hybrid_search` 同时使用 dense 向量和 BM25 sparse 检索，宽召回后用 FlashRank 本地重排；失败时自动降级。
- 多轮对话：支持普通响应和 SSE 流式响应。
- AIOps 诊断：通过 Plan-Execute-Replan 工作流调用日志、监控和知识库工具。
- MCP 集成：提供腾讯云 CLS 日志查询、TMP PromQL 和 Alertmanager 的 HTTP/stdio 入口。
- 可选联网搜索：配置 Tavily API Key 后，Agent 可检索外部时效信息。
- Web 页面：包含主界面和项目流程可视化页面。

## 技术栈

- Python 3.11-3.13
- FastAPI、LangChain、LangGraph
- DashScope 通义千问及文本嵌入模型
- Milvus、etcd、MinIO、Attu
- FlashRank
- FastMCP / Model Context Protocol
- uv、Docker Compose

## 环境要求

- Python 3.11 及以上、低于 3.14
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop、Colima 或其他 Docker 环境
- 阿里云 DashScope API Key

Tavily、腾讯云 CLS 和 Prometheus/TMP 配置均为可选项。

未配置真实云资源时，AIOps 默认运行在明确标识的 Mock 演示模式；Mock 结果不会伪装成生产数据。

## 快速开始

### Linux/macOS

```bash
git clone <repository_url>
cd super_biz_agent_py

# 按 uv.lock 创建 Python 3.11 虚拟环境
uv sync --frozen --python 3.11

# 创建并编辑本地配置
touch .env
# 至少填写 DASHSCOPE_API_KEY

# 启动 Milvus、MCP、FastAPI，并上传 aiops-docs 文档
make init
```

后续常用命令：

```bash
make start       # 启动 MCP 和 FastAPI
make stop        # 停止 MCP 和 FastAPI
make restart     # 重启应用服务
make up          # 启动 Milvus Docker 服务
make down        # 停止 Milvus Docker 服务
make upload      # 上传 aiops-docs 中的知识文档
make check       # 检查 FastAPI 和 Milvus 状态
make clean       # 清理日志、缓存和构建产物
```

## 服务地址

| 服务 | 地址 |
|------|------|
| Web 主界面 | <http://localhost:9900> |
| 项目流程图 | <http://localhost:9900/project-flow> |
| OpenAPI 文档 | <http://localhost:9900/docs> |
| 健康检查 | <http://localhost:9900/health> |
| Attu | <http://localhost:8000> |
| MinIO 控制台 | <http://localhost:9001> |
| Milvus | `localhost:19530` |

MinIO 的本地默认账号和密码均为 `minioadmin`，仅适合开发环境。

## 配置

应用默认从项目根目录的 `.env` 读取配置。最小配置示例：

```dotenv
DASHSCOPE_API_KEY=your-api-key
DASHSCOPE_MODEL=qwen-max
DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4

MILVUS_HOST=localhost
MILVUS_PORT=19530

RAG_TOP_K=3
RAG_FETCH_K=20
RAG_RERANK_ENABLED=true
RAG_FLASHRANK_MAX_LENGTH=512
RAG_TOTAL_TIMEOUT_SECONDS=120
RAG_TOOL_TIMEOUT_SECONDS=30
RAG_FALLBACK_ANSWER_ENABLED=true
RAG_RECURSION_LIMIT=12
RAG_SUMMARY_ENABLED=true
RAG_SUMMARY_TRIGGER_TOKENS=12000
RAG_SUMMARY_KEEP_MESSAGES=12
RAG_SUMMARY_TRIM_TOKENS=4000

MILVUS_METRIC_TYPE=COSINE
MILVUS_HYBRID_RANKER=weighted
MILVUS_DENSE_WEIGHT=0.7
MILVUS_SPARSE_WEIGHT=0.3
MILVUS_SPARSE_DROP_RATIO_SEARCH=0.2

CHUNK_MAX_SIZE=800
CHUNK_OVERLAP=100
```

可选 Tavily 联网搜索：

```dotenv
TAVILY_API_KEY=your-tavily-api-key
TAVILY_MAX_RESULTS=5
TAVILY_TIMEOUT_SECONDS=25
```

不配置 `TAVILY_API_KEY` 时，联网搜索工具不会注册，不影响其他功能。

默认 MCP 使用 HTTP：

```dotenv
MCP_CLS_TRANSPORT=streamable-http
MCP_CLS_URL=http://localhost:8003/mcp
MCP_MONITOR_TRANSPORT=streamable-http
MCP_MONITOR_URL=http://localhost:8004/mcp
```

AIOps 数据源模式：

```dotenv
# 演示模式，所有报告会显示 Mock 警告
AIOPS_DATA_MODE=mock

# 生产模式，只查询真实 CLS/TMP/Alertmanager，失败时不回退 Mock
# AIOPS_DATA_MODE=real

# 诊断保护边界
AIOPS_MAX_EXECUTION_STEPS=8
AIOPS_TOTAL_TIMEOUT_SECONDS=180
AIOPS_TOOL_TIMEOUT_SECONDS=30
AIOPS_FALLBACK_REPORT_ENABLED=true
AIOPS_REPLANNER_MAX_REPLANS=2
AIOPS_REPLANNER_MAX_NO_PROGRESS_ROUNDS=2
```

服务到 CLS Topic、CQL 和 PromQL 模板的映射在 [`aiops-resources.yml`](aiops-resources.yml) 中维护。

真实 CLS、Prometheus/TMP、Alertmanager 或 stdio MCP 的配置见 [`.env.real.example`](.env.real.example)。应用统一通过 [`app/config.py`](app/config.py) 加载 `.env` 和可选的 `.env.real`。

## API

| 功能 | 方法 | 路径 |
|------|------|------|
| 健康检查 | GET | `/health` |
| 普通对话 | POST | `/api/chat` |
| 流式对话 | POST | `/api/chat_stream` |
| 清除会话 | POST | `/api/chat/clear` |
| 查询会话 | GET | `/api/chat/session/{session_id}` |
| AIOps 诊断 | POST | `/api/aiops` |
| CLS 告警回调 | POST | `/api/aiops/webhook/cls` |
| AIOps 事件列表 | GET | `/api/aiops/incidents` |
| AIOps 技术报告 | GET | `/api/aiops/incidents/{incident_id}` |
| Markdown 报告正文 | GET | `/api/aiops/incidents/{incident_id}/report` |
| 上传并索引文档 | POST | `/api/upload` |
| 索引目录 | POST | `/api/index_directory` |

示例：

```bash
curl http://localhost:9900/health

curl -X POST http://localhost:9900/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"Id":"session-123","Question":"如何检查视频流卡顿？"}'

curl -X POST http://localhost:9900/api/upload \
  -F 'file=@aiops-docs/slow_response.md'

# 传入告警触发诊断；不传 alert/alerts 时主动拉取 Alertmanager
curl -N -X POST http://localhost:9900/api/aiops \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"incident-001","alert":{"status":"firing","labels":{"alertname":"HighErrorRate","severity":"critical","service":"video-gateway"},"annotations":{"description":"5xx错误率过高"}},"lookback_minutes":60}'
```

## CLS 闭环演示

启动完整服务后，浏览器打开 <http://127.0.0.1:9900>，点击右上角 **AI Ops / 一键演示** 即可运行可视化闭环。页面会展示真实 CLS 日志写入、明确标识的 Mock 告警回调、LangGraph 执行计划、排查步骤和最终 Markdown 报告。该按钮仅允许从本机访问。

启动 Lab Agent 后，可循环向真实 CLS 上传正常与故障日志，并在本机模拟一次明确标识为 Mock 的云告警回调：

```bash
.venv/bin/python -m scripts.run_aiops_demo --callback-mode local-mock --cycles 1 --interval 10
```

流程为：

```text
本地日志生成器 → 腾讯云 CLS → 本地 Mock 告警回调 → Agent 诊断 → Markdown 技术报告
```

事件与报告可通过以下接口查看，Markdown 文件同时保存在 `runtime/aiops_reports/`：

```bash
curl http://127.0.0.1:9900/api/aiops/incidents
curl http://127.0.0.1:9900/api/aiops/incidents/<incident_id>
curl http://127.0.0.1:9900/api/aiops/incidents/<incident_id>/report
```

接入真实 CLS 自定义接口回调时，在 `.env` 配置随机的 `AIOPS_WEBHOOK_TOKEN`，通过公网 HTTPS 地址回调：

```text
POST https://<public-host>/api/aiops/webhook/cls?token=<AIOPS_WEBHOOK_TOKEN>
```

推荐回调 JSON 内容：

```json
{
  "status": "firing",
  "labels": {
    "alertname": "LabAgentErrorAlert",
    "service": "lab-agent",
    "severity": "warning"
  },
  "annotations": {
    "summary": "CLS 检测到错误日志",
    "description": "最近 5 分钟 ERROR 日志数达到告警阈值"
  }
}
```

真实 CLS 负责回调时，循环脚本使用：

```bash
.venv/bin/python -m scripts.run_aiops_demo --callback-mode cls --cycles 1 --interval 10
```

持续循环演示需显式设置 `--cycles 0`。`local-mock` 模式每轮都会调用模型生成报告，持续运行会产生模型和 CLS 用量费用。

## Agent 流程

### Agent 边界模型

项目中的 ReAct RAG Agent 和 Plan-Execute-RePlan AIOps Agent 使用同一套保护理念，但按各自失败模式做差异化实现。`.env` 字段由 [`app/config.py`](app/config.py) 读取，内部边界配置结构定义在 [`app/config_models.py`](app/config_models.py)：

```text
AgentBoundaryConfig
  ├─ total_timeout_seconds   # 单次 Agent 运行总超时
  ├─ tool_timeout_seconds    # 单个工具调用超时
  └─ fallback_enabled        # 超时、异常或空响应时是否输出兜底结果

ReactBoundaryConfig
  ├─ recursion_limit         # ReAct / LangGraph 单次运行递归上限
  ├─ summary_trigger_tokens  # 触发历史总结的 token 阈值
  ├─ summary_keep_messages   # 总结后完整保留的最近消息数
  └─ summary_trim_tokens     # 每次送入总结模型的旧历史 token 预算

AIOpsBoundaryConfig
  ├─ max_execution_steps     # executor 最大执行步骤数
  ├─ max_replans             # replanner 最大重规划次数
  └─ max_no_progress_rounds  # replanner 连续空转轮数上限
```

共同边界负责“不要卡死、不要无限调用工具、失败时有结果”；ReAct Agent 重点防上下文膨胀和工具循环；AIOps Agent 重点防计划过长、重规划循环和诊断无结论。

### ReAct RAG Agent

普通问答由 `app/services/rag_agent_service.py` 提供，使用 `langchain.agents.create_agent` 创建 ReAct 风格工具调用 Agent。Agent 维护会话级 `thread_id`，通过 `MemorySaver` 保存多轮上下文，并用 `SummarizationMiddleware` 压缩早期对话历史；系统提示通过 `create_agent(system_prompt=...)` 注入，不反复写入会话消息；工具列表由本地工具和 MCP 工具合并而来。

```text
用户问题
  ↓
FastAPI /api/chat 或 /api/chat_stream
  ↓
RagAgentService 初始化 ChatQwen、MemorySaver、SummarizationMiddleware、本地工具和 MCP 工具
  ↓
应用 ReactBoundaryConfig：总超时、recursion_limit、工具调用次数限制、单工具超时、兜底回答
  ↓
SummarizationMiddleware 按 RAG_SUMMARY_* 配置压缩早期消息，仅保留最近上下文
  ↓
LLM 根据系统提示判断是否需要工具
  ├─ retrieve_knowledge：Milvus 原生 hybrid_search 宽召回 → FlashRank 重排 → 返回参考上下文
  ├─ get_current_time：返回当前时间
  ├─ Tavily 搜索：仅配置 TAVILY_API_KEY 后启用
  └─ MCP 工具：CLS 日志、TMP/Prometheus 指标、Alertmanager 告警等
  ↓
LLM 基于工具结果继续推理，可再次调用工具
  ↓
生成最终回答；超时、异常或空响应时按 RAG_FALLBACK_ANSWER_ENABLED 返回兜底答案；
流式接口以 SSE 输出 content/tool_call/complete/error 事件
```

知识检索链路：

```text
用户 query
  ↓
DashScope text-embedding-v4 生成 1024 维 dense vector
  ↓
Milvus BM25 Function 基于 content 生成 sparse query
  ↓
PyMilvus Collection.hybrid_search(dense + sparse)
  ↓
WeightedRanker 或 RRFRanker 融合
  ↓
FlashRank Cross-Encoder 精排
  ↓
格式化为带来源的参考资料交给 Qwen
```

### Plan-Execute-RePlan AIOps Agent

AIOps 诊断由 `app/services/aiops_service.py` 构建 LangGraph 状态图，核心节点在 `app/agent/aiops/` 下。它不是一次性 ReAct 对话，而是显式拆成“规划、执行、评估/重规划”三个阶段，适合需要多工具、多证据链的故障诊断。

```text
告警输入 / 主动拉取 Alertmanager
  ↓
AIOpsService.diagnose 标准化告警、数据源模式和回看窗口
  ↓
应用 AIOpsBoundaryConfig：总超时、工具超时、最大执行步数、重规划限制、空转保护、兜底报告
  ↓
planner
  ├─ 先调用 retrieve_knowledge 检索内部排障经验
  ├─ 拉取本地工具与 MCP 工具清单
  └─ ChatQwen 生成 4-6 步结构化计划
  ↓
executor
  ├─ 取当前计划第 1 步
  ├─ 绑定本地工具和 MCP 工具
  ├─ 对单轮工具调用施加 AIOPS_TOOL_TIMEOUT_SECONDS 超时
  ├─ 最多执行 AIOPS_MAX_EXECUTION_STEPS 个步骤，收集日志、指标、知识库和时间证据
  └─ 写入 past_steps 与 evidence，移除已执行步骤
  ↓
replanner
  ├─ 判断信息是否足够
  ├─ continue：继续执行剩余步骤
  ├─ replan：替换剩余计划，最多 AIOPS_REPLANNER_MAX_REPLANS 次
  ├─ 空转保护：连续无有效计划变化达到阈值后强制收敛
  └─ respond：生成最终 Markdown 诊断报告
  ↓
总耗时超过 AIOPS_TOTAL_TIMEOUT_SECONDS、模型空响应或异常时按 AIOPS_FALLBACK_REPORT_ENABLED 输出兜底 Markdown 报告
  ↓
SSE 输出 plan/step_complete/status/report/complete 事件
```

## 项目结构

```text
lab agent/
├── app/                         # FastAPI 应用、Agent、业务服务和工具
│   ├── agent/
│   │   ├── __init__.py          # Agent 包标记
│   │   ├── mcp_client.py        # MCP 客户端创建、工具加载和重试拦截器
│   │   └── aiops/
│   │       ├── __init__.py      # 导出 PlanExecuteState、planner、executor、replanner
│   │       ├── state.py         # Plan-Execute-RePlan 状态定义
│   │       ├── planner.py       # 诊断计划生成节点
│   │       ├── executor.py      # 单步执行节点，绑定工具并收集 evidence
│   │       ├── replanner.py     # 继续、重规划或生成最终报告的决策节点
│   │       └── utils.py         # 工具描述格式化辅助函数
│   ├── api/
│   │   ├── __init__.py          # API 包标记
│   │   ├── chat.py              # 普通聊天、流式聊天、会话清理和会话查询接口
│   │   ├── file.py              # 文档上传和目录索引接口
│   │   ├── health.py            # FastAPI 与 Milvus 健康检查接口
│   │   └── aiops.py             # AIOps 诊断、CLS webhook、事件和报告接口
│   ├── core/
│   │   ├── __init__.py          # Core 包标记
│   │   ├── llm_factory.py       # ChatOpenAI 兼容模型工厂
│   │   └── milvus_client.py     # PyMilvus 连接、hybrid schema、索引和 collection 生命周期
│   ├── models/
│   │   ├── __init__.py          # Models 包标记
│   │   ├── request.py           # Chat/Clear 请求模型
│   │   ├── response.py          # 通用 API 响应和会话信息模型
│   │   ├── document.py          # 文档上传/索引结果模型
│   │   └── aiops.py             # AIOps 请求、事件、告警和报告模型
│   ├── services/
│   │   ├── __init__.py          # Services 包标记
│   │   ├── rag_agent_service.py # ReAct RAG Agent，负责对话、工具调用和 SSE 输出
│   │   ├── aiops_service.py     # LangGraph Plan-Execute-RePlan 诊断编排
│   │   ├── document_splitter_service.py # Markdown/TXT 切分与元数据生成
│   │   ├── vector_embedding_service.py  # DashScope text-embedding-v4 LangChain Embeddings 实现
│   │   ├── vector_store_manager.py      # 唯一 Milvus 原生写入与 hybrid_search 检索入口
│   │   ├── vector_index_service.py      # 文件读取、旧分片删除、切分和入库
│   │   ├── rerank_service.py     # FlashRank Cross-Encoder 精排与失败降级
│   │   └── incident_service.py   # AIOps 事件、Markdown 报告和报告文件管理
│   ├── tools/
│   │   ├── __init__.py          # 导出本地工具，并按配置追加 Tavily
│   │   ├── knowledge_tool.py    # retrieve_knowledge 工具，调用 Milvus hybrid 检索和 FlashRank
│   │   ├── time_tool.py         # 当前时间工具
│   │   └── tavily_search_tool.py # 可选 Tavily 联网搜索工具
│   ├── utils/
│   │   ├── __init__.py          # Utils 包标记
│   │   └── logger.py            # Loguru 日志格式和输出配置
│   ├── __init__.py              # app 包标记
│   ├── config.py                # Pydantic Settings 配置中心，读取 .env/.env.real
│   ├── config_models.py         # 内部配置结构，如 Agent 边界保护配置
│   ├── config_real.py           # 真实环境配置兼容入口
│   └── main.py                  # FastAPI 应用入口、路由注册、静态资源挂载和生命周期
├── mcp_servers/
│   ├── README.md                # MCP 服务说明
│   ├── __init__.py              # MCP 包标记
│   ├── aiops_common.py          # CLS/TMP/AIOps 共享配置、Mock 标识和资源映射
│   ├── cls_server.py            # CLS 日志查询 Streamable HTTP MCP 服务
│   ├── cls_stdio.py             # CLS 日志查询 stdio MCP 服务
│   ├── monitor_server.py        # 监控指标、Alertmanager Streamable HTTP MCP 服务
│   └── monitor_stdio.py         # 监控指标、Alertmanager stdio MCP 服务
├── scripts/
│   ├── __init__.py              # Scripts 包标记
│   ├── upload_cls_test_logs.py  # 向腾讯云 CLS 上传演示日志
│   └── run_aiops_demo.py        # 生成日志、触发回调并运行 AIOps 闭环演示
├── static/
│   ├── index.html               # Web 主界面
│   ├── app.js                   # 前端交互、聊天、上传和 AIOps 演示逻辑
│   ├── styles.css               # 主界面样式
│   └── project-flow.html        # 项目架构和流程可视化页面
├── tests/
│   ├── test_api_chat_file.py    # chat/file API endpoint 函数测试
│   ├── test_aiops_boundaries.py # AIOps 最大步数、超时、空转保护和兜底报告测试
│   ├── test_aiops_common.py     # AIOps 共享逻辑测试
│   ├── test_aiops_mcp_tools.py  # MCP 工具行为测试
│   ├── test_aiops_models.py     # AIOps Pydantic 模型测试
│   ├── test_aiops_service.py    # Plan-Execute-RePlan 服务测试
│   ├── test_aiops_webhook.py    # CLS webhook 与事件接口测试
│   ├── test_cls_upload.py       # CLS 日志上传脚本测试
│   ├── test_rag_agent_summary.py # ReAct Agent SummarizationMiddleware 接入测试
│   └── test_vector_store_manager.py # Milvus 原生 hybrid_search 写入/检索测试
├── aiops-docs/
│   ├── cpu_high_usage.md        # CPU 高使用率排障知识
│   ├── memory_high_usage.md     # 内存高使用率排障知识
│   ├── disk_high_usage.md       # 磁盘空间高使用率排障知识
│   ├── service_unavailable.md   # 服务不可用排障知识
│   └── slow_response.md         # 响应慢排障知识
├── uploads/                     # 运行时上传目录，已被 Git 忽略
├── volumes/                     # Milvus/MinIO/etcd 持久化数据，已被 Git 忽略
├── runtime/                     # 运行时 AIOps 报告目录，已被 Git 忽略
├── logs/                        # Loguru 运行日志，已被 Git 忽略
├── htmlcov/                     # pytest-cov HTML 覆盖率报告，已被 Git 忽略
├── .env                         # 本地环境变量，已被 Git 忽略
├── .env.real.example            # 真实 CLS/TMP/Alertmanager 配置示例
├── .gitignore                   # Git 忽略规则
├── .pre-commit-config.yaml      # Ruff、Black、isort、Bandit 等提交前检查
├── .python-version              # 本地 Python 版本提示
├── .uvignore                    # uv 构建/同步忽略规则
├── aiops-resources.yml          # 服务到 CLS Topic、CQL、PromQL 的资源映射
├── Makefile                     # Linux/macOS 自动化启动、停止、检查和上传命令
├── pyproject.toml               # Python 项目元数据、依赖和工具配置
├── pyrightconfig.json           # Pyright/Pylance 类型检查配置
├── README.md                    # 项目说明文档
├── uv.lock                      # uv 锁定依赖版本
└── vector-database.yml          # Milvus、etcd、MinIO、Attu Docker Compose 配置
```

运行时可能还会生成 `server.log`、`mcp_cls.log`、`mcp_monitor.log`、`.venv/`、`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/`、`super_biz_agent_py.egg-info/` 等本地文件或缓存目录，它们不属于核心源码。

## `.yml` 和 `.yaml` 文件说明

`.yml` 与 `.yaml` 是同一种 YAML 格式，只是扩展名写法不同。本项目中的相关文件均有明确用途：

| 文件 | 用途 | 是否保留 |
|------|------|----------|
| `vector-database.yml` | 定义 Milvus、etcd、MinIO 和 Attu 容器；Makefile 会使用它启停向量数据库 | 必须保留 |
| `aiops-resources.yml` | 维护服务名到 CLS Topic、CQL、PromQL 的映射，供 AIOps 工具解析资源 | 必须保留 |
| `.pre-commit-config.yaml` | 配置 Ruff、Black、isort、Bandit 等提交前检查 | 运行应用不需要，但建议保留 |

启用提交前检查：

```bash
uv sync --extra dev
make pre-commit-install
make pre-commit
```

当前仓库没有 Windows `.bat` 启停脚本；日常启动统一使用 Makefile 和 Docker Compose。

## 开发与检查

```bash
uv sync --extra dev --python 3.11
make lint
make type-check
make test
```

当前仓库已包含 API、RAG Agent、Milvus hybrid search、AIOps 与 MCP 相关测试，也可以直接运行：

```bash
uv run ruff check .
uv run python -m pytest
```

## 常见问题

### Milvus 连接失败

```bash
docker compose -f vector-database.yml ps
docker compose -f vector-database.yml restart standalone
```

同时检查 `.env` 中的 `MILVUS_HOST` 和 `MILVUS_PORT`。

### 服务无法启动

```bash
tail -f server.log
tail -f mcp_cls.log
tail -f mcp_monitor.log
```

运行时日志、PID、`uploads/`、`volumes/`、虚拟环境和缓存目录都已通过 `.gitignore` 排除。

### FlashRank 首次运行较慢

FlashRank 首次重排可能需要准备本地模型。设置 `RAG_RERANK_ENABLED=false` 可关闭精排，直接使用 Milvus 原生 hybrid_search 的融合结果。

## 更多文档

- [MCP 服务说明](mcp_servers/README.md)
- 项目流程可视化页面：启动服务后访问 <http://localhost:9900/project-flow>

## License

MIT License

## 运行步骤
1. 启动 Docker

打开 Docker Desktop(或 colima start),等它就绪。验证:

docker info   # 不报错即可

2. 一键初始化(首次运行)

make init
这会:启动 Milvus/etcd/MinIO/Attu 容器 → 启动 MCP 和 FastAPI → 上传 aiops-docs/ 知识文档。

3. 访问

Web 主界面: http://localhost:9900
项目流程图: http://localhost:9900/project-flow
API 文档: http://localhost:9900/docs
健康检查: http://localhost:9900/health

日常命令

make start     # 启动 MCP + FastAPI(容器已在跑时)
make stop      # 停止应用
make up/down   # 启停 Milvus 容器
make check     # 检查 FastAPI 和 Milvus 状态
make logs      # 查看日志

## 启动
1. 先启动 Docker Desktop(等右上角图标变绿/不再转圈)

2. 启动项目 —— 取决于你上次是怎么关的:

cd "/Users/miaoran/Documents/Program/lab agent"

# 情况 A:你上次只用了 make stop(Milvus 容器还在)
make start          # 只拉起 MCP + FastAPI,几秒就好

# 情况 B:你上次用了 make down 或重启过电脑(容器没了)
make up             # 先起 Milvus 容器(等它 healthy)
make start          # 再起 MCP + FastAPI
不确定是哪种就先跑 make check 看状态,或者直接两条都跑(make up 检测到容器已在跑会自动跳过)。

注意:不需要再 make init 或 make upload —— 文档已经索引在 Milvus 里了,数据持久化在 volumes/。只有清空过数据卷或想重新导入文档时才需要 make upload。

3. 验证

make check                        # 一键检查
# 或浏览器打开 http://localhost:9900
关闭
按"关多干净"分三档:

make stop     # 日常用这个:停 MCP + FastAPI,Milvus 容器留着 → 下次 make start 秒开
make down     # 连 Milvus 容器一起停(释放内存/端口)→ 下次需要 make up
彻底关:先 make stop 再 make down,然后退出 Docker Desktop。数据都在 volumes/,不会丢。

最省心的日常节奏:用 make stop 关 → 下次 make start 开。只有重启电脑(Docker 容器被关)后,才需要先补一个 make up。
