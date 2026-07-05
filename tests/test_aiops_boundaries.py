import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.aiops.executor import executor
from app.agent.aiops.replanner import replanner
from app.config import config
from app.services.aiops_service import AIOpsService

executor_module = importlib.import_module("app.agent.aiops.executor")
replanner_module = importlib.import_module("app.agent.aiops.replanner")


class FakeGraphState:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values


class TimeoutGraph:
    async def astream(self, **_: Any):
        await asyncio.sleep(0.05)
        yield {}

    def get_state(self, _: Any) -> FakeGraphState:
        return FakeGraphState(
            {
                "input": "diagnose timeout",
                "past_steps": [("查询指标", "CPU 持续升高")],
                "evidence": [{"tool": "query_service_metric", "status": "success", "content": "cpu=95"}],
                "alerts": [{"labels": {"service": "video-gateway"}}],
                "data_mode": "mock",
                "response": "",
            }
        )


class EmptyResponseGraph:
    async def astream(self, **_: Any):
        yield {"executor": {"plan": [], "past_steps": [("查询日志", "发现 500 错误")], "evidence": []}}

    def get_state(self, _: Any) -> FakeGraphState:
        return FakeGraphState(
            {
                "input": "diagnose empty response",
                "past_steps": [("查询日志", "发现 500 错误")],
                "evidence": [],
                "alerts": [],
                "data_mode": "real",
                "response": "",
            }
        )


def make_service_with_graph(graph: Any) -> AIOpsService:
    service = AIOpsService()
    service.graph = graph
    return service


def test_aiops_boundary_config_groups_common_and_specific_fields(monkeypatch):
    monkeypatch.setattr(config, "aiops_total_timeout_seconds", 10)
    monkeypatch.setattr(config, "aiops_tool_timeout_seconds", 2)
    monkeypatch.setattr(config, "aiops_fallback_report_enabled", True)
    monkeypatch.setattr(config, "aiops_max_execution_steps", 3)
    monkeypatch.setattr(config, "aiops_replanner_max_replans", 1)
    monkeypatch.setattr(config, "aiops_replanner_max_no_progress_rounds", 4)

    boundary = config.aiops_boundary

    assert boundary.total_timeout_seconds == 10
    assert boundary.tool_timeout_seconds == 2
    assert boundary.fallback_enabled is True
    assert boundary.max_execution_steps == 3
    assert boundary.max_replans == 1
    assert boundary.max_no_progress_rounds == 4


@pytest.mark.asyncio
async def test_execute_total_timeout_returns_fallback_report(monkeypatch):
    monkeypatch.setattr(config, "aiops_total_timeout_seconds", 0.01)
    monkeypatch.setattr(config, "aiops_data_mode", "mock")
    service = make_service_with_graph(TimeoutGraph())

    events = [event async for event in service.execute("diagnose timeout", session_id="timeout")]

    assert events[-2]["type"] == "report"
    assert events[-1]["type"] == "complete"
    assert events[-1]["timeout"] is True
    assert "诊断总耗时超过" in events[-1]["response"]
    assert "CPU 持续升高" in events[-1]["response"]
    assert "Mock 演示报告" in events[-1]["response"]


@pytest.mark.asyncio
async def test_execute_empty_response_returns_fallback_report(monkeypatch):
    monkeypatch.setattr(config, "aiops_total_timeout_seconds", 10)
    monkeypatch.setattr(config, "aiops_data_mode", "real")
    service = make_service_with_graph(EmptyResponseGraph())

    events = [event async for event in service.execute("diagnose empty response", session_id="empty")]

    assert events[-2]["type"] == "report"
    assert events[-2]["message"] == "最终报告缺失，已生成兜底报告"
    assert events[-1]["type"] == "complete"
    assert "兜底说明" in events[-1]["response"]
    assert "发现 500 错误" in events[-1]["response"]


@pytest.mark.asyncio
async def test_executor_tool_call_timeout_records_evidence(monkeypatch):
    class FakeMCPClient:
        async def get_tools(self) -> list[Any]:
            return []

    class FakeToolLLM:
        async def ainvoke(self, _: Any) -> SimpleNamespace:
            return SimpleNamespace(tool_calls=[{"name": "slow_tool"}], content="")

    class FakeChatQwen:
        def __init__(self, **_: Any) -> None:
            pass

        def bind_tools(self, _: list[Any]) -> FakeToolLLM:
            return FakeToolLLM()

    class SlowToolNode:
        def __init__(self, _: list[Any]) -> None:
            pass

        async def ainvoke(self, _: Any) -> dict[str, Any]:
            await asyncio.sleep(0.05)
            return {"messages": []}

    async def fake_get_mcp_client_with_retry() -> FakeMCPClient:
        return FakeMCPClient()

    monkeypatch.setattr(config, "aiops_tool_timeout_seconds", 0.01)
    monkeypatch.setattr(
        executor_module,
        "get_mcp_client_with_retry",
        fake_get_mcp_client_with_retry,
    )
    monkeypatch.setattr(executor_module, "ChatQwen", FakeChatQwen)
    monkeypatch.setattr(executor_module, "ToolNode", SlowToolNode)

    result = await executor(
        {
            "input": "diagnose",
            "plan": ["执行慢工具"],
            "past_steps": [],
            "response": "",
            "alerts": [],
            "alert_source": "api",
            "data_mode": "real",
            "lookback_minutes": 60,
            "evidence": [],
            "replan_attempts": 0,
            "no_progress_rounds": 0,
        }
    )

    assert result["plan"] == []
    assert result["past_steps"][0][0] == "执行慢工具"
    assert "工具调用超时" in result["past_steps"][0][1]
    assert result["evidence"][0]["status"] == "timeout"
    assert result["no_progress_rounds"] == 0


@pytest.mark.asyncio
async def test_replanner_idle_protection_forces_response(monkeypatch):
    async def fake_generate_response(state: dict[str, Any], _: Any) -> dict[str, str]:
        return {"response": f"forced response for {state['input']}"}

    class FakeChatQwen:
        def __init__(self, **_: Any) -> None:
            pass

    monkeypatch.setattr(config, "aiops_replanner_max_replans", 1)
    monkeypatch.setattr(config, "aiops_replanner_max_no_progress_rounds", 2)
    monkeypatch.setattr(replanner_module, "ChatQwen", FakeChatQwen)
    monkeypatch.setattr(replanner_module, "_generate_response", fake_generate_response)

    result = await replanner(
        {
            "input": "diagnose idle",
            "plan": ["下一步"],
            "past_steps": [("第一步", "done")],
            "response": "",
            "alerts": [],
            "alert_source": "api",
            "data_mode": "real",
            "lookback_minutes": 60,
            "evidence": [],
            "replan_attempts": 1,
            "no_progress_rounds": 0,
        }
    )

    assert result == {"response": "forced response for diagnose idle"}
