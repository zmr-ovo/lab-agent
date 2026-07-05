"""配置结构模型。

这些模型用于组织内部配置视图，不作为 API 请求/响应模型使用。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentBoundaryConfig:
    """Agent 通用保护边界。"""

    total_timeout_seconds: float
    tool_timeout_seconds: float
    fallback_enabled: bool


@dataclass(frozen=True)
class ReactBoundaryConfig(AgentBoundaryConfig):
    """ReAct Agent 专属保护边界。"""

    recursion_limit: int
    summary_trigger_tokens: int
    summary_keep_messages: int
    summary_trim_tokens: int


@dataclass(frozen=True)
class AIOpsBoundaryConfig(AgentBoundaryConfig):
    """Plan-Execute-RePlan Agent 专属保护边界。"""

    max_execution_steps: int
    max_replans: int
    max_no_progress_rounds: int
