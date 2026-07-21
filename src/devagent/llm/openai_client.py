from __future__ import annotations

import json
from copy import deepcopy
from enum import Enum
from typing import Any

from .base import LLMClient
from .models import LLMResponse, ToolCall
from devagent.tools.models import RiskLevel
from devagent.tools.registry import ToolRegistry


class OpenAIAPIMode(str, Enum):
    """DevAgent 支持的 OpenAI 文本生成接口。"""

    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


OPENAI_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}


def tool_registry_to_openai_tools(
    registry: ToolRegistry,
    allowed_risk_levels: set[RiskLevel] | None = None,
) -> list[dict[str, Any]]:
    """把内部 ToolRegistry schema 转成 Chat Completions tools schema。"""
    tools: list[dict[str, Any]] = []
    for tool in registry.list():
        if (
            allowed_risk_levels is not None
            and tool.risk_level not in allowed_risk_levels
        ):
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


def openai_tools_to_responses_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把 Chat Completions function tools 转成 Responses 扁平格式。"""
    responses_tools: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            raise ValueError("Responses API 当前只支持 DevAgent function tools")
        function = tool.get("function") or {}
        responses_tools.append(
            {
                "type": "function",
                "name": function.get("name", ""),
                "description": function.get("description", ""),
                "parameters": deepcopy(function.get("parameters", {})),
                # * 保持旧 Chat Completions 的宽松参数语义。
                "strict": False,
            }
        )
    return responses_tools


def to_openai_messages(
    internal_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    把 Runtime 内部 messages 转成 Chat Completions 消息格式。

    Runtime 内部保存的 function.arguments 是 dict，Chat Completions 需要 JSON
    字符串。转换只发生在 LLM client 适配层，不污染 AgentRuntime。
    """
    api_messages = deepcopy(internal_messages)

    for message in api_messages:
        # ! metadata 仅供 Runtime 调试，发送前必须移除非标准字段。
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


