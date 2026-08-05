from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from devagent.storage import SQLiteDatabase


class PublicationStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class GitHubReviewPublication(BaseModel):
    publication_id: str = Field(default_factory=lambda: str(uuid4()))
    delivery_id: str
    repository_full_name: str
    pull_number: int = Field(gt=0)
    head_sha: str
    status: PublicationStatus
    external_comment_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class PublicationClaim(BaseModel):
    publication: GitHubReviewPublication
    acquired: bool


class GitHubReviewPublicationStore(Protocol):
    def claim(
        self,
        *,
        delivery_id: str,
        repository_full_name: str,
        pull_number: int,
        head_sha: str,
    ) -> PublicationClaim: ...

    def mark_completed(
        self,
        publication_id: str,
        external_comment_id: str | None,
    ) -> GitHubReviewPublication: ...

    def mark_failed(self, publication_id: str) -> GitHubReviewPublication: ...


class SQLiteGitHubReviewPublicationStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def claim(
        self,
        *,
        delivery_id: str,
        repository_full_name: str,
        pull_number: int,
        head_sha: str,
    ) -> PublicationClaim:
        now = datetime.now(UTC)
        publication_id = str(uuid4())
        with self._database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO github_review_publications(
                    publication_id, delivery_id, repository_full_name,
                    pull_number, head_sha, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_full_name, pull_number, head_sha) DO NOTHING
                """,
                (
                    publication_id,
                    delivery_id,
                    repository_full_name,
                    pull_number,
                    head_sha,
                    PublicationStatus.PROCESSING.value,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            acquired = cursor.rowcount == 1
            row = connection.execute(
                """
                SELECT * FROM github_review_publications
                WHERE repository_full_name = ? AND pull_number = ? AND head_sha = ?
                """,
                (repository_full_name, pull_number, head_sha),
            ).fetchone()
            if (
                not acquired
                and row is not None
                and row["status"] == PublicationStatus.FAILED.value
            ):
                connection.execute(
                    """
                    UPDATE github_review_publications
                    SET delivery_id = ?, status = ?, error_message = NULL, updated_at = ?
                    WHERE publication_id = ?
                    """,
                    (
                        delivery_id,
                        PublicationStatus.PROCESSING.value,
                        now.isoformat(),
                        row["publication_id"],
                    ),
                )
                acquired = True
                row = connection.execute(
                    "SELECT * FROM github_review_publications WHERE publication_id = ?",
                    (row["publication_id"],),
                ).fetchone()
        return PublicationClaim(publication=_from_row(row), acquired=acquired)

    def mark_completed(
        self,
        publication_id: str,
        external_comment_id: str | None,
    ) -> GitHubReviewPublication:
        return self._update(
            publication_id,
            status=PublicationStatus.COMPLETED,
            external_comment_id=external_comment_id,
            error_message=None,
        )

    def mark_failed(self, publication_id: str) -> GitHubReviewPublication:
        return self._update(
            publication_id,
            status=PublicationStatus.FAILED,
            external_comment_id=None,
            error_message="GitHub review publication failed",
        )

    def get(self, publication_id: str) -> GitHubReviewPublication:
        connection = self._database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM github_review_publications WHERE publication_id = ?",
                (publication_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(f"发布记录不存在: {publication_id}")
        return _from_row(row)

    def _update(
        self,
        publication_id: str,
        *,
        status: PublicationStatus,
        external_comment_id: str | None,
        error_message: str | None,
    ) -> GitHubReviewPublication:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE github_review_publications
                SET status = ?, external_comment_id = ?, error_message = ?, updated_at = ?
                WHERE publication_id = ?
                """,
                (
                    status.value,
                    external_comment_id,
                    error_message,
                    datetime.now(UTC).isoformat(),
                    publication_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"发布记录不存在: {publication_id}")
        return self.get(publication_id)


def _from_row(row: sqlite3.Row) -> GitHubReviewPublication:
    return GitHubReviewPublication.model_validate(dict(row))
