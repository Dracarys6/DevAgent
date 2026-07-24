from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


def _validate_relative_path(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value != value.strip():
        raise ValueError("path 不能包含首尾空白")
    path = PurePosixPath(value)
    if value in {"", "."} or path.is_absolute() or ".." in path.parts:
        raise ValueError("path 必须是数据源内的相对路径")
    if "\\" in value:
        raise ValueError("path 必须使用 POSIX 风格路径分隔符 '/'")
    return value


RelativePath = Annotated[
    str,
    BeforeValidator(_validate_relative_path),
    Field(min_length=1, max_length=1000),
]
# * 代码缩进、日志换行和 Markdown 代码块都属于原始证据的一部分。
RawContent = Annotated[str, StringConstraints(strip_whitespace=False)]


class MemoryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,  # * 统一清理普通字符串首尾空白。
        allow_inf_nan=False,  # ! 拒绝无法可靠序列化和比较的 NaN/Inf。
    )


class LineRange(MemoryModel):
    """使用 1-based 闭区间定位原始内容。"""

    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> "LineRange":
        if self.end < self.start:
            raise ValueError("end 不能小于 start")
        return self


class ChunkType(str, Enum):
    CODE = "code"
    MARKDOWN = "markdown"
    LOG = "log"
    CI_JSON = "ci_json"
    TEXT = "text"


def _validate_non_blank_content(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} 不能只包含空白")
    return value


class Document(MemoryModel):
    """一份等待切片的原始本地知识文档。"""

    document_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=200)  # * 数据源名称。
    path: RelativePath
    document_type: ChunkType
    content: RawContent
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return _validate_non_blank_content(value, "content")


class Chunk(MemoryModel):
    """保留原始定位信息的稳定索引切片。"""

    chunk_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=200)
    path: RelativePath
    line_range: LineRange
    chunk_type: ChunkType
    content: RawContent
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return _validate_non_blank_content(value, "content")


class EvidenceSnippet(MemoryModel):
    """一次检索中准备交给 Agent 的有界证据。"""

    chunk_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=200)
    path: RelativePath
    line_range: LineRange
    excerpt: RawContent = Field(max_length=2000)
    score: float = Field(ge=0)
    rank: int = Field(ge=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("excerpt")
    @classmethod
    def validate_excerpt(cls, value: str) -> str:
        return _validate_non_blank_content(value, "excerpt")


class RetrievalResult(MemoryModel):
    """一次查询的已排序检索结果及可评测元数据。"""

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(ge=1, le=50)
    total_candidates: int = Field(ge=0)
    items: list[EvidenceSnippet] = Field(default_factory=list)
    retrieval_ms: float = Field(ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_items(self) -> "RetrievalResult":
        if len(self.items) > self.top_k:
            raise ValueError(f"items 长度不能超过 top_k: {self.top_k}")
        if self.total_candidates < len(self.items):
            raise ValueError("total_candidates 不能小于 items 长度")

        chunk_ids = [item.chunk_id for item in self.items]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("items 中的 chunk_id 不能重复")

        ranks = [item.rank for item in self.items]
        expected_ranks = list(range(1, len(self.items) + 1))
        if ranks != expected_ranks:
            raise ValueError("items 的 rank 必须从 1 开始连续递增")

        scores = [item.score for item in self.items]
        if any(previous < current for previous, current in zip(scores, scores[1:])):
            raise ValueError("items 必须按 score 从高到低排列")
        return self