def to_openai_responses_input(
    internal_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把 Runtime messages 转成 Responses API input items。"""
    input_items: list[dict[str, Any]] = []

    for original_message in internal_messages:
        message = deepcopy(original_message)
        role = message.get("role")
        metadata = message.pop("metadata", {}) or {}

        if role == "assistant" and message.get("tool_calls"):
            # * 精确重放上一轮 output，避免丢失 reasoning item 和 call_id。
            preserved_output = metadata.get("openai_responses_output")
            if preserved_output:
                input_items.extend(deepcopy(preserved_output))
                continue

            content = message.get("content")
            if content:
                input_items.append({"role": "assistant", "content": content})
            for tool_call in message["tool_calls"]:
                function = tool_call.get("function") or {}
                arguments = function.get("arguments", {})
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id", ""),
                        "name": function.get("name", ""),
                        "arguments": arguments,
                    }
                )
            continue

        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": message.get("content", ""),
                }
            )
            continue

        if role in {"system", "developer", "user", "assistant"}:
            input_items.append(
                {
                    "role": role,
                    "content": message.get("content", "") or "",
                }
            )
            continue

        raise ValueError(f"Responses API 不支持的消息角色: {role}")

    return input_items


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


def _serialize_response_output(output: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for item in output:
        if isinstance(item, dict):
            serialized.append(deepcopy(item))
            continue
        model_dump = getattr(item, "model_dump", None)
        if not callable(model_dump):
            raise ValueError("LLM Responses output item 无法序列化")
        serialized.append(model_dump(exclude_none=True))
    return serialized


def parse_openai_message(message: Any) -> LLMResponse:
    """把 Chat Completions message 转成内部 LLMResponse。"""
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
            metadata={
                "provider": "openai_compatible",
                "api_mode": OpenAIAPIMode.CHAT_COMPLETIONS.value,
            },
        )

    return LLMResponse.final_answer(
        _get_value(message, "content", "") or "",
        metadata={
            "provider": "openai_compatible",
            "api_mode": OpenAIAPIMode.CHAT_COMPLETIONS.value,
        },
    )


def parse_openai_response(response: Any) -> LLMResponse:
    """解析 OpenAI-compatible Chat Completions 响应对象。"""
    if isinstance(response, str):
        raise ValueError(
            "LLM 返回了文本而不是 Chat Completions 对象；"
            "请检查 base_url 是否包含正确 API 前缀（通常为 /v1）"
        )

    choices = _get_value(response, "choices") or []
    if not choices:
        response_type = type(response).__name__
        response_object = _get_value(response, "object", "unknown")
        raise ValueError(
            "LLM Chat Completions 响应缺少 choices: "
            f"type={response_type}, object={response_object}"
        )

    first_choice = choices[0]
    message = _get_value(first_choice, "message")
    if message is None:
        raise ValueError("LLM Chat Completions 响应缺少 message")

    parsed = parse_openai_message(message)
    parsed.metadata.update(
        {
            "choice_index": _get_value(first_choice, "index", 0),
            "finish_reason": _get_value(first_choice, "finish_reason"),
            "response_id": _get_value(response, "id"),
            "model": _get_value(response, "model"),
        }
    )
    return parsed


def parse_openai_responses_response(response: Any) -> LLMResponse:
    """解析 OpenAI Responses API 的 output items。"""
    status = _get_value(response, "status")
    if status not in (None, "completed"):
        error = _get_value(response, "error")
        error_message = _get_value(error, "message") if error else None
        detail = f": {error_message}" if error_message else ""
        raise ValueError(f"LLM Responses 响应未完成: status={status}{detail}")

    output = _get_value(response, "output") or []
    if not output:
        response_type = type(response).__name__
        raise ValueError(
            "LLM Responses 响应缺少 output: "
            f"type={response_type}, status={status or 'unknown'}"
        )

    metadata = {
        "provider": "openai",
        "api_mode": OpenAIAPIMode.RESPONSES.value,
        "response_id": _get_value(response, "id"),
        "model": _get_value(response, "model"),
        # * Runtime 会把它保存在 assistant metadata，下一轮按原样重放。
        "openai_responses_output": _serialize_response_output(output),
    }

    parsed_tool_calls: list[ToolCall] = []
    for item in output:
        if _get_value(item, "type") != "function_call":
            continue
        tool_name = _get_value(item, "name", "")
        parsed_tool_calls.append(
            ToolCall(
                id=_get_value(item, "call_id", ""),
                name=tool_name,
                arguments=_parse_tool_arguments(
                    _get_value(item, "arguments", "{}"),
                    tool_name,
                ),
            )
        )

    if parsed_tool_calls:
        return LLMResponse.tool_calls_response(parsed_tool_calls, metadata=metadata)

    output_text = _get_value(response, "output_text")
    if isinstance(output_text, str) and output_text:
        return LLMResponse.final_answer(output_text, metadata=metadata)

    text_parts: list[str] = []
    found_text_part = False
    for item in output:
        if _get_value(item, "type") != "message":
            continue
        for content_part in _get_value(item, "content") or []:
            content_type = _get_value(content_part, "type")
            if content_type == "output_text":
                found_text_part = True
                text_parts.append(_get_value(content_part, "text", "") or "")
            elif content_type == "refusal":
                found_text_part = True
                text_parts.append(_get_value(content_part, "refusal", "") or "")

    if found_text_part:
        return LLMResponse.final_answer("".join(text_parts), metadata=metadata)

    raise ValueError("LLM Responses 响应缺少 output_text 或 function_call")


def _validate_reasoning_effort(
    reasoning_effort: str | None,
    *,
    model: str,
) -> None:
    if reasoning_effort is None:
        return
    if reasoning_effort not in OPENAI_REASONING_EFFORTS:
        allowed = ", ".join(sorted(OPENAI_REASONING_EFFORTS))
        raise ValueError(
            f"不支持的 reasoning effort: {reasoning_effort}；可选值: {allowed}"
        )
    if _is_gpt_5_6(model) and reasoning_effort == "minimal":
        raise ValueError("GPT-5.6 不支持 reasoning effort: minimal")


def _is_gpt_5_6(model: str) -> bool:
    return model == "gpt-5.6" or model.startswith("gpt-5.6-")


def _create_sdk_client(api_key: str, base_url: str | None) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("缺少 openai 依赖，请先安装 openai") from exc

    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


class OpenAICompatibleLLMClient:
    """OpenAI-compatible Chat Completions LLMClient 适配器。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("缺少 LLM API Key")
        if not model:
            raise ValueError("缺少 LLM 模型名称")
        if max_tokens is not None and (
            isinstance(max_tokens, bool) or max_tokens < 1
        ):
            raise ValueError("max_tokens 必须大于或等于 1")
        _validate_reasoning_effort(reasoning_effort, model=model)

        self.model = model
        self.tools = tools or []
        self.temperature = temperature
        self.response_format = deepcopy(response_format)
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.client = _create_sdk_client(api_key, base_url)

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "temperature": self.temperature,
        }
        if self.tools:
            request["tools"] = self.tools
            request["tool_choice"] = "auto"
        if self.response_format is not None:
            request["response_format"] = deepcopy(self.response_format)
        max_tokens = getattr(self, "max_tokens", None)
        if max_tokens is not None:
            request["max_tokens"] = max_tokens

        reasoning_effort = getattr(self, "reasoning_effort", None)
        if _is_gpt_5_6(self.model) and self.tools:
            if reasoning_effort is None:
                reasoning_effort = "none"
            elif reasoning_effort != "none":
                raise ValueError(
                    "GPT-5.6 使用 Chat Completions function tools 时 "
                    "reasoning_effort 必须为 none；"
                    "需要推理工具调用请改用 responses"
                )
        if reasoning_effort is not None:
            request["reasoning_effort"] = reasoning_effort

        response = self.client.chat.completions.create(**request)
        return parse_openai_response(response)


