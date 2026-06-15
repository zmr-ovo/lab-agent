# Lab Agent

Lab Agent 是一个面向实验室端到端视频传输场景的智能运维与知识服务原型，集成 RAG 知识库、多轮对话、流式输出和 AIOps 分步诊断。

## 主要能力

- RAG 知识问答：上传 Markdown/TXT 文档，自动切分、向量化并写入 Milvus。
- 检索重排：Milvus 宽召回后使用 FlashRank 本地重排；失败时自动降级。
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
