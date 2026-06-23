from types import SimpleNamespace

import pytest

from devagent.llm.models import LLMResponseType
from devagent.llm.openai_client import (
    parse_openai_message,
    parse_openai_response,
    to_openai_messages,
    tool_registry_to_openai_tools,
)
from devagent.tools.builtin import create_builtin_registry
from devagent.tools.models import RiskLevel


def test_tool_registry_to_openai_tools_removes_internal_risk_level():
    tools = tool_registry_to_openai_tools(create_builtin_registry())

    assert tools
    assert all(tool["type"] == "function" for tool in tools)
    assert {tool["function"]["name"] for tool in tools} >= {
        "read_file",
        "search_code",
        "run_shell",
    }
    assert all("description" in tool["function"] for tool in tools)
    assert all("parameters" in tool["function"] for tool in tools)
    assert all("risk_level" not in tool["function"] for tool in tools)


def test_tool_registry_to_openai_tools_can_filter_by_risk_level():
    tools = tool_registry_to_openai_tools(
        create_builtin_registry(),
        allowed_risk_levels={RiskLevel.LOW},
    )

    assert {tool["function"]["name"] for tool in tools} == {
        "read_file",
        "search_code",
    }


def test_to_openai_messages_converts_tool_arguments_to_json_string():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_code",
                        "arguments": {"query": "ToolRegistry", "workspace": "."},
                    },
                }
            ],
            "metadata": {"debug": True},
        }
    ]

    converted = to_openai_messages(messages)

    assert converted[0]["tool_calls"][0]["function"]["arguments"] == (
        '{"query": "ToolRegistry", "workspace": "."}'
    )
    assert "metadata" not in converted[0]
    assert messages[0]["tool_calls"][0]["function"]["arguments"] == {
        "query": "ToolRegistry",
        "workspace": ".",
    }


def test_parse_openai_message_returns_final_answer():
    message = SimpleNamespace(content="hello", tool_calls=None)

    response = parse_openai_message(message)

    assert response.response_type == LLMResponseType.FINAL_ANSWER
    assert response.content == "hello"
    assert response.metadata["provider"] == "openai_compatible"


def test_parse_openai_message_returns_tool_calls():
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="search_code",
                    arguments='{"query": "ToolRegistry", "workspace": "."}',
                ),
            )
        ],
    )

    response = parse_openai_message(message)

    assert response.response_type == LLMResponseType.TOOL_CALLS
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "search_code"
    assert response.tool_calls[0].arguments == {
        "query": "ToolRegistry",
        "workspace": ".",
    }


def test_parse_openai_message_rejects_invalid_tool_arguments_json():
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="search_code",
                    arguments="not json",
                ),
            )
        ],
    )

    with pytest.raises(ValueError, match="工具参数不是合法 JSON"):
        parse_openai_message(message)


def test_parse_openai_response_reads_first_choice_message():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                message=SimpleNamespace(content="done", tool_calls=None),
            )
        ]
    )

    parsed = parse_openai_response(response)

    assert parsed.response_type == LLMResponseType.FINAL_ANSWER
    assert parsed.content == "done"
    assert parsed.metadata["choice_index"] == 0


def test_parse_openai_response_requires_choice_message():
    with pytest.raises(ValueError, match="缺少 choices"):
        parse_openai_response(SimpleNamespace(choices=[]))
