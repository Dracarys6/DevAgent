import json

import pytest
from pydantic import ValidationError

from devagent.llm.base import LLMClient
from devagent.llm.mock_client import MockLLMClient
from devagent.llm.models import LLMResponse, LLMResponseType, ToolCall


def test_mock_llm_first_response_is_search_code_tool_call():
    client = MockLLMClient()
    response = client.chat(messages=[])
    assert client.call_count == 1
    assert response.response_type == LLMResponseType.TOOL_CALLS

    tool_call = response.tool_calls[0]
    assert tool_call.id == "call_search_code_001"
    assert tool_call.name == "search_code"


def test_mock_llm_implements_llm_client_protocol():
    assert isinstance(MockLLMClient(), LLMClient)


def test_mock_llm_second_response_is_read_file_tool_call():
    client = MockLLMClient()
    client.chat(messages=[])
    response = client.chat(messages=[])
    assert client.call_count == 2
    assert response.response_type == LLMResponseType.TOOL_CALLS

    tool_call = response.tool_calls[0]
    assert tool_call.id == "call_read_file_001"
    assert tool_call.name == "read_file"


def test_mock_llm_third_response_is_final_answer():
    client = MockLLMClient()
    client.chat(messages=[])
    client.chat(messages=[])
    response = client.chat(messages=[])
    assert client.call_count == 3
    assert response.response_type == LLMResponseType.FINAL_ANSWER
    assert response.content == "已完成代码搜索和文件读取，这是最终回答。"


def test_mock_llm_fixed_response_sequence():
    client = MockLLMClient()

    r1 = client.chat(messages=[])
    r2 = client.chat(messages=[])
    r3 = client.chat(messages=[])

    assert r1.response_type == LLMResponseType.TOOL_CALLS
    assert r1.tool_calls[0].name == "search_code"

    assert r2.response_type == LLMResponseType.TOOL_CALLS
    assert r2.tool_calls[0].name == "read_file"

    assert r3.response_type == LLMResponseType.FINAL_ANSWER
    assert r3.content is not None

    assert client.call_count == 3


def test_mock_llm_fourth_call_still_returns_final_answer():
    client = MockLLMClient()

    client.chat(messages=[])
    client.chat(messages=[])
    client.chat(messages=[])
    response = client.chat(messages=[])

    assert client.call_count == 4
    assert response.response_type == LLMResponseType.FINAL_ANSWER
    assert response.tool_calls == []
    assert response.content == "已完成代码搜索和文件读取，这是最终回答。"


def test_llm_response_can_be_serialized():
    client = MockLLMClient()

    response = client.chat(messages=[])

    data = response.model_dump()

    assert data["response_type"] == "tool_calls"
    assert data["tool_calls"][0]["name"] == "search_code"
    assert data["tool_calls"][0]["arguments"]["query"] == "ToolRegistry"


def test_llm_response_can_be_json_serialized():
    response = MockLLMClient().chat(messages=[])

    json.dumps(response.model_dump(mode="json"))


def test_mock_llm_records_deep_copied_requests():
    messages = [{"role": "user", "content": "hello"}]
    client = MockLLMClient()

    client.chat(messages)
    messages[0]["content"] = "changed"

    assert client.requests == [[{"role": "user", "content": "hello"}]]


def test_mock_llm_accepts_custom_response_sequence():
    client = MockLLMClient(
        responses=[
            LLMResponse.final_answer("custom"),
        ]
    )

    first = client.chat([])
    second = client.chat([])

    assert first.content == "custom"
    assert second.content == "custom"
    assert second.metadata["mock_call_index"] == 2


def test_mock_llm_rejects_empty_response_sequence():
    with pytest.raises(ValueError, match="至少需要一个响应"):
        MockLLMClient(responses=[])


def test_tool_call_requires_nonempty_id_and_name():
    with pytest.raises(ValidationError):
        ToolCall(id="", name="", arguments={})


def test_tool_calls_response_requires_tool_call():
    with pytest.raises(ValidationError):
        LLMResponse.tool_calls_response([])


def test_final_answer_cannot_contain_tool_calls():
    with pytest.raises(ValidationError):
        LLMResponse(
            response_type=LLMResponseType.FINAL_ANSWER,
            content="done",
            tool_calls=[ToolCall(id="call_1", name="read_file")],
        )
