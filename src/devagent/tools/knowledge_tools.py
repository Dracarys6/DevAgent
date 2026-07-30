import os
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, Field

from devagent.memory import (
    ChunkingError,
    ChunkType,
    Document,
    KeywordRetriever,
    RetrievalError,
    RetrievalResult,
    chunk_document,
)

MAX_KNOWLEDGE_FILES = 1_000
MAX_KNOWLEDGE_FILE_CHARS = 200_000
MAX_TOTAL_KNOWLEDGE_CHARS = 5_000_000

# * 允许索引的文件类型
SUPPORTED_DOCUMENT_TYPES = {
    ".py": ChunkType.CODE,
    ".md": ChunkType.MARKDOWN,
    ".log": ChunkType.LOG,
    ".jsonl": ChunkType.LOG,
    ".json": ChunkType.CI_JSON,
    ".toml": ChunkType.TEXT,
    ".yaml": ChunkType.TEXT,
    ".yml": ChunkType.TEXT,
    ".txt": ChunkType.TEXT,
}

# * 需要跳过的目录
IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


class KnowledgeRetrieveError(ValueError):
    """工作区知识无法被安全发现或检索。"""


def _resolve_workspace(workspace: str | Path) -> Path:
    """将工作区路径解析为绝对路径。"""
    path = Path(workspace).expanduser().resolve()
    if not path.exists():
        raise KnowledgeRetrieveError(f"工作区不存在: {workspace}")
    if not path.is_dir():
        raise KnowledgeRetrieveError(f"工作区不是目录: {workspace}")
    return path


def _discover_knowledge_files(workspace: Path) -> list[Path]:
    """发现工作区中允许索引的文本文件。"""
    root = _resolve_workspace(workspace)
    knowledge_files: list[Path] = []
    # * 跳过 symlink 软链接
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current_root)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in IGNORED_DIRECTORY_NAMES
            and not (current_path / name).is_symlink()
        )
        for file_name in sorted(file_names):
            file_path = Path(current_root) / file_name
            if file_path.suffix.casefold() not in SUPPORTED_DOCUMENT_TYPES:
                continue
            if file_path.is_symlink():
                continue

            resolved_path = file_path.resolve()
            if not resolved_path.is_relative_to(root):
                continue
            if not resolved_path.is_file():
                continue
            knowledge_files.append(resolved_path)
            if len(knowledge_files) > MAX_KNOWLEDGE_FILES:
                raise KnowledgeRetrieveError(
                    f"可索引文件数量不能超过 {MAX_KNOWLEDGE_FILES}"
                )
    return sorted(knowledge_files, key=lambda path: path.relative_to(root).as_posix())


def _build_document_id(relative_path: str) -> str:
    """根据文件相对路径生成唯一的 document_id。"""
    digest = sha256(relative_path.encode("utf-8")).hexdigest()[:24]
    return f"doc_{digest}"


def _load_documents(root: Path, paths: list[Path]) -> list[Document]:
    """将工作区文本文件加载为可切片文档。"""
    total_chars = 0
    resolved_root = _resolve_workspace(root)
    documents: list[Document] = []
    for path in paths:
        if path.is_symlink():
            continue

        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(resolved_root):
            raise KnowledgeRetrieveError("知识文件位于工作区之外")
        if not resolved_path.is_file():
            raise KnowledgeRetrieveError("知识文件不是普通文件")

        relative_path = resolved_path.relative_to(resolved_root).as_posix()
        document_type = SUPPORTED_DOCUMENT_TYPES.get(resolved_path.suffix.casefold())

        # * 跳过调用方直接传入的不支持文件类型。
        if document_type is None:
            continue

        try:
            content = resolved_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeRetrieveError(
                f"知识文件不是 UTF-8 文本: {relative_path}"
            ) from exc
        except PermissionError:
            raise
        except OSError as exc:
            raise KnowledgeRetrieveError(f"无法读取知识文件: {relative_path}") from exc

        if not content.strip():
            continue
        if len(content) > MAX_KNOWLEDGE_FILE_CHARS:
            raise KnowledgeRetrieveError(f"知识文件字符数超过上限 {relative_path}")
        total_chars += len(content)
        if total_chars > MAX_TOTAL_KNOWLEDGE_CHARS:
            raise KnowledgeRetrieveError("知识文件总字符数超过上限")
        documents.append(
            Document(
                document_id=_build_document_id(relative_path),
                source="workspace",
                path=relative_path,
                document_type=document_type,
                content=content,
                metadata={"file_suffix": resolved_path.suffix.casefold()},
            )
        )
    return documents


class KnowledgeRetrieveArgs(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=2000,
        description="需要检索的研发问题或关键词",
    )
    workspace: str = Field(min_length=1, description="需要检索的工作区目录")
    top_k: int = Field(
        default=5, ge=1, le=50, strict=True, description="最多返回的证据片段数量"
    )


def load_workspace_documents(workspace: str | Path) -> list[Document]:
    """按知识检索的安全边界加载工作区文档。"""
    root = _resolve_workspace(workspace)
    return _load_documents(root, _discover_knowledge_files(root))


def knowledge_retrieve(
    query: str, workspace: str | Path, top_k: int = 5
) -> RetrievalResult:
    documents = load_workspace_documents(workspace)
    try:
        chunks = [chunk for document in documents for chunk in chunk_document(document)]
        return KeywordRetriever(chunks).retrieve(query, top_k=top_k)
    except (ChunkingError, RetrievalError) as exc:
        raise KnowledgeRetrieveError(str(exc)) from exc
