import subprocess
from pathlib import Path

import pytest


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


@pytest.fixture
def git_repo_with_commit(tmp_path: Path) -> tuple[Path, str]:
    """创建包含一次可观察代码变更的独立临时 Git 仓库。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "--quiet")
    run_git(repo, "config", "user.email", "devagent@example.test")
    run_git(repo, "config", "user.name", "DevAgent Test")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    run_git(repo, "add", "app.py")
    run_git(repo, "commit", "--quiet", "-m", "initial")
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    run_git(repo, "add", "app.py")
    run_git(repo, "commit", "--quiet", "-m", "change value")
    return repo, run_git(repo, "rev-parse", "HEAD")
