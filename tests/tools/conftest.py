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


@pytest.fixture
def git_repo_for_compare(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """创建 base 与 feature 分叉、且覆盖 A/M/D/R 状态的仓库。"""
    repo = tmp_path / "compare-repo"
    repo.mkdir()
    run_git(repo, "init", "--quiet", "-b", "main")
    run_git(repo, "config", "user.email", "devagent@example.test")
    run_git(repo, "config", "user.name", "DevAgent Test")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "delete_me.txt").write_text("delete me\n", encoding="utf-8")
    (repo / "rename me.txt").write_text("rename me\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "--quiet", "-m", "common base")
    common = run_git(repo, "rev-parse", "HEAD")
    run_git(repo, "branch", "feature")

    (repo / "main_only.py").write_text("main_only = True\n", encoding="utf-8")
    run_git(repo, "add", "main_only.py")
    run_git(repo, "commit", "--quiet", "-m", "main only")
    main = run_git(repo, "rev-parse", "HEAD")

    run_git(repo, "switch", "--quiet", "feature")
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    (repo / "added file.py").write_text("added = True\n", encoding="utf-8")
    (repo / "delete_me.txt").unlink()
    run_git(repo, "mv", "rename me.txt", "renamed file.txt")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "--quiet", "-m", "feature changes")
    (repo / "app.py").write_text("value = 2\nfeature = True\n", encoding="utf-8")
    run_git(repo, "add", "app.py")
    run_git(repo, "commit", "--quiet", "-m", "second feature change")
    feature = run_git(repo, "rev-parse", "HEAD")

    return repo, {"common": common, "main": main, "feature": feature}
