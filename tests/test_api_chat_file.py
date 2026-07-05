import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, UploadFile

import app.api.chat as chat_api
import app.api.file as file_api
from app.models.request import ChatRequest, ClearRequest
from app.models.response import ApiResponse, SessionInfoResponse


@pytest.mark.asyncio
async def test_chat_returns_success_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_query(question: str, session_id: str) -> str:
        assert question == "hello"
        assert session_id == "session-1"
        return "world"

    monkeypatch.setattr(chat_api.rag_agent_service, "query", fake_query)

    response = await chat_api.chat(ChatRequest(id="session-1", question="hello"))

    assert response == {
        "code": 200,
        "message": "success",
        "data": {"success": True, "answer": "world", "errorMessage": None},
    }


@pytest.mark.asyncio
async def test_chat_returns_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_query(question: str, session_id: str) -> str:
        raise RuntimeError(f"{session_id}:{question}")

    monkeypatch.setattr(chat_api.rag_agent_service, "query", fake_query)

    response = await chat_api.chat(ChatRequest(id="session-1", question="hello"))

    assert response["code"] == 500
    assert response["data"]["success"] is False
    assert response["data"]["errorMessage"] == "session-1:hello"


@pytest.mark.asyncio
async def test_clear_session_uses_rag_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_clear_session(session_id: str) -> bool:
        assert session_id == "session-1"
        return True

    monkeypatch.setattr(chat_api.rag_agent_service, "clear_session", fake_clear_session)

    response = await chat_api.clear_session(ClearRequest(session_id="session-1"))

    assert isinstance(response, ApiResponse)
    assert response.status == "success"
    assert response.message == "会话已清空"


@pytest.mark.asyncio
async def test_get_session_info_returns_history(monkeypatch: pytest.MonkeyPatch) -> None:
    history = [{"role": "user", "content": "hello", "timestamp": "2026-07-05T00:00:00"}]

    def fake_get_session_history(session_id: str) -> list[dict[str, str]]:
        assert session_id == "session-1"
        return history

    monkeypatch.setattr(
        chat_api.rag_agent_service,
        "get_session_history",
        fake_get_session_history,
    )

    response = await chat_api.get_session_info("session-1")

    assert isinstance(response, SessionInfoResponse)
    assert response.session_id == "session-1"
    assert response.message_count == 1
    assert response.history == history


@pytest.mark.asyncio
async def test_upload_file_saves_sanitized_file_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    indexed_paths: list[str] = []

    def fake_index_single_file(path: str) -> None:
        indexed_paths.append(path)

    monkeypatch.setattr(file_api, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        file_api.vector_index_service,
        "index_single_file",
        fake_index_single_file,
    )
    upload = UploadFile(filename="hello world.md", file=BytesIO(b"# hello"))

    response = await file_api.upload_file(upload)
    body = json.loads(response.body)

    saved_path = tmp_path / "hello_world.md"
    assert response.status_code == 200
    assert saved_path.read_bytes() == b"# hello"
    assert indexed_paths == [str(saved_path)]
    assert body["data"]["filename"] == "hello_world.md"
    assert body["data"]["size"] == 7


@pytest.mark.asyncio
async def test_upload_file_rejects_unsupported_extension() -> None:
    upload = UploadFile(filename="image.png", file=BytesIO(b"png"))

    with pytest.raises(HTTPException) as exc_info:
        await file_api.upload_file(upload)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_index_directory_returns_vector_index_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeIndexResult:
        success = True

        def to_dict(self) -> dict[str, Any]:
            return {"success": True, "indexed": 2}

    def fake_index_directory(directory_path: str | None) -> FakeIndexResult:
        assert directory_path == "/tmp/uploads"
        return FakeIndexResult()

    monkeypatch.setattr(file_api.vector_index_service, "index_directory", fake_index_directory)

    response = await file_api.index_directory("/tmp/uploads")
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["message"] == "success"
    assert body["data"] == {"success": True, "indexed": 2}
