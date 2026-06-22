from __future__ import annotations

import argparse
from pathlib import Path

from devagent.agent.models import AgentEvent, AgentEventType, AgentRunResult
from devagent.agent.runtime import AgentRuntime
from devagent.llm.mock_client import MockLLMClient
from devagent.llm.models import LLMResponse, ToolCall
from devagent.tools.builtin import create_builtin_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devagent")
    parser.add_argument("question")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--max-tool-calls", type=int, default=20)
    parser.add_argument("--show-messages", action="store_true")
    return parser


def _format_step(event: AgentEvent) -> str:
    return f"[step {event.step}]"


def _render_event(event: AgentEvent) -> str:
    if event.type == AgentEventType.RUN_START:
        return "DevAgent 运行开始"

    if event.type == AgentEventType.LLM_START:
        message_count = event.metadata.get("message_count", "?")
        return f"{_format_step(event)} 调用 LLM，当前消息数：{message_count}"

    if event.type == AgentEventType.LLM_END:
        response_type = event.metadata.get("response_type", "unknown")
        tool_call_count = event.metadata.get("tool_call_count", 0)
        if response_type == "tool_calls":
            return (
                f"{_format_step(event)} LLM 返回：{response_type}，"
                f"工具数：{tool_call_count}"
            )
        return f"{_format_step(event)} LLM 返回：{response_type}"

    if event.type == AgentEventType.TOOL_START:
        return f"{_format_step(event)} 执行工具：{event.tool_name}"

    if event.type == AgentEventType.TOOL_END:
        success = event.metadata.get("success")
        error_code = event.metadata.get("error_code")
        line = f"{_format_step(event)} 工具完成：{event.tool_name}，success={success}"
        if error_code:
            line += f"，error_code={error_code}"
        return line

    if event.type == AgentEventType.ERROR:
        return f"{_format_step(event)} 错误：{event.message}"

    if event.type == AgentEventType.RUN_END:
        status = event.metadata.get("status")
        if status:
            return f"DevAgent 运行结束：{status}"
        return "DevAgent 运行结束"

    return f"{_format_step(event)} 未知事件：{event.type}，{event.message}"


def render_result(result: AgentRunResult, show_messages: bool = False) -> str:
    lines: list[str] = []

    for event in result.events:
        lines.append(_render_event(event))

    lines.append("")
    if result.success:
        lines.extend(
            [
                "最终回答：",
                result.final_answer or "无最终回答",
            ]
        )
    else:
        lines.extend(
            [
                f"运行失败：{result.status.value}",
                f"错误信息：{result.error_message or '未知错误'}",
            ]
        )

    if show_messages:
        lines.extend(
            [
                "",
                "调试信息：",
                f"messages 数量：{len(result.messages)}",
                f"LLM 调用轮数：{result.steps}",
                f"工具调用次数：{result.tool_call_count}",
            ]
        )

    return "\n".join(lines)


def create_demo_responses(workspace: str) -> list[LLMResponse]:
    workspace_path = Path(workspace).resolve()
    return [
        LLMResponse.tool_calls_response(
            tool_calls=[
                ToolCall(
                    id="call_search_code_001",
                    name="search_code",
                    arguments={
                        "query": "ToolRegistry",
                        "workspace": str(workspace_path),
                        "file_pattern": "*.py",
                    },
                )
            ],
            metadata={"description": "第 1 次模拟调用：返回 search_code tool call"},
        ),
        LLMResponse.tool_calls_response(
            tool_calls=[
                ToolCall(
                    id="call_read_file_001",
                    name="read_file",
                    arguments={
                        "file_path": "src/devagent/tools/models.py",
                        "workspace": str(workspace_path),
                    },
                )
            ],
            metadata={"description": "第 2 次模拟调用：返回 read_file tool call"},
        ),
        LLMResponse.final_answer(
            content="已完成代码搜索和文件读取，这是最终回答。",
            metadata={"description": "第 3 次模拟调用：返回 final answer"},
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        workspace_path = Path(args.workspace).resolve()
        client = MockLLMClient(responses=create_demo_responses(str(workspace_path)))
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=create_builtin_registry(),
            max_steps=args.max_steps,
            max_tool_calls=args.max_tool_calls,
        )
        result = runtime.run(args.question)
        output = render_result(result, args.show_messages)
        print(output)
        return 0 if result.success else 1
    except Exception as exc:
        print(f"DevAgent 运行失败: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
