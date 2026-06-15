"""
Executor 节点：执行单个步骤
基于 LangGraph 官方教程实现
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_qwq import ChatQwen
from langgraph.prebuilt import ToolNode
from loguru import logger
from pydantic import SecretStr

from app.agent.mcp_client import get_mcp_client_with_retry
from app.config import config
from app.tools import get_current_time, retrieve_knowledge, with_optional_tavily

from .state import PlanExecuteState


async def executor(state: PlanExecuteState) -> dict[str, Any]:
    """
    执行节点：执行计划中的下一个步骤

    使用 LangGraph 的 ToolNode 自动处理工具调用
    """
    logger.info("=== Executor：执行步骤 ===")

    plan = state.get("plan", [])

    # 如果计划为空，不执行
    if not plan:
        logger.info("计划为空，跳过执行")
        return {}

    # 取出第一个步骤
    task = plan[0]
    logger.info(f"当前任务: {task}")

    try:
        # 获取本地工具
        local_tools = with_optional_tavily(
            [
                get_current_time,
                retrieve_knowledge,
            ]
        )

        # 获取 MCP 工具
        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()
        logger.info(f"可用工具数量: 本地 {len(local_tools)} + MCP {len(mcp_tools)}")

        # 合并所有工具
        all_tools = local_tools + mcp_tools

        # 创建 LLM（绑定工具）
        llm = ChatQwen(
            model=config.rag_model,
            api_key=SecretStr(config.dashscope_api_key),
            temperature=0,
        )
        llm_with_tools = llm.bind_tools(all_tools)

        # 创建工具节点（自动执行工具调用）
        tool_node = ToolNode(all_tools)

        alert_context = state.get("alerts", [])
        evidence: list[dict[str, Any]] = []

        # 构建消息，携带告警上下文和已获得证据。
        messages = [
            SystemMessage(
                content="""你是一个能力强大的助手，负责执行具体的任务步骤。

你可以使用各种工具来完成任务。对于每个步骤：
1. 理解步骤的目标
2. 选择合适的工具，如果已经指定了工具，则使用指定的工具
3. 调用工具获取信息
4. 返回执行结果

注意：
- 如果工具调用失败，请说明失败原因
- 不要编造数据，只返回实际获取的信息
- **优先使用知识库检索**；仅当知识库不足以完成本步骤时再使用联网搜索（Tavily）
- 执行结果要清晰、准确
- 工具结果中的 is_mock=true 表示演示数据，必须明确说明，不能当作生产事实
- 一个步骤可以连续调用多个工具，但最多进行 4 轮工具调用
- 专注于当前步骤，不要考虑其他任务"""
            ),
            HumanMessage(
                content=(
                    f"请执行以下任务: {task}\n"
                    f"告警上下文: {alert_context}\n"
                    f"数据模式: {state.get('data_mode', 'unknown')}\n"
                    f"默认回看窗口: {state.get('lookback_minutes', 60)} 分钟"
                )
            ),
        ]

        result = ""
        for round_index in range(4):
            llm_response = await llm_with_tools.ainvoke(messages)
            tool_calls = getattr(llm_response, "tool_calls", None) or []
            if not tool_calls:
                result = str(getattr(llm_response, "content", llm_response))
                break

            logger.info(f"第 {round_index + 1} 轮检测到 {len(tool_calls)} 个工具调用")
            messages.append(llm_response)
            tool_output = await tool_node.ainvoke({"messages": messages})
            new_messages = tool_output.get("messages", [])
            messages.extend(new_messages)
            for tool_message in new_messages:
                if isinstance(tool_message, ToolMessage):
                    evidence.append(
                        {
                            "step": task,
                            "tool": tool_message.name or "unknown",
                            "tool_call_id": tool_message.tool_call_id,
                            "content": str(tool_message.content),
                            "status": getattr(tool_message, "status", "success"),
                        }
                    )
        else:
            final_response = await llm.ainvoke(
                [*messages, HumanMessage(content="停止调用工具，基于已获得的证据总结本步骤。")]
            )
            result = str(getattr(final_response, "content", final_response))

        logger.info(f"步骤执行完成，结果长度: {len(result)}")

        # 返回更新：移除已执行的步骤，添加执行历史
        return {
            "plan": plan[1:],  # 移除第一个步骤
            "past_steps": [(task, result)],  # 使用 operator.add 追加
            "evidence": evidence,
        }

    except Exception as e:
        logger.error(f"执行步骤失败: {e}", exc_info=True)
        return {
            "plan": plan[1:],
            "past_steps": [(task, f"执行失败: {str(e)}")],
            "evidence": [],
        }
