"""
通用 Plan-Execute-Replan 服务
基于 LangGraph 官方教程实现
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from app.agent.aiops import PlanExecuteState, executor, planner, replanner
from app.config import config
from mcp_servers.monitor_server import get_active_alerts_impl

# 节点名称常量
NODE_PLANNER = "planner"
NODE_EXECUTOR = "executor"
NODE_REPLANNER = "replanner"


class AIOpsService:
    """通用 Plan-Execute-Replan 服务"""

    def __init__(self):
        """初始化服务"""
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        logger.info("Plan-Execute-Replan Service 初始化完成")

    def _build_graph(self):
        """构建 Plan-Execute-Replan 工作流"""
        logger.info("构建工作流图...")

        # 创建状态图
        workflow = StateGraph(PlanExecuteState)

        # 添加节点
        workflow.add_node(NODE_PLANNER, planner)  # 制定计划
        workflow.add_node(NODE_EXECUTOR, executor)  # 执行步骤
        workflow.add_node(NODE_REPLANNER, replanner)  # 重新规划

        # 设置入口点
        workflow.set_entry_point(NODE_PLANNER)

        # 定义边
        workflow.add_edge(NODE_PLANNER, NODE_EXECUTOR)  # planner -> executor
        workflow.add_edge(NODE_EXECUTOR, NODE_REPLANNER)  # executor -> replanner

        # replanner 的条件边
        def should_continue(state: PlanExecuteState) -> str:
            """判断是否继续执行"""
            # 如果已经生成了最终响应，结束
            if state.get("response"):
                logger.info("已生成最终响应，结束流程")
                return END

            past_steps = state.get("past_steps", [])
            if len(past_steps) >= config.aiops_max_execution_steps:
                logger.warning(
                    f"已达到最大执行轮数 {config.aiops_max_execution_steps}，结束流程并交由服务层兜底"
                )
                return END

            # 如果还有计划步骤，继续执行
            plan = state.get("plan", [])
            if plan:
                logger.info(f"继续执行，剩余 {len(plan)} 个步骤")
                return NODE_EXECUTOR

            # 计划为空但没有响应，返回 replanner 生成响应
            logger.info("计划执行完毕，生成最终响应")
            return END

        workflow.add_conditional_edges(
            NODE_REPLANNER, should_continue, {NODE_EXECUTOR: NODE_EXECUTOR, END: END}
        )

        # 编译工作流
        compiled_graph = workflow.compile(checkpointer=self.checkpointer)

        logger.info("工作流图构建完成")
        return compiled_graph

    async def execute(
        self,
        user_input: str,
        session_id: str = "default",
        alerts: list[dict[str, Any]] | None = None,
        alert_source: str = "unknown",
        lookback_minutes: int = 60,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        执行 Plan-Execute-Replan 流程

        Args:
            user_input: 用户的任务描述
            session_id: 会话ID

        Yields:
            Dict[str, Any]: 流式事件
        """
        logger.info(f"[会话 {session_id}] 开始执行任务: {user_input}")

        # 初始化状态
        initial_state: PlanExecuteState = {
            "input": user_input,
            "plan": [],
            "past_steps": [],
            "response": "",
            "alerts": alerts or [],
            "alert_source": alert_source,
            "data_mode": config.aiops_data_mode,
            "lookback_minutes": lookback_minutes,
            "evidence": [],
            "replan_attempts": 0,
            "no_progress_rounds": 0,
        }

        try:
            yield {
                "type": "status",
                "stage": "data_source",
                "message": (
                    "当前使用 Mock 演示数据，不代表真实生产环境"
                    if config.aiops_data_mode == "mock"
                    else "当前使用真实 CLS/TMP/Alertmanager 数据"
                ),
                "data_mode": config.aiops_data_mode,
                "is_mock": config.aiops_data_mode == "mock",
                "alert_source": alert_source,
            }

            # 流式执行工作流
            config_dict: RunnableConfig = {
                "configurable": {
                    # 每次诊断独立运行，避免 operator.add 合并同一会话的旧证据。
                    "thread_id": f"{session_id}:{uuid.uuid4()}"
                }
            }

            try:
                async with asyncio.timeout(config.aiops_total_timeout_seconds):
                    async for event in self.graph.astream(
                        input=initial_state, config=config_dict, stream_mode="updates"
                    ):
                        # 解析事件
                        for node_name, node_output in event.items():
                            logger.info(f"节点 '{node_name}' 输出事件")

                            # 根据节点类型生成不同的事件
                            if node_name == NODE_PLANNER:
                                yield self._format_planner_event(node_output)

                            elif node_name == NODE_EXECUTOR:
                                yield self._format_executor_event(node_output)

                            elif node_name == NODE_REPLANNER:
                                yield self._format_replanner_event(node_output)
            except TimeoutError:
                final_values = self._read_graph_values(config_dict, initial_state)
                fallback_report = self._build_fallback_report(
                    final_values,
                    reason=(
                        f"诊断总耗时超过 {config.aiops_total_timeout_seconds:.1f} 秒，"
                        "已停止继续执行并输出已收集信息。"
                    ),
                )
                logger.warning(f"[会话 {session_id}] AIOps 诊断总超时，输出兜底报告")
                yield {
                    "type": "report",
                    "stage": "final_report",
                    "message": "诊断超时，已生成兜底报告",
                    "report": fallback_report,
                }
                yield {
                    "type": "complete",
                    "stage": "complete",
                    "message": "任务执行超时，已返回兜底报告",
                    "response": fallback_report,
                    "data_mode": config.aiops_data_mode,
                    "is_mock": config.aiops_data_mode == "mock",
                    "timeout": True,
                }
                return

            # 获取最终状态
            final_values = self._read_graph_values(config_dict, initial_state)
            final_response = str(final_values.get("response") or "")
            if not final_response.strip():
                final_response = self._build_fallback_report(
                    final_values,
                    reason="诊断流程结束时未生成最终报告，已基于已执行步骤和证据输出兜底报告。",
                )
                yield {
                    "type": "report",
                    "stage": "final_report",
                    "message": "最终报告缺失，已生成兜底报告",
                    "report": final_response,
                }

            # 发送完成事件
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": final_response,
                "data_mode": config.aiops_data_mode,
                "is_mock": config.aiops_data_mode == "mock",
            }

            logger.info(f"[会话 {session_id}] 任务执行完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] 任务执行失败: {e}", exc_info=True)
            fallback_report = self._build_fallback_report(
                initial_state,
                reason=f"诊断流程异常中断: {str(e)}",
            )
            yield {"type": "error", "stage": "error", "message": f"任务执行出错: {str(e)}"}
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行异常，已返回兜底报告",
                "response": fallback_report,
                "data_mode": config.aiops_data_mode,
                "is_mock": config.aiops_data_mode == "mock",
                "error": True,
            }

    async def diagnose(
        self,
        session_id: str = "default",
        alerts: list[dict[str, Any]] | None = None,
        lookback_minutes: int = 60,
        alert_source: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        AIOps 诊断接口（兼容旧接口）

        Args:
            session_id: 会话ID

        Yields:
            Dict[str, Any]: 诊断过程的流式事件
        """
        resolved_alert_source = alert_source or "api"
        selected_alerts = list(alerts or [])
        if not selected_alerts:
            resolved_alert_source = "alertmanager"
            alert_result = await get_active_alerts_impl()
            if alert_result.get("status") in {"error", "unavailable"}:
                yield {
                    "type": "status",
                    "stage": "fetching_alerts",
                    "message": f"获取活跃告警失败: {alert_result.get('error', 'unknown error')}",
                    "is_mock": alert_result.get("is_mock", False),
                }
            selected_alerts = alert_result.get("data") or []

        yield {
            "type": "status",
            "stage": "alerts_loaded",
            "message": f"已从 {resolved_alert_source} 获取 {len(selected_alerts)} 条活跃告警",
            "alert_source": resolved_alert_source,
            "alert_count": len(selected_alerts),
            "is_mock": config.aiops_data_mode == "mock",
        }

        if not selected_alerts:
            report = "# 告警分析报告\n\n当前未发现活跃告警，未执行日志和指标排查。"
            yield {
                "type": "report",
                "stage": "final_report",
                "message": "当前无活跃告警",
                "report": report,
                "is_mock": False,
            }
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "message": "诊断流程完成",
                "diagnosis": {"status": "no_active_alerts", "report": report},
                "is_mock": False,
            }
            return

        # 使用标准化任务描述，并把结构化告警作为不可忽略的诊断输入。
        from textwrap import dedent

        alerts_json = json.dumps(selected_alerts, ensure_ascii=False, default=str)
        aiops_task = dedent(f"""请诊断以下活跃告警，使用可用的知识库、监控指标和腾讯云 CLS 日志完成根因分析。
                告警来源: {resolved_alert_source}
                默认回看时间: {lookback_minutes} 分钟
                告警内容: {alerts_json}

                诊断报告输出格式要求：
                ```
                # 告警分析报告

                ---

                ## 📋 活跃告警清单

                | 告警名称 | 级别 | 目标服务 | 首次触发时间 | 最新触发时间 | 状态 |
                |---------|------|----------|-------------|-------------|------|
                | [告警1名称] | [级别] | [服务名] | [时间] | [时间] | 活跃 |
                | [告警2名称] | [级别] | [服务名] | [时间] | [时间] | 活跃 |

                ---

                ## 🔍 告警根因分析1 - [告警名称]

                ### 告警详情
                - **告警级别**: [级别]
                - **受影响服务**: [服务名]
                - **持续时间**: [X分钟]

                ### 症状描述
                [根据监控指标描述症状]

                ### 日志证据
                [引用查询到的关键日志]

                ### 根因结论
                [基于证据得出的根本原因]

                ---

                ## 🛠️ 处理方案执行1 - [告警名称]

                ### 已执行的排查步骤
                1. [步骤1]
                2. [步骤2]

                ### 处理建议
                [给出具体的处理建议]

                ### 预期效果
                [说明预期的效果]

                ---

                ## 🔍 告警根因分析2 - [告警名称]
                [如果有第2个告警，重复上述格式]

                ---

                ## 📊 结论

                ### 整体评估
                [总结所有告警的整体情况]

                ### 关键发现
                - [发现1]
                - [发现2]

                ### 后续建议
                1. [建议1]
                2. [建议2]

                ### 风险评估
                [评估当前风险等级和影响范围]
                ```

                **重要提醒**：
                - 最终输出必须是纯 Markdown 文本，不要包含 JSON 结构
                - 所有内容必须基于工具查询的真实数据，严禁编造
                - 如果某个步骤失败，在结论中如实说明，不要跳过""")

        async for event in self.execute(
            aiops_task,
            session_id,
            alerts=selected_alerts,
            alert_source=resolved_alert_source,
            lookback_minutes=lookback_minutes,
        ):
            # 转换事件格式以兼容旧的 API
            if event.get("type") == "complete":
                # 将 response 包装为 diagnosis 格式
                yield {
                    "type": "complete",
                    "stage": "diagnosis_complete",
                    "message": "诊断流程完成",
                    "diagnosis": {"status": "completed", "report": event.get("response", "")},
                    "data_mode": event.get("data_mode"),
                    "is_mock": event.get("is_mock", False),
                }
            else:
                yield event

    def _read_graph_values(
        self, config_dict: RunnableConfig, fallback: PlanExecuteState
    ) -> dict[str, Any]:
        """安全读取 LangGraph 最终状态。"""
        try:
            final_state = self.graph.get_state(config_dict)
            if final_state and final_state.values:
                return dict(final_state.values)
        except Exception as exc:
            logger.warning(f"读取 AIOps graph 状态失败，使用初始状态兜底: {exc}")
        return dict(fallback)

    def _build_fallback_report(self, state: dict[str, Any], reason: str) -> str:
        """基于已执行步骤和证据生成兜底 Markdown 报告。"""
        input_text = str(state.get("input") or "")
        past_steps = list(state.get("past_steps") or [])
        evidence = list(state.get("evidence") or [])
        alerts = list(state.get("alerts") or [])
        data_mode = str(state.get("data_mode") or config.aiops_data_mode)

        mock_notice = (
            "> **Mock 演示报告：以下数据为模拟数据，不代表真实生产环境。**\n\n"
            if data_mode == "mock"
            else ""
        )

        alert_lines = "\n".join(f"- `{json.dumps(alert, ensure_ascii=False, default=str)}`" for alert in alerts)
        if not alert_lines:
            alert_lines = "- 无结构化告警输入"

        step_lines = self._format_fallback_steps(past_steps)
        evidence_lines = self._format_fallback_evidence(evidence)

        return (
            f"{mock_notice}"
            "# 告警分析报告\n\n"
            "## 兜底说明\n"
            f"{reason}\n\n"
            "## 原始任务\n"
            f"{input_text or '未提供任务描述'}\n\n"
            "## 活跃告警上下文\n"
            f"{alert_lines}\n\n"
            "## 已执行步骤\n"
            f"{step_lines}\n\n"
            "## 已收集证据\n"
            f"{evidence_lines}\n\n"
            "## 结论\n"
            "当前报告由保护边界自动生成，仅汇总已完成步骤与已收集证据。"
            "请根据上述信息继续人工排查，或缩小时间范围后重新发起诊断。\n"
        )

    @staticmethod
    def _format_fallback_steps(past_steps: list[Any]) -> str:
        if not past_steps:
            return "未完成任何执行步骤。"

        lines: list[str] = []
        for index, item in enumerate(past_steps, 1):
            try:
                step, result = item
            except (TypeError, ValueError):
                step, result = f"步骤 {index}", item
            result_text = str(result)
            if len(result_text) > 600:
                result_text = result_text[:600] + "..."
            lines.append(f"{index}. **{step}**\n\n   {result_text}")
        return "\n\n".join(lines)

    @staticmethod
    def _format_fallback_evidence(evidence: list[Any]) -> str:
        if not evidence:
            return "未收集到工具证据。"

        lines: list[str] = []
        for index, item in enumerate(evidence[:10], 1):
            if isinstance(item, dict):
                tool = item.get("tool", "unknown")
                status = item.get("status", "unknown")
                content = str(item.get("content", ""))
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"{index}. `{tool}` ({status}): {content}")
            else:
                lines.append(f"{index}. {str(item)[:500]}")
        if len(evidence) > 10:
            lines.append(f"... 另有 {len(evidence) - 10} 条证据未展示")
        return "\n".join(lines)

    def _format_planner_event(self, state: dict | None) -> dict:
        """格式化 Planner 节点事件"""
        if not state:
            return {"type": "status", "stage": "planner", "message": "规划节点执行中"}

        plan = state.get("plan", [])

        return {
            "type": "plan",
            "stage": "plan_created",
            "message": f"执行计划已制定，共 {len(plan)} 个步骤",
            "plan": plan,
        }

    def _format_executor_event(self, state: dict | None) -> dict:
        """格式化 Executor 节点事件"""
        if not state:
            return {"type": "status", "stage": "executor", "message": "执行节点运行中"}

        plan = state.get("plan", [])
        past_steps = state.get("past_steps", [])
        evidence = state.get("evidence", [])

        if past_steps:
            last_step, _ = past_steps[-1]
            return {
                "type": "step_complete",
                "stage": "step_executed",
                "message": f"步骤执行完成 ({len(past_steps)}/{len(past_steps) + len(plan)})",
                "current_step": last_step,
                "remaining_steps": len(plan),
                "evidence_count": len(evidence),
            }
        else:
            return {"type": "status", "stage": "executor", "message": "开始执行步骤"}

    def _format_replanner_event(self, state: dict | None) -> dict:
        """格式化 Replanner 节点事件"""
        if not state:
            return {"type": "status", "stage": "replanner", "message": "评估节点运行中"}

        response = state.get("response", "")
        plan = state.get("plan", [])

        if response:
            # 已生成最终响应
            return {
                "type": "report",
                "stage": "final_report",
                "message": "最终报告已生成",
                "report": response,
            }
        else:
            # 重新规划
            return {
                "type": "status",
                "stage": "replanner",
                "message": f"评估完成，{'继续执行剩余步骤' if plan else '准备生成最终响应'}",
                "remaining_steps": len(plan),
            }


# 全局单例
aiops_service = AIOpsService()