class OpenAIResponsesLLMClient:
    """OpenAI Responses API LLMClient 适配器。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        base_url: str | None = None,
        response_format: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("缺少 LLM API Key")
        if not model:
            raise ValueError("缺少 LLM 模型名称")
        if max_tokens is not None and (
            isinstance(max_tokens, bool) or max_tokens < 1
        ):
            raise ValueError("max_tokens 必须大于或等于 1")
        _validate_reasoning_effort(reasoning_effort, model=model)

        self.model = model
        self.tools = openai_tools_to_responses_tools(tools or [])
        self.response_format = deepcopy(response_format)
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.client = _create_sdk_client(api_key, base_url)

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "input": to_openai_responses_input(messages),
            # ! Runtime 手工重放 output items，不依赖服务端持久化会话。
            "store": False,
        }
        if self.tools:
            request["tools"] = self.tools
            request["tool_choice"] = "auto"
        if self.response_format is not None:
            request["text"] = {"format": deepcopy(self.response_format)}
        if self.reasoning_effort is not None:
            request["reasoning"] = {"effort": self.reasoning_effort}
        max_tokens = getattr(self, "max_tokens", None)
        if max_tokens is not None:
            request["max_output_tokens"] = max_tokens

        response = self.client.responses.create(**request)
        return parse_openai_responses_response(response)


def create_openai_llm_client(
    *,
    api_key: str,
    model: str,
    tools: list[dict[str, Any]] | None = None,
    base_url: str | None = None,
    api_mode: str = OpenAIAPIMode.CHAT_COMPLETIONS.value,
    response_format: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
) -> LLMClient:
    """根据显式 API 模式创建对应的 OpenAI LLMClient。"""
    try:
        parsed_mode = OpenAIAPIMode(api_mode)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in OpenAIAPIMode)
        raise ValueError(
            f"不支持的 OpenAI API 模式: {api_mode}；可选值: {allowed}"
        ) from exc

    client_type = (
        OpenAIResponsesLLMClient
        if parsed_mode == OpenAIAPIMode.RESPONSES
        else OpenAICompatibleLLMClient
    )
    return client_type(
        api_key=api_key,
        model=model,
        tools=tools,
        base_url=base_url,
        response_format=response_format,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )
