from types import SimpleNamespace

import pytest

from devagent.agent import AgentRuntime
from devagent.llm.models import LLMResponseType
from devagent.llm.openai_client import (
    OpenAIAPIMode,
    OpenAICompatibleLLMClient,
    OpenAIResponsesLLMClient,
    create_openai_llm_client,
    openai_tools_to_responses_tools,
    parse_openai_message,
    parse_openai_response,
    parse_openai_responses_response,
    to_openai_messages,
    to_openai_responses_input,
    tool_registry_to_openai_tools,
)
from devagent.tools import ReadFileTool, ToolRegistry
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
        "get_ci_result",
        "git_compare",
        "git_diff",
        "knowledge_retrieve",
        "read_file",
        "search_code",
        "search_log",
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


def test_openai_tools_to_responses_tools_flattens_function_schema():
    chat_tools = tool_registry_to_openai_tools(create_builtin_registry())

    responses_tools = openai_tools_to_responses_tools(chat_tools)

    assert responses_tools
    assert responses_tools[0]["type"] == "function"
    assert "function" not in responses_tools[0]
    assert "name" in responses_tools[0]
    assert "description" in responses_tools[0]
    assert "parameters" in responses_tools[0]
    assert responses_tools[0]["strict"] is False


def test_to_openai_responses_input_converts_tool_history_and_preserves_output():
    preserved_output = [
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "search_code",
            "arguments": '{"query":"ToolRegistry"}',
        },
    ]
    messages = [
        {"role": "system", "content": "你是代码助手"},
        {"role": "user", "content": "搜索代码"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_code",
                        "arguments": {"query": "ToolRegistry"},
                    },
                }
            ],
            "metadata": {"openai_responses_output": preserved_output},
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "search_code",
            "content": '{"success":true}',
        },
    ]

    converted = to_openai_responses_input(messages)

    assert converted[:2] == [
        {"role": "system", "content": "你是代码助手"},
        {"role": "user", "content": "搜索代码"},
    ]
    assert converted[2:4] == preserved_output
    assert converted[4] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"success":true}',
    }
    assert converted[2] is not preserved_output[0]


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
                finish_reason="stop",
                message=SimpleNamespace(content="done", tool_calls=None),
            )
        ]
    )

    parsed = parse_openai_response(response)

    assert parsed.response_type == LLMResponseType.FINAL_ANSWER
    assert parsed.content == "done"
    assert parsed.metadata["choice_index"] == 0
    assert parsed.metadata["finish_reason"] == "stop"


def test_parse_openai_response_requires_choice_message():
    with pytest.raises(ValueError, match="缺少 choices"):
        parse_openai_response(SimpleNamespace(choices=[]))


def test_parse_openai_response_explains_text_response_and_base_url():
    with pytest.raises(ValueError, match="base_url.*?/v1"):
        parse_openai_response("<!doctype html>")


def test_parse_openai_responses_response_returns_final_answer():
    response = SimpleNamespace(
        id="resp_1",
        model="gpt-5.6-luna",
        status="completed",
        output_text="分析完成",
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "分析完成"}],
            }
        ],
    )

    parsed = parse_openai_responses_response(response)

    assert parsed.content == "分析完成"
    assert parsed.metadata["api_mode"] == "responses"
    assert parsed.metadata["response_id"] == "resp_1"
    assert parsed.metadata["model"] == "gpt-5.6-luna"
    assert parsed.metadata["openai_responses_output"] == response.output


def test_parse_openai_responses_response_returns_function_calls():
    response = SimpleNamespace(
        id="resp_2",
        model="gpt-5.6-luna",
        status="completed",
        output_text="",
        output=[
            {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "search_code",
                "arguments": '{"query":"ToolRegistry","workspace":"."}',
            },
        ],
    )

    parsed = parse_openai_responses_response(response)

    assert parsed.tool_calls[0].id == "call_1"
    assert parsed.tool_calls[0].name == "search_code"
    assert parsed.tool_calls[0].arguments == {
        "query": "ToolRegistry",
        "workspace": ".",
    }
    assert parsed.metadata["openai_responses_output"] == response.output


