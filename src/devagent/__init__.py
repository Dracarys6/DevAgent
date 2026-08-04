"""DevAgent - 面向研发效能场景的 AI Agent 后端平台。"""

from devagent.agent import (
    AgentEvent,
    AgentEventType,
    AgentRunResult,
    AgentRunStatus,
    AgentRuntime,
)
from devagent.llm import (
    LLMClient,
    LLMResponse,
    LLMResponseType,
    MockLLMClient,
    OpenAIAPIMode,
    OpenAICompatibleLLMClient,
    OpenAIResponsesLLMClient,
    ToolCall,
    create_openai_llm_client,
    parse_openai_message,
    parse_openai_response,
    parse_openai_responses_response,
    to_openai_messages,
    to_openai_responses_input,
    tool_registry_to_openai_tools,
)
from devagent.tools import (
    BaseTool,
    ErrorCode,
    ReadFileTool,
    RiskLevel,
    RunShellTool,
    SearchCodeTool,
    ToolRegistry,
    ToolResult,
    create_builtin_registry,
)

# * 顶层公共 API 按领域分组，便于调用方理解入口边界。
__all__ = [  # noqa: RUF022
    # Agent
    "AgentEvent",
    "AgentEventType",
    "AgentRunResult",
    "AgentRunStatus",
    "AgentRuntime",
    # LLM
    "LLMClient",
    "LLMResponse",
    "LLMResponseType",
    "MockLLMClient",
    "OpenAIAPIMode",
    "OpenAICompatibleLLMClient",
    "OpenAIResponsesLLMClient",
    "ToolCall",
    "create_openai_llm_client",
    "parse_openai_message",
    "parse_openai_response",
    "parse_openai_responses_response",
    "to_openai_messages",
    "to_openai_responses_input",
    "tool_registry_to_openai_tools",
    # Tools
    "BaseTool",
    "ErrorCode",
    "ReadFileTool",
    "RiskLevel",
    "RunShellTool",
    "SearchCodeTool",
    "ToolRegistry",
    "ToolResult",
    "create_builtin_registry",
]
