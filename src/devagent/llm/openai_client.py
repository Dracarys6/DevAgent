from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from devagent.llm.models import LLMResponse, ToolCall
from devagent.tools.models import RiskLevel
from devagent.tools.registry import ToolRegistry


def tool_registry_to_openai_tools(
    registry: ToolRegistry,
    allowed_risk_levels: set[RiskLevel] | None = None,
) -> list[dict[str, Any]]:
    """把内部 ToolRegistry schema 转成 OpenAI-compatible tools schema。"""
    tools: list[dict[str, Any]] = []
    for tool in registry.list():
        if allowed_risk_levels is not None and tool.risk_level not in allowed_risk_levels:
            continue
        schema = tool.schema()
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema["description"],
                    "parameters": schema["parameters"],
                },
            }
        )
    return tools


def to_openai_messages(
    internal_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    把 Runtime 内部 messages 转成 OpenAI-compatible API 消息格式。

    Runtime 内部保存的 function.arguments 是 dict，OpenAI 风格 API 需要 JSON
    字符串。这个转换只发生在 LLM client 适配层，不污染 AgentRuntime。
    """
    api_messages = deepcopy(internal_messages)

    for message in api_messages:
        # Runtime 调试用 metadata 不是 Chat Completions 标准消息字段。
        message.pop("metadata", None)

        if message.get("role") != "assistant":
            continue

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            continue

        for tool_call in tool_calls:
            function = tool_call.get("function")
            if not function:
                continue

            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                continue
            function["arguments"] = json.dumps(arguments, ensure_ascii=False)

    return api_messages


def _get_value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _parse_tool_arguments(raw_arguments: Any, tool_name: str) -> dict[str, Any]:
    if raw_arguments in (None, ""):
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str):
        raise ValueError(f"工具参数类型不支持: {tool_name}")

    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(f"工具参数不是合法 JSON: {tool_name}") from exc

    if not isinstance(arguments, dict):
        raise ValueError(f"工具参数必须是 JSON object: {tool_name}")
    return arguments


def parse_openai_message(message: Any) -> LLMResponse:
    """把 OpenAI-compatible message 转成内部 LLMResponse。"""
    tool_calls = _get_value(message, "tool_calls") or []
    if tool_calls:
        parsed_tool_calls: list[ToolCall] = []
        for tool_call in tool_calls:
            function = _get_value(tool_call, "function", {})
            tool_name = _get_value(function, "name", "")
            raw_arguments = _get_value(function, "arguments", "{}")
            parsed_tool_calls.append(
                ToolCall(
                    id=_get_value(tool_call, "id", ""),
                    name=tool_name,
                    arguments=_parse_tool_arguments(raw_arguments, tool_name),
                )
            )

        return LLMResponse.tool_calls_response(
            parsed_tool_calls,
            metadata={"provider": "openai_compatible"},
        )

    return LLMResponse.final_answer(
        _get_value(message, "content", "") or "",
        metadata={"provider": "openai_compatible"},
    )


def parse_openai_response(response: Any) -> LLMResponse:
    """解析 OpenAI-compatible chat.completions.create 的响应对象。"""
    choices = _get_value(response, "choices") or []
    if not choices:
        raise ValueError("LLM 响应缺少 choices")

    first_choice = choices[0]
    message = _get_value(first_choice, "message")
    if message is None:
        raise ValueError("LLM 响应缺少 message")

    parsed = parse_openai_message(message)
    parsed.metadata["choice_index"] = _get_value(first_choice, "index", 0)
    return parsed


class OpenAICompatibleLLMClient:
    """OpenAI Chat Completions 风格的 LLMClient 适配器。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        if not api_key:
            raise ValueError("缺少 LLM API Key")
        if not model:
            raise ValueError("缺少 LLM 模型名称")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("缺少 openai 依赖，请先安装 openai") from exc

        self.model = model
        self.tools = tools or []
        self.temperature = temperature
        self.client = (
            OpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else OpenAI(api_key=api_key)
        )

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "temperature": self.temperature,
        }
        if self.tools:
            request["tools"] = self.tools
            request["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**request)
        return parse_openai_response(response)
