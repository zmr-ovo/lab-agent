# SuperBizAgent

SuperBizAgent 是一个面向实验室端到端视频传输场景的智能运维与知识服务原型，集成 RAG 知识库、多轮对话、流式输出和 AIOps 分步诊断。

## 主要能力

- RAG 知识问答：上传 Markdown/TXT 文档，自动切分、向量化并写入 Milvus。
- 检索重排：Milvus 宽召回后使用 FlashRank 本地重排；失败时自动降级。
- 多轮对话：支持普通响应和 SSE 流式响应。
- AIOps 诊断：通过 Plan-Execute-Replan 工作流调用日志、监控和知识库工具。
- MCP 集成：提供 CLS 日志查询和监控指标服务的 HTTP/stdio 入口。
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

真实 CLS、Prometheus/TMP 或 stdio MCP 的扩展配置见 [`.env.real.example`](.env.real.example) 和 [`app/config_real.py`](app/config_real.py)。`config_real.py` 是可选配置，不会自动替换默认配置。

## API

| 功能 | 方法 | 路径 |
|------|------|------|
| 健康检查 | GET | `/health` |
| 普通对话 | POST | `/api/chat` |
| 流式对话 | POST | `/api/chat_stream` |
| 清除会话 | POST | `/api/chat/clear` |
| 查询会话 | GET | `/api/chat/session/{session_id}` |
| AIOps 诊断 | POST | `/api/aiops` |
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
```

## 项目结构

```text
super_biz_agent_py/
├── app/
│   ├── agent/                 # AIOps 工作流与 MCP 客户端
│   ├── api/                   # FastAPI 路由
│   ├── core/                  # LLM 与 Milvus 基础组件
│   ├── models/                # 请求、响应和业务模型
│   ├── services/              # RAG、重排、索引和搜索服务
│   ├── tools/                 # 知识库、时间和 Tavily 工具
│   ├── config.py              # 默认配置
│   ├── config_real.py         # 可选真实环境扩展配置
│   └── main.py                # 应用入口
├── aiops-docs/                # 内置运维知识文档
├── docs/                      # 项目说明和图片
├── mcp_servers/               # CLS/Monitor HTTP 与 stdio 服务入口
├── static/                    # Web 页面、样式和脚本
├── uploads/                   # 运行时上传目录，已被 Git 忽略
├── volumes/                   # Milvus 持久化数据，已被 Git 忽略
├── Makefile                   # Linux/macOS 自动化命令
├── start-windows.bat          # Windows 一键启动脚本
├── stop-windows.bat           # Windows 一键停止脚本
├── vector-database.yml        # Milvus Docker Compose 配置
├── .pre-commit-config.yaml    # 可选的 Git 提交前检查配置
├── pyproject.toml             # Python 项目及工具配置
└── uv.lock                    # 锁定后的依赖版本
```

## `.bat`、`.yml` 和 `.yaml` 文件说明

`.yml` 与 `.yaml` 是同一种 YAML 格式，只是扩展名写法不同。本项目中的相关文件均有明确用途：

| 文件 | 用途 | 是否保留 |
|------|------|----------|
| `start-windows.bat` | Windows 下创建环境并启动 Milvus、MCP、FastAPI，随后上传知识文档 | 支持 Windows 时保留 |
| `stop-windows.bat` | Windows 下停止应用服务和 Docker Compose 服务 | 支持 Windows 时保留 |
| `vector-database.yml` | 定义 Milvus、etcd、MinIO 和 Attu 容器；Makefile 和 Windows 脚本都会使用 | 必须保留 |
| `.pre-commit-config.yaml` | 配置 Ruff、Black、isort、Bandit 等提交前检查 | 运行应用不需要，但建议保留 |

启用提交前检查：

```bash
uv sync --extra dev
make pre-commit-install
make pre-commit
```

如果项目明确不再支持 Windows，两个 `.bat` 文件及 README 中的 Windows 章节才可以一起删除。其余两个 YAML 文件不属于冗余文件。

## 开发与检查

```bash
uv sync --extra dev --python 3.11
make lint
make type-check
make test
```

当前仓库尚未提供 `tests/` 测试目录，因此 `make test` 需要在补充测试后使用。

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

FlashRank 首次重排可能需要准备本地模型。设置 `RAG_RERANK_ENABLED=false` 可关闭重排并退回普通向量检索。

## 更多文档

- [项目场景介绍](docs/project-intro.md)
- [MCP 服务说明](mcp_servers/README.md)
- [变更记录](CHANGELOG.md)

## License

MIT License
