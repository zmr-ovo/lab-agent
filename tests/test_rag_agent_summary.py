import asyncio
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

import app.services.rag_agent_service as rag_module
from app.services.rag_agent_service import RagAgentService


class FakeChatQwen:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class FakeSummarizationMiddleware:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def make_service(monkeypatch: pytest.MonkeyPatch) -> RagAgentService:
    monkeypatch.setattr(rag_module, "ChatQwen", FakeChatQwen)
    return RagAgentService(streaming=True)


def test_build_middleware_uses_summary_config(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service(monkeypatch)
    monkeypatch.setattr(rag_module, "SummarizationMiddleware", FakeSummarizationMiddleware)
    monkeypatch.setattr(rag_module.config, "rag_summary_enabled", True)
    monkeypatch.setattr(rag_module.config, "rag_summary_trigger_tokens", 123)
    monkeypatch.setattr(rag_module.config, "rag_summary_keep_messages", 7)
    monkeypatch.setattr(rag_module.config, "rag_summary_trim_tokens", 456)
    monkeypatch.setattr(rag_module.config, "rag_recursion_limit", 9)
    monkeypatch.setattr(rag_module.config, "rag_tool_timeout_seconds", 3)

    middleware = service._build_middleware()

    assert len(middleware) == 3
    assert middleware[0].timeout_seconds == 3
    assert middleware[1].run_limit == 9
    summary_middleware = middleware[2]
    assert isinstance(summary_middleware, FakeSummarizationMiddleware)
    assert summary_middleware.kwargs == {
        "model": service.summary_model,
        "trigger": ("tokens", 123),
        "keep": ("messages", 7),
        "trim_tokens_to_summarize": 456,
    }


def test_build_middleware_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service(monkeypatch)
    monkeypatch.setattr(rag_module.config, "rag_summary_enabled", False)

    middleware = service._build_middleware()

    assert len(middleware) == 2
    assert not any(isinstance(item, FakeSummarizationMiddleware) for item in middleware)


def test_react_boundary_config_groups_common_and_specific_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rag_module.config, "rag_total_timeout_seconds", 10)
    monkeypatch.setattr(rag_module.config, "rag_tool_timeout_seconds", 2)
    monkeypatch.setattr(rag_module.config, "rag_fallback_answer_enabled", True)
    monkeypatch.setattr(rag_module.config, "rag_recursion_limit", 5)
    monkeypatch.setattr(rag_module.config, "rag_summary_trigger_tokens", 100)
    monkeypatch.setattr(rag_module.config, "rag_summary_keep_messages", 4)
    monkeypatch.setattr(rag_module.config, "rag_summary_trim_tokens", 50)

    boundary = rag_module.config.react_boundary

    assert boundary.total_timeout_seconds == 10
    assert boundary.tool_timeout_seconds == 2
    assert boundary.fallback_enabled is True
    assert boundary.recursion_limit == 5
    assert boundary.summary_trigger_tokens == 100
    assert boundary.summary_keep_messages == 4
    assert boundary.summary_trim_tokens == 50


@pytest.mark.asyncio
async def test_initialize_agent_passes_system_prompt_and_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeMcpClient:
        async def get_tools(self) -> list[Any]:
            return ["mcp_tool"]

    async def fake_get_mcp_client() -> FakeMcpClient:
        return FakeMcpClient()

    def fake_create_agent(*args: Any, **kwargs: Any) -> object:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    service = make_service(monkeypatch)
    monkeypatch.setattr(rag_module, "get_mcp_client_with_retry", fake_get_mcp_client)
    monkeypatch.setattr(rag_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(rag_module, "SummarizationMiddleware", FakeSummarizationMiddleware)
    monkeypatch.setattr(rag_module.config, "rag_summary_enabled", True)

    await service._initialize_agent()

    kwargs = captured["kwargs"]
    assert captured["args"] == (service.model,)
    assert kwargs["tools"] == service.tools + ["mcp_tool"]
    assert kwargs["system_prompt"] == service.system_prompt
    assert kwargs["checkpointer"] is service.checkpointer
    assert len(kwargs["middleware"]) == 3
    assert isinstance(kwargs["middleware"][2], FakeSummarizationMiddleware)


@pytest.mark.asyncio
async def test_query_sends_human_message_and_thread_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeAgent:
        async def ainvoke(
            self,
            input: dict[str, Any],
            config: dict[str, Any] | None = None,
        ) -> dict[str, list[HumanMessage]]:
            captured["input"] = input
            captured["config"] = config
            return {"messages": [HumanMessage(content="answer")]}

    async def fake_initialize_agent() -> None:
        return None

    service = make_service(monkeypatch)
    service.agent = FakeAgent()
    monkeypatch.setattr(service, "_initialize_agent", fake_initialize_agent)

    answer = await service.query("hello", session_id="session-1")

    assert answer == "answer"
    messages = captured["input"]["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert not isinstance(messages[0], SystemMessage)
    assert messages[0].content == "hello"
    assert captured["config"] == {
        "configurable": {"thread_id": "session-1"},
        "recursion_limit": rag_module.config.react_boundary.recursion_limit,
    }


@pytest.mark.asyncio
async def test_query_timeout_returns_fallback_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowAgent:
        async def ainvoke(
            self,
            input: dict[str, Any],
            config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            await asyncio.sleep(0.05)
            return {"messages": [HumanMessage(content="too late")]}

    async def fake_initialize_agent() -> None:
        return None

    service = make_service(monkeypatch)
    service.agent = SlowAgent()
    monkeypatch.setattr(service, "_initialize_agent", fake_initialize_agent)
    monkeypatch.setattr(rag_module.config, "rag_total_timeout_seconds", 0.01)
    monkeypatch.setattr(rag_module.config, "rag_fallback_answer_enabled", True)

    answer = await service.query("hello", session_id="session-1")

    assert "本次回答超过总耗时限制" in answer


@pytest.mark.asyncio
async def test_tool_timeout_middleware_returns_error_tool_message() -> None:
    middleware = rag_module.ToolTimeoutMiddleware(timeout_seconds=0.01)

    class FakeRequest:
        tool_call = {"id": "tool-call-1", "name": "slow_tool"}

    async def slow_handler(_: Any) -> Any:
        await asyncio.sleep(0.05)
        return "too late"

    result = await middleware.awrap_tool_call(FakeRequest(), slow_handler)

    assert result.tool_call_id == "tool-call-1"
    assert result.name == "slow_tool"
    assert result.status == "error"
    assert "工具调用超时" in result.content
