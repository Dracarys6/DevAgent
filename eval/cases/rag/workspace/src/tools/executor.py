class ToolExecutor:
    def execute(self, tool: "BaseTool", context: "ToolExecutionContext") -> "ToolResult":
        requires_permission = tool.risk_level in {"HIGH", "CRITICAL"}
        if requires_permission:
            context.permission_manager.request(tool.name, tool.risk_level)
        return tool.invoke(context.arguments)

# High-risk execution delegates policy decisions to PermissionManager.
