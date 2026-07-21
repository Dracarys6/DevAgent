from fastapi import APIRouter, HTTPException, status

from devagent.api.schemas import GitCommitSummaryRequest
from devagent.tools import (
    GitCommitSummary,
    GitCommitSummaryError,
    get_git_commit_summary,
)

router = APIRouter(prefix="/api/v1/git", tags=["git"])


@router.post("/commit-summary", response_model=GitCommitSummary)
def read_git_commit_summary(request: GitCommitSummaryRequest) -> GitCommitSummary:
    try:
        return get_git_commit_summary(ref=request.ref, workspace=request.workspace)
    except GitCommitSummaryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "git_commit_summary_error", "message": str(exc)},
        ) from exc
