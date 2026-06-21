import json
from pathlib import Path

from devagent.agent.runtime import AgentRuntime
from devagent.agent.models import AgentRunStatus
from devagent.llm.mock_client import MockLLMClient
from devagent.llm.models import LLMResponse, ToolCall
from devagent.tools.builtin import create_builtin_registry


def create_runtime(
    responses: list[LLMResponse] | None = None,
    max_steps: int = 10,
    max_tool_calls: int = 20,
    stop_on_repeated_tool_call: bool = True,
) -> tuple[AgentRuntime, MockLLMClient]:
    client = MockLLMClient(responses=responses)
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=create_builtin_registry(),
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
        stop_on_repeated_tool_call=stop_on_repeated_tool_call,
    )
    return runtime, client


def test_runtime_completes_default_mock_workflow():
    runtime, client = create_runtime()

    result = runtime.run("请分析项目中的 ToolRegistry")

    assert result.success is True
    assert result.status == AgentRunStatus.SUCCESS
    assert result.final_answer == "已完成代码搜索和文件读取，这是最终回答。"
    assert result.steps == 3
    assert result.tool_call_count == 2
    assert result.error_message is None
    assert client.call_count == 3
    assert [message["role"] for message in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result.messages == runtime.messages


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


def test_runtime_stops_on_repeated_tool_calls_in_one_response(tmp_path: Path):
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

    result = runtime.run("读取两次")

    assert result.success is False
    assert result.status == AgentRunStatus.REPEATED_TOOL_CALL
    assert [
        message["tool_call_id"]
        for message in runtime.messages
        if message["role"] == "tool"
    ] == ["call_read_1"]


def test_runtime_can_disable_repeated_tool_call_detection(tmp_path: Path):
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
    runtime, _client = create_runtime(
        responses,
        stop_on_repeated_tool_call=False,
    )

    result = runtime.run("读取两次")

    assert result.success is True
    assert result.final_answer == "done"
    assert result.tool_call_count == 2
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

    result = runtime.run("调用未知工具")

    tool_result = json.loads(client.requests[1][-1]["content"])
    assert result.success is True
    assert result.final_answer == "无法执行该工具"
    assert tool_result["success"] is False
    assert tool_result["error_code"] == "TOOL_NOT_FOUND"


def test_runtime_stops_at_max_steps():
    repeated_tool_call = LLMResponse.tool_calls_response(
        [
            ToolCall(
                id="call_repeat",
                name="search_code",
                arguments={"query": "x", "workspace": "."},
            )
        ]
    )
    runtime, client = create_runtime(
        [repeated_tool_call],
        max_steps=2,
        stop_on_repeated_tool_call=False,
    )

    result = runtime.run("不断搜索")

    assert result.success is False
    assert result.status == AgentRunStatus.MAX_STEPS_EXCEEDED
    assert result.final_answer == ""
    assert result.error_message == "Agent 超过最大步数限制: 2"
    assert result.steps == 2
    assert result.tool_call_count == 2
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


def test_runtime_result_messages_are_independent_from_runtime_messages():
    runtime, _client = create_runtime(
        [LLMResponse.final_answer("first")],
    )

    result = runtime.run("first run")
    runtime.messages[0]["content"] = "changed"

    assert result.messages[0]["content"] == "你是一个可以调用工具的代码助手"


def test_runtime_stops_when_max_tool_calls_exceeded(tmp_path: Path):
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
    runtime, _client = create_runtime(
        responses,
        max_tool_calls=1,
        stop_on_repeated_tool_call=False,
    )

    result = runtime.run("最多执行一次工具")

    assert result.success is False
    assert result.status == AgentRunStatus.MAX_TOOL_CALLS_EXCEEDED
    assert result.final_answer == ""
    assert result.tool_call_count == 1
    assert result.error_message == "Agent 超过最大工具调用次数限制: 1"
    assert [
        message["tool_call_id"]
        for message in runtime.messages
        if message["role"] == "tool"
    ] == ["call_read_1"]


def test_runtime_detects_repeated_tool_call_with_normalized_arguments():
    responses = [
        LLMResponse.tool_calls_response(
            [
                ToolCall(
                    id="call_1",
                    name="search_code",
                    arguments={"query": "x", "workspace": "."},
                )
            ]
        ),
        LLMResponse.tool_calls_response(
            [
                ToolCall(
                    id="call_2",
                    name="search_code",
                    arguments={"workspace": ".", "query": "x"},
                )
            ]
        ),
        LLMResponse.final_answer("done"),
    ]
    runtime, _client = create_runtime(responses)

    result = runtime.run("重复搜索")

    assert result.success is False
    assert result.status == AgentRunStatus.REPEATED_TOOL_CALL
    assert result.final_answer == ""
    assert result.tool_call_count == 1
    assert result.error_message == "检测到重复工具调用: search_code"


def test_runtime_returns_llm_error_when_client_raises():
    class FailingLLMClient:
        def chat(self, messages):
            raise RuntimeError("boom")

    runtime = AgentRuntime(
        llm_client=FailingLLMClient(),
        tool_registry=create_builtin_registry(),
    )

    result = runtime.run("触发 LLM 错误")

    assert result.success is False
    assert result.status == AgentRunStatus.LLM_ERROR
    assert result.final_answer == ""
    assert result.steps == 1
    assert result.tool_call_count == 0
    assert result.error_message == "LLM 调用失败: boom"
