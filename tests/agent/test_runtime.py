import json
from pathlib import Path

from devagent.agent.runtime import AgentRuntime
from devagent.llm.mock_client import MockLLMClient
from devagent.llm.models import LLMResponse, ToolCall
from devagent.tools.builtin import create_builtin_registry


def create_runtime(
    responses: list[LLMResponse] | None = None,
    max_steps: int = 10,
) -> tuple[AgentRuntime, MockLLMClient]:
    client = MockLLMClient(responses=responses)
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=create_builtin_registry(),
        max_steps=max_steps,
    )
    return runtime, client


def test_runtime_completes_default_mock_workflow():
    runtime, client = create_runtime()

    answer = runtime.run("请分析项目中的 ToolRegistry")

    assert answer == "已完成代码搜索和文件读取，这是最终回答。"
    assert client.call_count == 3
    assert [message["role"] for message in runtime.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


def test_runtime_executes_tool_calls_in_expected_order():
    runtime, _client = create_runtime()

    runtime.run("请分析项目")

    assistant_calls = [
        message["tool_calls"][0]["function"]["name"]
        for message in runtime.messages
        if message["role"] == "assistant" and "tool_calls" in message
    ]
    tool_results = [
        message["name"] for message in runtime.messages if message["role"] == "tool"
    ]

    assert assistant_calls == ["search_code", "read_file"]
    assert tool_results == ["search_code", "read_file"]


def test_runtime_writes_tool_results_back_to_next_llm_request():
    runtime, client = create_runtime()

    runtime.run("请分析项目")

    second_request = client.requests[1]
    third_request = client.requests[2]

    assert second_request[-1]["role"] == "tool"
    assert second_request[-1]["tool_call_id"] == "call_search_code_001"
    assert third_request[-1]["role"] == "tool"
    assert third_request[-1]["tool_call_id"] == "call_read_file_001"

    first_tool_result = json.loads(second_request[-1]["content"])
    second_tool_result = json.loads(third_request[-1]["content"])
    assert first_tool_result["success"] is True
    assert second_tool_result["success"] is True


def test_runtime_supports_multiple_tool_calls_in_one_response(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")
    responses = [
        LLMResponse.tool_calls_response(
            [
                ToolCall(
                    id="call_read_1",
                    name="read_file",
                    arguments={"file_path": "sample.txt", "workspace": str(tmp_path)},
                ),
                ToolCall(
                    id="call_read_2",
                    name="read_file",
                    arguments={"file_path": "sample.txt", "workspace": str(tmp_path)},
                ),
            ]
        ),
        LLMResponse.final_answer("done"),
    ]
    runtime, _client = create_runtime(responses)

    answer = runtime.run("读取两次")

    assert answer == "done"
    assert [
        message["tool_call_id"]
        for message in runtime.messages
        if message["role"] == "tool"
    ] == ["call_read_1", "call_read_2"]


def test_runtime_writes_unknown_tool_error_back_to_messages():
    responses = [
        LLMResponse.tool_calls_response(
            [ToolCall(id="call_unknown", name="missing_tool", arguments={})]
        ),
        LLMResponse.final_answer("无法执行该工具"),
    ]
    runtime, client = create_runtime(responses)

    answer = runtime.run("调用未知工具")

    tool_result = json.loads(client.requests[1][-1]["content"])
    assert answer == "无法执行该工具"
    assert tool_result["success"] is False
    assert tool_result["error_code"] == "TOOL_NOT_FOUND"


def test_runtime_stops_at_max_steps():
    repeated_tool_call = LLMResponse.tool_calls_response(
        [ToolCall(id="call_repeat", name="search_code", arguments={"query": "x", "workspace": "."})]
    )
    runtime, client = create_runtime([repeated_tool_call], max_steps=2)

    answer = runtime.run("不断搜索")

    assert answer == "Agent 超过最大步数限制: 2"
    assert client.call_count == 2
    assert runtime.messages[-1] == {
        "role": "assistant",
        "content": "Agent 超过最大步数限制: 2",
    }


def test_runtime_saves_independent_message_snapshots():
    runtime, _client = create_runtime(
        [LLMResponse.final_answer("first")],
    )

    runtime.run("first run")
    first_snapshot = runtime.message_history[0]
    runtime.messages[0]["content"] = "changed"

    assert first_snapshot[0]["content"] == "你是一个可以调用工具的代码助手"
