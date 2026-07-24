from dataclasses import dataclass
from hashlib import sha256
import json

from devagent.memory.models import Chunk, ChunkType, Document, LineRange

CHUNK_MAX_LINES = 80
CHUNK_OVERLAP_LINES = 10
CHUNK_MAX_CHARS = 4_000


class ChunkingError(ValueError):
    """输入内容无法按声明类型切片。"""


@dataclass(frozen=True)
class ChunkingConfig:
    max_lines: int = CHUNK_MAX_LINES
    overlap_lines: int = CHUNK_OVERLAP_LINES
    max_chars: int = CHUNK_MAX_CHARS

    def __post_init__(self) -> None:
        if isinstance(self.max_lines, bool) or not isinstance(self.max_lines, int):
            raise ValueError("max_lines 必须是整数")
        if self.max_lines < 1:
            raise ValueError("max_lines 必须大于 0")
        if isinstance(self.overlap_lines, bool) or not isinstance(
            self.overlap_lines, int
        ):
            raise ValueError("overlap_lines 必须是整数")
        if self.overlap_lines < 0:
            raise ValueError("overlap_lines 不能小于 0")
        if self.overlap_lines >= self.max_lines:
            raise ValueError("overlap_lines 必须小于 max_lines")
        if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int):
            raise ValueError("max_chars 必须是整数")
        if self.max_chars < 1:
            raise ValueError("max_chars 必须大于 0")


@dataclass(frozen=True)
class _ChunkSpan:
    start_line: int
    end_line: int
    content: str
    segment_index: int


# * 统一入口保证所有内容类型共享同一套定位和稳定 ID 契约。
def chunk_document(
    document: Document,
    *,
    config: ChunkingConfig | None = None,
) -> list[Chunk]:
    resolved_config = config or ChunkingConfig()
    _validate_declared_content(document)
    lines = document.content.splitlines(keepends=True)
    windows = _build_line_windows(lines, config=resolved_config)
    spans = _split_oversized_windows(
        windows,
        config=resolved_config,
        path=document.path,
    )
    return _build_chunks(document, spans)


def _validate_declared_content(document: Document) -> None:
    if document.document_type != ChunkType.CI_JSON:
        return
    try:
        json.loads(document.content)
    except json.JSONDecodeError as exc:
        # ! 原始 CI 内容可能包含凭据，领域错误只暴露安全路径。
        raise ChunkingError(f"CI JSON 文档格式无效: {document.path}") from exc


def _build_line_windows(
    lines: list[str],
    *,
    config: ChunkingConfig,
) -> list[tuple[int, int, str]]:
    """构建 1-based 闭区间行窗口。"""
    windows: list[tuple[int, int, str]] = []
    start_index = 0

    while start_index < len(lines):
        end_index = min(start_index + config.max_lines, len(lines))
        windows.append(
            (
                start_index + 1,
                end_index,
                "".join(lines[start_index:end_index]),
            )
        )
        if end_index == len(lines):
            break
        start_index = end_index - config.overlap_lines

    return windows


def _split_oversized_windows(
    windows: list[tuple[int, int, str]],
    *,
    config: ChunkingConfig,
    path: str,
) -> list[_ChunkSpan]:
    raw_spans: list[tuple[int, int, str]] = []
    for start_line, end_line, content in windows:
        if len(content) <= config.max_chars:
            raw_spans.append((start_line, end_line, content))
            continue
        raw_spans.extend(
            _split_oversized_window(
                start_line=start_line,
                content=content,
                max_chars=config.max_chars,
                path=path,
            )
        )

    return [
        _ChunkSpan(
            start_line=start_line,
            end_line=end_line,
            content=content,
            segment_index=segment_index,
        )
        for segment_index, (start_line, end_line, content) in enumerate(raw_spans)
    ]


def _split_oversized_window(
    *,
    start_line: int,
    content: str,
    max_chars: int,
    path: str,
) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    buffered_lines: list[str] = []
    buffered_chars = 0
    buffered_start_line = start_line

    def flush_buffer() -> None:
        nonlocal buffered_chars, buffered_lines
        if not buffered_lines:
            return
        spans.append(
            (
                buffered_start_line,
                buffered_start_line + len(buffered_lines) - 1,
                "".join(buffered_lines),
            )
        )
        buffered_lines = []
        buffered_chars = 0

    for offset, line in enumerate(content.splitlines(keepends=True)):
        line_number = start_line + offset
        if len(line) > max_chars:
            flush_buffer()
            spans.extend(
                (line_number, line_number, fragment)
                for fragment in _split_long_line(
                    line,
                    max_chars=max_chars,
                    path=path,
                )
            )
            buffered_start_line = line_number + 1
            continue

        if buffered_lines and buffered_chars + len(line) > max_chars:
            flush_buffer()
            buffered_start_line = line_number
        elif not buffered_lines:
            buffered_start_line = line_number

        buffered_lines.append(line)
        buffered_chars += len(line)

    flush_buffer()
    return spans


def _split_long_line(
    line: str,
    *,
    max_chars: int,
    path: str,
) -> list[str]:
    fragments = [
        line[index : index + max_chars] for index in range(0, len(line), max_chars)
    ]
    if len(fragments) > 1 and not fragments[-1].strip():
        trailing_whitespace = fragments.pop()
        room = max_chars - len(trailing_whitespace)
        if room < 1:
            raise ChunkingError(f"文档无法在字符上限内保留空白格式: {path}")
        previous = fragments.pop()
        leading = previous[:-room]
        trailing = previous[-room:] + trailing_whitespace
        if leading:
            fragments.append(leading)
        fragments.append(trailing)

    if any(not fragment.strip() for fragment in fragments):
        # ! 三项契约无法同时满足时返回固定领域错误，不下放 Pydantic 原始异常。
        raise ChunkingError(f"文档无法在字符上限内保留空白格式: {path}")
    return fragments


def _build_chunk_id(document: Document, span: _ChunkSpan) -> str:
    identity = {
        "document_id": document.document_id,
        "source": document.source,
        "path": document.path,
        "start_line": span.start_line,
        "end_line": span.end_line,
        "segment_index": span.segment_index,
        "content": span.content,
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"chk_{sha256(encoded).hexdigest()[:24]}"


def _build_chunks(document: Document, spans: list[_ChunkSpan]) -> list[Chunk]:
    chunk_count = len(spans)
    return [
        Chunk(
            chunk_id=_build_chunk_id(document, span),
            document_id=document.document_id,
            source=document.source,
            path=document.path,
            line_range=LineRange(start=span.start_line, end=span.end_line),
            chunk_type=document.document_type,
            content=span.content,
            metadata={
                **document.metadata,
                "chunk_index": str(index),
                "chunk_count": str(chunk_count),
            },
        )
        for index, span in enumerate(spans, start=1)
    ]