def test_parse_openai_responses_response_rejects_incomplete_response():
    with pytest.raises(ValueError, match="status=incomplete"):
        parse_openai_responses_response(
            SimpleNamespace(status="incomplete", output=[]),
        )


def test_openai_client_forwards_configured_response_format():
    recorded: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        index=0,
                        message=SimpleNamespace(
                            content='{"status":"ok"}',
                            tool_calls=None,
                        ),
                    )
                ]
            )

    client = object.__new__(OpenAICompatibleLLMClient)
    client.model = "test-model"
    client.tools = []
    client.temperature = 0.0
    client.response_format = {"type": "json_object"}
    client.max_tokens = 8192
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    response = client.chat([{"role": "user", "content": "Return JSON"}])

    assert recorded["response_format"] == {"type": "json_object"}
    assert recorded["max_tokens"] == 8192
    assert response.content == '{"status":"ok"}'


def test_openai_client_omits_response_format_by_default():
    recorded: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        index=0,
                        message=SimpleNamespace(
                            content="done",
                            tool_calls=None,
                        ),
                    )
                ]
            )

    client = object.__new__(OpenAICompatibleLLMClient)
    client.model = "test-model"
    client.tools = []
    client.temperature = 0.0
    client.response_format = None
    client.max_tokens = None
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    client.chat([{"role": "user", "content": "hello"}])

    assert "response_format" not in recorded
    assert "max_tokens" not in recorded


def test_chat_client_sets_gpt_5_6_tool_reasoning_to_none():
    recorded: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        index=0,
                        message=SimpleNamespace(content="done", tool_calls=None),
                    )
                ]
            )

    client = object.__new__(OpenAICompatibleLLMClient)
    client.model = "gpt-5.6-luna"
    client.tools = [{"type": "function", "function": {"name": "search_code"}}]
    client.temperature = 0.0
    client.response_format = None
    client.reasoning_effort = None
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    client.chat([{"role": "user", "content": "hello"}])

    assert recorded["reasoning_effort"] == "none"


def test_chat_client_rejects_gpt_5_6_reasoning_tools_combination():
    client = object.__new__(OpenAICompatibleLLMClient)
    client.model = "gpt-5.6-luna"
    client.tools = [{"type": "function", "function": {"name": "search_code"}}]
    client.temperature = 0.0
    client.response_format = None
    client.reasoning_effort = "medium"
    client.client = SimpleNamespace()

    with pytest.raises(ValueError, match="请改用 responses"):
        client.chat([{"role": "user", "content": "hello"}])


def test_responses_client_sends_tools_reasoning_and_json_format():
    recorded: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(
                status="completed",
                output_text='{"status":"ok"}',
                output=[
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": '{"status":"ok"}'}
                        ],
                    }
                ],
            )

    client = object.__new__(OpenAIResponsesLLMClient)
    client.model = "gpt-5.6-luna"
    client.tools = [
        {
            "type": "function",
            "name": "search_code",
            "description": "搜索代码",
            "parameters": {"type": "object"},
            "strict": False,
        }
    ]
    client.response_format = {"type": "json_object"}
    client.reasoning_effort = "medium"
    client.max_tokens = 8192
    client.client = SimpleNamespace(responses=FakeResponses())

    parsed = client.chat([{"role": "user", "content": "分析项目"}])

    assert recorded["input"] == [{"role": "user", "content": "分析项目"}]
    assert recorded["tools"] == client.tools
    assert recorded["tool_choice"] == "auto"
    assert recorded["reasoning"] == {"effort": "medium"}
    assert recorded["text"] == {"format": {"type": "json_object"}}
    assert recorded["max_output_tokens"] == 8192
    assert recorded["store"] is False
    assert "temperature" not in recorded
    assert parsed.content == '{"status":"ok"}'


