#!/usr/bin/env bash

set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 检查 Shell 脚本语法"
for script in "${PROJECT_ROOT}"/scripts/*.sh; do
    bash -n "$script"
done

echo "==> 检查 Git diff 格式"
(
    cd "$PROJECT_ROOT"
    git diff --check
)

"${PROJECT_ROOT}/scripts/test.sh" --all

echo
echo "DevAgent 开发检查全部通过。"
