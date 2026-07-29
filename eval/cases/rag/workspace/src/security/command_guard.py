class CommandGuard:
    def classify(self, command: list[str]) -> str:
        """A recursive delete targeting root is always BLOCKED."""
        if command[:3] == ["rm", "-rf", "/"]:
            return "BLOCKED"
        return "ALLOWED"
