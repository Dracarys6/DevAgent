import json
from copy import deepcopy
from dataclasses import dataclass
from math import isclose
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devagent.memory import RetrievalResult
from devagent.tools.models import ErrorCode, ToolResult

_ALLOWED_ROLES = {"system", "user", "assistant", "tool"}
_TRUNCATION_MARKER = "\n[context truncated]"


class ContextCompressionError(ValueError):
    """消息历史无法在不破坏关键上下文的前提下完成压缩。"""


class ContextModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class ContextPolicy(ContextModel):
    max_chars: int = Field(default=12_000, ge=500, le=200_000, strict=True)
    recent_blocks: int = Field(default=4, ge=1, le=50, strict=True)
    max_tool_result_chars: int = Field(
        default=4_000,
        ge=500,
        le=50_000,
        strict=True,
    )


class ContextCompressionResult(ContextModel):
    messages: list[dict[str, Any]] = Field(min_length=2)
    original_chars: int = Field(ge=1)
    compressed_chars: int = Field(ge=1)
    reduction_rate: float = Field(ge=0, le=1)
    original_message_count: int = Field(ge=2)
    compressed_message_count: int = Field(ge=2)
    dropped_message_count: int = Field(ge=0)
    preserved_evidence_count: int = Field(ge=0)
    truncated_tool_result_count: int = Field(ge=0)
    compressed: bool

    @model_validator(mode="after")
    def validate_compression_result(self) -> "ContextCompressionResult":
        if self.compressed_chars > self.original_chars:
            raise ValueError("compressed_chars 不能大于 original_chars")
        if self.compressed_message_count != len(self.messages):
            raise ValueError("compressed_message_count 必须等于 messages 数量")
        expected_dropped = self.original_message_count - self.compressed_message_count
        if self.dropped_message_count != expected_dropped:
            raise ValueError("dropped_message_count 与消息数量不一致")
        expected_reduction = 1 - self.compressed_chars / self.original_chars
        if not isclose(
            self.reduction_rate,
            expected_reduction,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("reduction_rate 与字符数不一致")
        if self.compressed != (self.compressed_chars < self.original_chars):
            raise ValueError("compressed 必须反映字符数是否减少")
        return self


@dataclass(frozen=True)
class _MessageBlock:
    start_index: int
    messages: tuple[dict[str, Any], ...]
    contains_evidence: bool
    contains_tool_failure: bool
    evidence_count: int
    truncated_tool_result_count: int = 0


class ContextManager:
    """按预算构造确定性的 LLM 消息视图，同时保留工具协议完整性。"""

    def __init__(self, policy: ContextPolicy | None = None) -> None:
        self.policy = policy or ContextPolicy()

    def compress(
        self,
        messages: list[dict[str, Any]],
    ) -> ContextCompressionResult:
        anchors, blocks = _validate_and_group_messages(messages)
        original_chars = count_message_chars(messages)

        if original_chars <= self.policy.max_chars:
            return _build_result(
                original_messages=messages,
                selected_messages=deepcopy(messages),
                original_chars=original_chars,
                evidence_count=sum(block.evidence_count for block in blocks),
                truncated_tool_result_count=0,
            )

        compacted_blocks = [
            _compact_block(block, self.policy.max_tool_result_chars) for block in blocks
        ]
        if count_message_chars(list(anchors)) > self.policy.max_chars:
            raise ContextCompressionError("system prompt 与原始任务超过上下文字符预算")
        if not compacted_blocks:
            raise ContextCompressionError("system prompt 与原始任务超过上下文字符预算")

        selected_indexes: set[int] = set()
        priority_indexes = _priority_indexes(
            compacted_blocks,
            recent_blocks=self.policy.recent_blocks,
        )
        for block_index in priority_indexes:
            candidate_indexes = selected_indexes | {block_index}
            candidate_messages = _assemble_messages(
                anchors,
                compacted_blocks,
                candidate_indexes,
            )
            if count_message_chars(candidate_messages) <= self.policy.max_chars:
                selected_indexes.add(block_index)
                continue
            if block_index == len(compacted_blocks) - 1:
                raise ContextCompressionError("最新消息块压缩后仍超过上下文字符预算")

        selected_messages = _assemble_messages(
            anchors,
            compacted_blocks,
            selected_indexes,
        )
        compressed_chars = count_message_chars(selected_messages)
        if compressed_chars > self.policy.max_chars:
            raise ContextCompressionError("压缩结果超过上下文字符预算")

        selected_blocks = [
            block
            for index, block in enumerate(compacted_blocks)
            if index in selected_indexes
        ]
        return _build_result(
            original_messages=messages,
            selected_messages=selected_messages,
            original_chars=original_chars,
            evidence_count=sum(block.evidence_count for block in selected_blocks),
            truncated_tool_result_count=sum(
                block.truncated_tool_result_count for block in selected_blocks
            ),
        )


def count_message_chars(messages: list[dict[str, Any]]) -> int:
    """使用稳定 JSON 表示统计完整消息请求的字符数。"""
    try:
        encoded = json.dumps(
            messages,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ContextCompressionError("messages 包含无法 JSON 序列化的值") from exc
    return len(encoded)


def _validate_and_group_messages(
    messages: list[dict[str, Any]],
) -> tuple[tuple[dict[str, Any], dict[str, Any]], list[_MessageBlock]]:
    if not isinstance(messages, list) or not messages:
        raise ContextCompressionError("messages 不能为空")
    if any(not isinstance(message, dict) for message in messages):
        raise ContextCompressionError("每条 message 必须是字典")

    roles = [message.get("role") for message in messages]
    if any(role not in _ALLOWED_ROLES for role in roles):
        raise ContextCompressionError("messages 包含不受支持的 role")
    if roles[0] != "system":
        raise ContextCompressionError("第一条 message 必须是 system")
    if len(messages) < 2 or roles[1] != "user":
        raise ContextCompressionError("第二条 message 必须是原始 user task")
    if "system" in roles[1:]:
        raise ContextCompressionError("system message 只能出现在第一条")

    seen_tool_call_ids: set[str] = set()
    blocks: list[_MessageBlock] = []
    index = 2
    while index < len(messages):
        message = messages[index]
        role = message["role"]
        if role == "tool":
            tool_call_id = _safe_identifier(message.get("tool_call_id"))
            raise ContextCompressionError(
                f"tool result 缺少对应 assistant tool_call: {tool_call_id}"
            )

        tool_calls = message.get("tool_calls") if role == "assistant" else None
        if not tool_calls:
            blocks.append(
                _MessageBlock(
                    start_index=index,
                    messages=(message,),
                    contains_evidence=False,
                    contains_tool_failure=False,
                    evidence_count=0,
                )
            )
            index += 1
            continue

        call_ids = _validate_tool_calls(tool_calls, seen_tool_call_ids)
        block_messages = [message]
        result_ids: set[str] = set()
        cursor = index + 1
        while cursor < len(messages) and messages[cursor]["role"] == "tool":
            tool_message = messages[cursor]
            tool_call_id = tool_message.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                raise ContextCompressionError("tool_call_id 必须是非空字符串")
            if tool_call_id not in call_ids:
                raise ContextCompressionError(
                    f"tool result 与当前 assistant tool_call 不匹配: {tool_call_id}"
                )
            if tool_call_id in result_ids:
                raise ContextCompressionError(f"tool result 重复: {tool_call_id}")
            result_ids.add(tool_call_id)
            block_messages.append(tool_message)
            cursor += 1

        missing_ids = sorted(call_ids - result_ids)
        if missing_ids:
            raise ContextCompressionError(
                f"assistant tool_call 缺少结果: {', '.join(missing_ids)}"
            )

        contains_evidence, contains_failure, evidence_count = _inspect_block(
            block_messages
        )
        blocks.append(
            _MessageBlock(
                start_index=index,
                messages=tuple(block_messages),
                contains_evidence=contains_evidence,
                contains_tool_failure=contains_failure,
                evidence_count=evidence_count,
            )
        )
        index = cursor

    return (messages[0], messages[1]), blocks


def _validate_tool_calls(
    tool_calls: object,
    seen_tool_call_ids: set[str],
) -> set[str]:
    if not isinstance(tool_calls, list) or not tool_calls:
        raise ContextCompressionError("assistant.tool_calls 必须是非空列表")

    call_ids: set[str] = set()
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            raise ContextCompressionError("assistant.tool_calls 项必须是字典")
        tool_call_id = tool_call.get("id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise ContextCompressionError("assistant tool_call id 必须是非空字符串")
        if tool_call_id in call_ids or tool_call_id in seen_tool_call_ids:
            raise ContextCompressionError(f"tool_call id 重复: {tool_call_id}")
        call_ids.add(tool_call_id)
        seen_tool_call_ids.add(tool_call_id)
    return call_ids


def _inspect_block(messages: list[dict[str, Any]]) -> tuple[bool, bool, int]:
    contains_evidence = False
    contains_failure = False
    evidence_count = 0
    for message in messages:
        if message.get("role") != "tool":
            continue
        result = _parse_tool_result(message)
        if result is None or not result.success:
            contains_failure = True
            continue
        if message.get("name") != "knowledge_retrieve":
            continue
        try:
            retrieval = RetrievalResult.model_validate_json(result.content)
        except ValidationError:
            contains_failure = True
            continue
        contains_evidence = True
        evidence_count += len(retrieval.items)
    return contains_evidence, contains_failure, evidence_count


def _parse_tool_result(message: dict[str, Any]) -> ToolResult | None:
    content = message.get("content")
    if not isinstance(content, str):
        return None
    try:
        return ToolResult.model_validate_json(content)
    except ValidationError:
        return None


def _compact_block(block: _MessageBlock, max_tool_result_chars: int) -> _MessageBlock:
    compacted_messages: list[dict[str, Any]] = []
    truncated_count = 0
    for message in block.messages:
        copied = deepcopy(message)
        if copied.get("role") == "tool":
            copied, truncated = _compact_tool_message(
                copied,
                max_tool_result_chars=max_tool_result_chars,
            )
            truncated_count += truncated
        compacted_messages.append(copied)

    contains_evidence, contains_failure, evidence_count = _inspect_block(
        compacted_messages
    )
    return _MessageBlock(
        start_index=block.start_index,
        messages=tuple(compacted_messages),
        contains_evidence=contains_evidence,
        contains_tool_failure=contains_failure,
        evidence_count=evidence_count,
        truncated_tool_result_count=truncated_count,
    )


def _compact_tool_message(
    message: dict[str, Any],
    *,
    max_tool_result_chars: int,
) -> tuple[dict[str, Any], int]:
    content = message.get("content")
    result = _parse_tool_result(message)
    if (
        result is not None
        and isinstance(content, str)
        and len(content) <= max_tool_result_chars
    ):
        return message, 0

    if result is None:
        raw_content = content if isinstance(content, str) else repr(content)
        result = ToolResult.fail(
            ErrorCode.TOOL_EXECUTION_ERROR,
            error_message="上下文中的工具结果格式无效",
            content=raw_content,
            metadata={"malformed_original": True},
        )

    compacted_result = (
        _compact_knowledge_result(result, max_tool_result_chars)
        if message.get("name") == "knowledge_retrieve" and result.success
        else _compact_generic_result(result, max_tool_result_chars)
    )
    copied = deepcopy(message)
    copied["content"] = compacted_result.model_dump_json()
    if len(copied["content"]) > max_tool_result_chars:
        raise ContextCompressionError("工具结果无法压缩到单条字符预算")
    return copied, 1


def _compact_generic_result(
    result: ToolResult,
    max_chars: int,
) -> ToolResult:
    metadata = {**result.metadata, "context_truncated": True}
    candidate = result.model_copy(
        deep=True,
        update={"metadata": metadata},
    )
    if len(candidate.model_dump_json()) <= max_chars:
        return candidate

    content = _fit_text_content(candidate, result.content, max_chars)
    return candidate.model_copy(update={"content": content})


def _compact_knowledge_result(
    result: ToolResult,
    max_chars: int,
) -> ToolResult:
    try:
        retrieval = RetrievalResult.model_validate_json(result.content)
    except ValidationError:
        return _compact_generic_result(result, max_chars)

    items = [item.model_copy(deep=True) for item in retrieval.items]
    while items:
        compacted_retrieval = retrieval.model_copy(
            deep=True,
            update={"items": items, "truncated": True},
        )
        candidate = result.model_copy(
            deep=True,
            update={
                "content": compacted_retrieval.model_dump_json(),
                "metadata": {
                    **result.metadata,
                    "context_truncated": True,
                },
            },
        )
        if len(candidate.model_dump_json()) <= max_chars:
            return candidate
        if len(items) > 1:
            items.pop()
            continue

        original_excerpt = items[0].excerpt
        low = 1
        high = len(original_excerpt)
        best: ToolResult | None = None
        while low <= high:
            middle = (low + high) // 2
            excerpt = _truncate_text(original_excerpt, middle)
            compacted_item = items[0].model_copy(update={"excerpt": excerpt})
            compacted_retrieval = retrieval.model_copy(
                deep=True,
                update={"items": [compacted_item], "truncated": True},
            )
            attempt = result.model_copy(
                deep=True,
                update={
                    "content": compacted_retrieval.model_dump_json(),
                    "metadata": {
                        **result.metadata,
                        "context_truncated": True,
                    },
                },
            )
            if len(attempt.model_dump_json()) <= max_chars:
                best = attempt
                low = middle + 1
            else:
                high = middle - 1
        if best is not None:
            return best
        break

    empty_retrieval = retrieval.model_copy(
        deep=True,
        update={"items": [], "truncated": True},
    )
    empty_candidate = result.model_copy(
        deep=True,
        update={
            "content": empty_retrieval.model_dump_json(),
            "metadata": {**result.metadata, "context_truncated": True},
        },
    )
    if len(empty_candidate.model_dump_json()) <= max_chars:
        return empty_candidate
    raise ContextCompressionError("RAG evidence 无法压缩到单条字符预算")


def _fit_text_content(
    result: ToolResult,
    original_content: str,
    max_chars: int,
) -> str:
    low = 0
    high = len(original_content)
    best: str | None = None
    while low <= high:
        middle = (low + high) // 2
        content = _truncate_text(original_content, middle)
        attempt = result.model_copy(update={"content": content})
        if len(attempt.model_dump_json()) <= max_chars:
            best = content
            low = middle + 1
        else:
            high = middle - 1
    if best is None:
        raise ContextCompressionError("工具结果无法压缩到单条字符预算")
    return best


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= len(_TRUNCATION_MARKER):
        return _TRUNCATION_MARKER[:max_chars]
    return value[: max_chars - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER


def _priority_indexes(
    blocks: list[_MessageBlock],
    *,
    recent_blocks: int,
) -> list[int]:
    latest_index = len(blocks) - 1
    priority: list[int] = [latest_index]
    priority.extend(range(latest_index, max(-1, latest_index - recent_blocks), -1))
    priority.extend(
        index
        for index in range(latest_index, -1, -1)
        if blocks[index].contains_evidence
    )
    priority.extend(
        index
        for index in range(latest_index, -1, -1)
        if blocks[index].contains_tool_failure
    )
    priority.extend(range(latest_index, -1, -1))
    return list(dict.fromkeys(priority))


def _assemble_messages(
    anchors: tuple[dict[str, Any], dict[str, Any]],
    blocks: list[_MessageBlock],
    selected_indexes: set[int],
) -> list[dict[str, Any]]:
    selected = [deepcopy(anchors[0]), deepcopy(anchors[1])]
    for index, block in enumerate(blocks):
        if index in selected_indexes:
            selected.extend(deepcopy(list(block.messages)))
    return selected


def _build_result(
    *,
    original_messages: list[dict[str, Any]],
    selected_messages: list[dict[str, Any]],
    original_chars: int,
    evidence_count: int,
    truncated_tool_result_count: int,
) -> ContextCompressionResult:
    compressed_chars = count_message_chars(selected_messages)
    return ContextCompressionResult(
        messages=selected_messages,
        original_chars=original_chars,
        compressed_chars=compressed_chars,
        reduction_rate=1 - compressed_chars / original_chars,
        original_message_count=len(original_messages),
        compressed_message_count=len(selected_messages),
        dropped_message_count=len(original_messages) - len(selected_messages),
        preserved_evidence_count=evidence_count,
        truncated_tool_result_count=truncated_tool_result_count,
        compressed=compressed_chars < original_chars,
    )


def _safe_identifier(value: object) -> str:
    return value if isinstance(value, str) and value else "<unknown>"
