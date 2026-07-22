import json
from typing import Any

from devagent.llm import LLMResponse

from .models import CodeReviewInput, CodeReviewReport, ReviewStatus

INPUT_PREFIX = "代码审查输入：\n"


class DeterministicCodeReviewLLMClient:
    """仅用于显式 smoke：复制输入契约并返回无 finding 的固定报告。"""

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        try:
            user_content = next(
                message["content"]
                for message in reversed(messages)
                if message.get("role") == "user"
                and isinstance(message.get("content"), str)
                and message["content"].startswith(INPUT_PREFIX)
            )
            decoder = json.JSONDecoder()
            payload, _ = decoder.raw_decode(user_content[len(INPUT_PREFIX) :])
            review_input = CodeReviewInput.model_validate(payload)
        except Exception as exc:
            raise ValueError("固定 Review LLM 无法解析代码审查输入") from exc

        report = CodeReviewReport(
            review_id=review_input.review_id,
            base_ref=review_input.base_ref,
            head_ref=review_input.head_ref,
            status=ReviewStatus.REVIEWED,
            summary="固定 smoke 模式已验证证据采集与 GitHub 发布链路。",
            findings=[],
            evidence=review_input.evidence,
            missing_evidence=review_input.missing_evidence,
        )
        return LLMResponse.final_answer(
            report.model_dump_json(),
            metadata={"provider": "deterministic_review_smoke"},
        )
