from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class GuardDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class GuardResult(BaseModel):
    decision: GuardDecision = Field(..., description="决策结果")
    reason: str
    matched_rule: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == GuardDecision.ALLOW


class CommandGuard:
    def validate(
        self, command: list[Any], workspace: str | Path | None = None
    ) -> GuardResult:
        """验证命令和参数是否允许执行"""
        if not command:
            return self._block("命令为空", "empty_command", workspace)
        if any(not isinstance(argument, str) for argument in command):
            return self._block(
                "command 中的每个参数都必须是字符串",
                "invalid_command",
                workspace,
            )

        normalized = self._normalize_command(command)
        executable = Path(normalized[0]).name.lower()
        command_text = self._command_text(normalized).lower()

        if executable == "sudo":
            return self._block("禁止使用 sudo 命令", "sudo", workspace)
        if executable in {"shutdown", "poweroff", "halt"}:
            return self._block("禁止使用关机命令", "shutdown", workspace)
        if executable == "reboot":
            return self._block("禁止使用 reboot 命令", "reboot", workspace)
        if executable.startswith("mkfs"):
            return self._block("禁止使用 mkfs 格式化命令", "mkfs", workspace)
        if executable == "dd" and any(
            argument.startswith(("if=", "of=")) for argument in normalized[1:]
        ):
            return self._block("禁止使用 dd 直接读写设备", "dd_if", workspace)
        if executable == "rm" and self._is_recursive_force_rm(normalized):
            if any(argument == "/" for argument in normalized[1:]):
                return self._block("禁止递归强制删除根目录", "rm_root", workspace)
            if any(argument in {"*", "./*"} for argument in normalized[1:]):
                return self._block("禁止递归强制删除通配路径", "rm_wildcard", workspace)
        if executable == "chmod" and self._is_recursive_chmod_777(normalized):
            return self._block("禁止递归 chmod 777", "chmod_777_recursive", workspace)
        if self._pipes_download_to_shell(command_text):
            return self._block(
                "禁止将 curl 或 wget 下载内容直接管道给 shell",
                "pipe_to_shell",
                workspace,
            )

        return GuardResult(
            decision=GuardDecision.ALLOW,
            reason="命令未命中危险规则",
            metadata=self._metadata(workspace),
        )

    def _block(
        self,
        reason: str,
        matched_rule: str,
        workspace: str | Path | None,
    ) -> GuardResult:
        return GuardResult(
            decision=GuardDecision.BLOCK,
            reason=reason,
            matched_rule=matched_rule,
            metadata=self._metadata(workspace),
        )

    def _metadata(self, workspace: str | Path | None) -> dict[str, str]:
        if workspace is None:
            return {}
        return {"workspace": str(workspace)}

    def _normalize_command(self, command: list[str]) -> list[str]:
        return [argument.strip() for argument in command]

    def _command_text(self, command: list[str]) -> str:
        return " ".join(command)

    def _is_recursive_force_rm(self, command: list[str]) -> bool:
        flags = [argument for argument in command[1:] if argument.startswith("-")]
        has_recursive = any("r" in flag.lower() for flag in flags)
        has_force = any("f" in flag.lower() for flag in flags)
        return has_recursive and has_force

    def _is_recursive_chmod_777(self, command: list[str]) -> bool:
        return any(argument.lower() == "-r" for argument in command[1:]) and any(
            argument == "777" for argument in command[1:]
        )

    def _pipes_download_to_shell(self, command_text: str) -> bool:
        has_downloader = "curl " in command_text or "wget " in command_text
        has_pipe = "|" in command_text
        has_shell = any(shell in command_text for shell in (" sh", " bash"))
        return has_downloader and has_pipe and has_shell
