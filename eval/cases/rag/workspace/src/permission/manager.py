class PermissionManager:
    def match_policy(self, tool_name: str, risk_level: str) -> str:
        """Return the first matching policy decision for tool_name and risk_level."""
        return self.policy_store.resolve(tool_name, risk_level).decision