def test_responses_client_completes_runtime_tool_loop_with_output_replay(tmp_path):
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("alpha\n", encoding="utf-8")
    requests: list[dict[str, object]] = []

    class FakeResponses:
        def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                return SimpleNamespace(
                    id="resp_tool",
                    model="gpt-5.6-luna",
                    status="completed",
                    output_text="",
                    output=[
                        {
                            "type": "reasoning",
                            "id": "rs_1",
                            "encrypted_content": "opaque",
                        },
                        {
                            "type": "function_call",
                            "call_id": "call_read",
                            "name": "read_file",
                            "arguments": (
                                '{"file_path":"sample.txt","workspace":'
                                f'"{tmp_path}"}}'
                            ),
                        },
                    ],
                )
            return SimpleNamespace(
                id="resp_final",
                model="gpt-5.6-luna",
                status="completed",
                output_text="文件内容是 alpha。",
                output=[
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "文件内容是 alpha。"}
                        ],
                    }
                ],
            )

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    client = object.__new__(OpenAIResponsesLLMClient)
    client.model = "gpt-5.6-luna"
    client.tools = openai_tools_to_responses_tools(
        tool_registry_to_openai_tools(registry)
    )
    client.response_format = None
    client.reasoning_effort = "medium"
    client.client = SimpleNamespace(responses=FakeResponses())
    runtime = AgentRuntime(llm_client=client, tool_registry=registry)

    result = runtime.run("读取 sample.txt")

    assert result.success is True
    assert result.final_answer == "文件内容是 alpha。"
    assert len(requests) == 2
    second_input = requests[1]["input"]
    assert any(item.get("type") == "reasoning" for item in second_input)
    assert any(item.get("type") == "function_call" for item in second_input)
    assert any(item.get("type") == "function_call_output" for item in second_input)


def test_create_openai_llm_client_selects_responses(monkeypatch):
    monkeypatch.setattr(
        "devagent.llm.openai_client._create_sdk_client",
        lambda api_key, base_url, timeout_seconds, max_retries: SimpleNamespace(),
    )

    client = create_openai_llm_client(
        api_key="test-key",
        model="gpt-5.6-luna",
        api_mode=OpenAIAPIMode.RESPONSES.value,
    )

    assert isinstance(client, OpenAIResponsesLLMClient)


def test_create_openai_llm_client_rejects_unknown_mode():
    with pytest.raises(ValueError, match="不支持的 OpenAI API 模式"):
        create_openai_llm_client(
            api_key="test-key",
            model="test-model",
            api_mode="unknown",
        )


def test_create_openai_llm_client_rejects_gpt_5_6_minimal_reasoning(monkeypatch):
    monkeypatch.setattr(
        "devagent.llm.openai_client._create_sdk_client",
        lambda api_key, base_url, timeout_seconds, max_retries: SimpleNamespace(),
    )

    with pytest.raises(ValueError, match="GPT-5.6.*minimal"):
        create_openai_llm_client(
            api_key="test-key",
            model="gpt-5.6-luna",
            api_mode="responses",
            reasoning_effort="minimal",
        )


@pytest.mark.parametrize("max_tokens", [0, -1, True])
def test_openai_client_rejects_invalid_max_tokens(max_tokens: int):
    with pytest.raises(ValueError, match="max_tokens"):
        OpenAICompatibleLLMClient(
            api_key="test-key",
            model="test-model",
            max_tokens=max_tokens,
        )


def test_create_openai_llm_client_forwards_transport_limits(monkeypatch):
    captured = {}

    def fake_create_sdk_client(api_key, base_url, timeout_seconds, max_retries):
        captured.update(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return SimpleNamespace()

    monkeypatch.setattr(
        "devagent.llm.openai_client._create_sdk_client",
        fake_create_sdk_client,
    )

    client = create_openai_llm_client(
        api_key="test-key",
        model="test-model",
        timeout_seconds=45.0,
        max_retries=0,
    )

    assert client.timeout_seconds == 45.0
    assert client.max_retries == 0
    assert captured == {"timeout_seconds": 45.0, "max_retries": 0}


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"timeout_seconds": True}, "timeout_seconds"),
        ({"max_retries": -1}, "max_retries"),
        ({"max_retries": True}, "max_retries"),
    ],
)
def test_openai_client_rejects_invalid_transport_limits(kwargs, error):
    with pytest.raises((TypeError, ValueError), match=error):
        OpenAICompatibleLLMClient(
            api_key="test-key",
            model="test-model",
            **kwargs,
        )
