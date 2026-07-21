import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from devagent.api.app import app

client = TestClient(app)


def create_git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "devagent@example.test"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=repo,
        check=True,
    )
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "实现上传超时修复"],
        cwd=repo,
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, sha


def test_commit_summary_api_returns_git_subject(tmp_path: Path) -> None:
    repo, sha = create_git_repo(tmp_path)

    response = client.post(
        "/api/v1/git/commit-summary",
        json={"ref": "HEAD", "workspace": str(repo)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ref": "HEAD",
        "sha": sha,
        "subject": "实现上传超时修复",
    }


def test_commit_summary_api_returns_400_for_missing_ref(tmp_path: Path) -> None:
    repo, _ = create_git_repo(tmp_path)

    response = client.post(
        "/api/v1/git/commit-summary",
        json={"ref": "missing", "workspace": str(repo)},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "git_commit_summary_error"


def test_commit_summary_api_rejects_invalid_payload() -> None:
    response = client.post(
        "/api/v1/git/commit-summary",
        json={"ref": " HEAD", "workspace": "."},
    )

    assert response.status_code == 422


def test_commit_summary_api_is_exposed_in_openapi() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/api/v1/git/commit-summary"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/GitCommitSummaryRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/GitCommitSummary"}
