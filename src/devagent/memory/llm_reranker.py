import json
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devagent.llm import LLMClient, LLMResponseType

from .models import EvidenceSnippet
from .reranker import RerankerError, RerankScore

_SYSTEM_PROMPT = """你是代码与研发证据相关性评分器。
根据 query 判断每个 candidate 对问题的直接回答程度。
只返回以下精确结构的 JSON object，不要使用 Markdown 代码块：
{"scores":[{"chunk_id":"输入中的原始 ID","score":0.0}]}
scores 必须是数组，必须为每个输入 chunk_id 返回且只返回一个 0 到 1 的数字 score。
不要改写 chunk_id，不要生成答案，不要调用工具。"""


class _LLMRerankModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _LLMRerankScore(_LLMRerankModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class _LLMRerankResponse(_LLMRerankModel):
    scores: list[_LLMRerankScore] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "_LLMRerankResponse":
        ids = [item.chunk_id for item in self.scores]
        if len(ids) != len(set(ids)):
            raise ValueError("scores chunk_id 不能重复")
        return self


@dataclass(frozen=True)
class LLMRerankerConfig:
    model_name: str
    max_attempts: int = 2
    max_candidates: int = 10
    max_excerpt_chars: int = 1_200

    def __post_init__(self) -> None:
        if not isinstance(self.model_name, str) or not self.model_name:
            raise ValueError("model_name 不能为空")
        if self.model_name != self.model_name.strip() or len(self.model_name) > 200:
            raise ValueError("model_name 格式无效")
        for name, value, maximum in (
            ("max_attempts", self.max_attempts, 3),
            ("max_candidates", self.max_candidates, 20),
            ("max_excerpt_chars", self.max_excerpt_chars, 2_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} 必须是整数")
            if not 1 <= value <= maximum:
                raise ValueError(f"{name} 必须位于 1 到 {maximum}")


class LLMReranker:
    """使用统一 LLMClient 对有界候选进行结构化相关性评分。"""

    def __init__(self, *, llm_client: LLMClient, config: LLMRerankerConfig) -> None:
        self._llm_client = llm_client
        self.config = config
        self._request_count = 0
        self._repair_count = 0
        self._last_attempt_count = 0
        self._total_latency_ms = 0.0
        self._scored_candidate_count = 0
        self._input_char_count = 0
        self._output_char_count = 0

    @property
    def reranker_name(self) -> str:
        return f"llm:{self.config.model_name}"

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def repair_count(self) -> int:
        return self._repair_count

    @property
    def last_attempt_count(self) -> int:
        return self._last_attempt_count

    @property
    def total_latency_ms(self) -> float:
        return self._total_latency_ms

    @property
    def scored_candidate_count(self) -> int:
        return self._scored_candidate_count

    @property
    def input_char_count(self) -> int:
        return self._input_char_count

    @property
    def output_char_count(self) -> int:
        return self._output_char_count

    @property
    def timeout_seconds(self) -> float | None:
        value = getattr(self._llm_client, "timeout_seconds", None)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def transport_max_retries(self) -> int | None:
        value = getattr(self._llm_client, "max_retries", None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def score(
        self,
        query: str,
        candidates: Sequence[EvidenceSnippet],
    ) -> list[RerankScore]:
        normalized_query = _validate_query(query)
        candidate_snapshot = tuple(candidates)
        _validate_candidates(candidate_snapshot, maximum=self.config.max_candidates)
        self._scored_candidate_count += len(candidate_snapshot)
        expected_ids = {item.chunk_id for item in candidate_snapshot}
        messages: list[dict[str, object]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "query": normalized_query,
                        "candidates": [
                            {
                                "chunk_id": item.chunk_id,
                                "path": item.path,
                                "line_range": item.line_range.model_dump(),
                                "excerpt": item.excerpt[
                                    : self.config.max_excerpt_chars
                                ],
                            }
                            for item in candidate_snapshot
                        ],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]
        self._last_attempt_count = 0
        for attempt in range(1, self.config.max_attempts + 1):
            self._last_attempt_count = attempt
            self._request_count += 1
            self._input_char_count += sum(
                len(content)
                for message in messages
                if isinstance((content := message.get("content")), str)
            )
            started = perf_counter()
            try:
                response = self._llm_client.chat(list(messages))
            except Exception as exc:
                self._total_latency_ms += (perf_counter() - started) * 1000
                raise RerankerError(
                    "LLM reranker 调用失败",
                    code="llm_call_failed",
                ) from exc
            self._total_latency_ms += (perf_counter() - started) * 1000
            if response.content is not None:
                self._output_char_count += len(response.content)

            if response.response_type != LLMResponseType.FINAL_ANSWER:
                raise RerankerError(
                    "LLM reranker 返回了非评分响应",
                    code="unexpected_response",
                )
            try:
                decoded = json.loads(response.content or "")
            except json.JSONDecodeError as exc:
                error_code = "invalid_json"
                parse_error: Exception = exc
            else:
                try:
                    parsed = _LLMRerankResponse.model_validate(decoded)
                except ValidationError as exc:
                    error_code = "schema_mismatch"
                    parse_error = exc
                else:
                    actual_ids = {item.chunk_id for item in parsed.scores}
                    if actual_ids == expected_ids:
                        return [
                            RerankScore(chunk_id=item.chunk_id, score=item.score)
                            for item in parsed.scores
                        ]
                    error_code = "candidate_id_mismatch"
                    parse_error = ValueError("score chunk_id 集合与候选不一致")

            if attempt >= self.config.max_attempts:
                raise RerankerError(
                    "LLM reranker 输出不符合契约",
                    code=error_code,
                ) from parse_error
            self._repair_count += 1
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过评分契约校验。只返回精确结构："
                        '{"scores":[{"chunk_id":"输入中的原始 ID",'
                        '"score":0.0}]}。scores 必须覆盖每个输入 chunk_id，'
                        "不能增加、遗漏或改写 ID，score 必须是 0 到 1 的数字。"
                    ),
                }
            )

        raise AssertionError("LLM reranker 重试循环不应执行到这里")


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise TypeError("query 必须是字符串")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query 不能为空")
    if len(normalized) > 2_000:
        raise ValueError("query 长度不能超过 2000 字符")
    return normalized


def _validate_candidates(
    candidates: Sequence[EvidenceSnippet],
    *,
    maximum: int,
) -> None:
    if not candidates:
        raise RerankerError("rerank candidates 不能为空", code="invalid_candidates")
    if len(candidates) > maximum:
        raise RerankerError(
            "rerank candidates 超过上限",
            code="invalid_candidates",
        )
    ids = [item.chunk_id for item in candidates]
    if len(ids) != len(set(ids)):
        raise RerankerError(
            "rerank candidates chunk_id 重复",
            code="invalid_candidates",
        )
