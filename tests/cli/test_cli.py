from pathlib import Path

from devagent.agent.runtime import AgentRuntime
from devagent.cli.cli import build_parser, create_demo_responses, main, render_result
from devagent.llm.mock_client import MockLLMClient
from devagent.tools.builtin import create_builtin_registry


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_demo_result(max_steps: int = 10):
    client = MockLLMClient(responses=create_demo_responses(str(PROJECT_ROOT)))
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=create_builtin_registry(),
        max_steps=max_steps,
    )
    return runtime.run("请分析项目")


def test_build_parser_parses_cli_arguments():
    parser = build_parser()

    args = parser.parse_args(
        [
            "请分析项目",
            "--workspace",
            "/tmp/project",
            "--max-steps",
            "3",
            "--max-tool-calls",
            "5",
            "--show-messages",
        ]
    )

    assert args.question == "请分析项目"
    assert args.workspace == "/tmp/project"
    assert args.max_steps == 3
    assert args.max_tool_calls == 5
    assert args.show_messages is True


def test_create_demo_responses_uses_given_workspace():
    responses = create_demo_responses(str(PROJECT_ROOT))

    first_call = responses[0].tool_calls[0]
    second_call = responses[1].tool_calls[0]

    assert first_call.name == "search_code"
    assert first_call.arguments["workspace"] == str(PROJECT_ROOT)
    assert second_call.name == "read_file"
    assert second_call.arguments["workspace"] == str(PROJECT_ROOT)
    assert second_call.arguments["file_path"] == "src/devagent/tools/models.py"


def test_render_result_outputs_successful_event_summary():
    result = create_demo_result()

    output = render_result(result)

    assert "DevAgent 运行开始" in output
    assert "[step 1] 调用 LLM，当前消息数：2" in output
    assert "[step 1] LLM 返回：tool_calls，工具数：1" in output
    assert "[step 1] 执行工具：search_code" in output
    assert "[step 1] 工具完成：search_code，success=True" in output
    assert "[step 2] 执行工具：read_file" in output
    assert "DevAgent 运行结束：success" in output
    assert "最终回答：" in output
    assert "已完成代码搜索和文件读取，这是最终回答。" in output
    assert "运行失败" not in output


def test_render_result_can_show_debug_message_summary():
    result = create_demo_result()

    output = render_result(result, show_messages=True)

    assert "调试信息：" in output
    assert "messages 数量：7" in output
    assert "LLM 调用轮数：3" in output
    assert "工具调用次数：2" in output


def test_render_result_outputs_failure_summary():
    result = create_demo_result(max_steps=1)

    output = render_result(result)

    assert "运行失败：max_steps_exceeded" in output
    assert "错误信息：Agent 超过最大步数限制: 1" in output
    assert "[step 1] 错误：Agent 超过最大步数限制: 1" in output
    assert "最终回答：" not in output


def test_main_success_returns_zero_and_prints_answer(capsys):
    exit_code = main(["请分析项目", "--workspace", str(PROJECT_ROOT)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "DevAgent 运行开始" in captured.out
    assert "执行工具：search_code" in captured.out
    assert "最终回答：" in captured.out
    assert captured.err == ""


def test_main_failure_returns_one_and_prints_error(capsys):
    exit_code = main(
        [
            "请分析项目",
            "--workspace",
            str(PROJECT_ROOT),
            "--max-steps",
            "1",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "运行失败：max_steps_exceeded" in captured.out
    assert "错误信息：Agent 超过最大步数限制: 1" in captured.out
    assert captured.err == ""


def test_main_can_show_message_debug_summary(capsys):
    exit_code = main(
        [
            "请分析项目",
            "--workspace",
            str(PROJECT_ROOT),
            "--show-messages",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "调试信息：" in captured.out
    assert "messages 数量：7" in captured.out
