"""
通用 Plan-Execute-Replan 状态定义
基于 LangGraph 官方教程实现
"""

import operator
from typing import Annotated, Any, TypedDict


class PlanExecuteState(TypedDict):
    """Plan-Execute-Replan 状态"""

    # 用户输入（任务描述）
    input: str

    # 执行计划（步骤列表）
    plan: list[str]

    # 已执行的步骤历史
    # 使用 operator.add 实现追加式更新（而非覆盖）
    past_steps: Annotated[list[tuple], operator.add]

    # 最终响应/报告
    response: str

    # 本次诊断的告警上下文和数据模式
    alerts: list[dict[str, Any]]
    alert_source: str
    data_mode: str
    lookback_minutes: int

    # Executor 保存的原始工具证据，供最终报告引用
    evidence: Annotated[list[dict[str, Any]], operator.add]

    # 保护边界状态：防止 replanner 反复空转
    replan_attempts: int
    no_progress_rounds: int
