from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudget:
    max_chars: int
    recent_block_count: int = 3


def build_compacted_view(messages: list[dict], budget: ContextBudget) -> list[dict]:
    """Build a request-only compacted view without mutating canonical history."""
    if not messages:
        return []

    system_messages = [message for message in messages if message["role"] == "system"]
    original_user_input = next(
        message for message in messages if message["role"] == "user"
    )
    atomic_tool_blocks = collect_atomic_tool_blocks(messages)
    recent_blocks = atomic_tool_blocks[-budget.recent_block_count :]
    return [*system_messages, original_user_input, *recent_blocks]


def collect_atomic_tool_blocks(messages: list[dict]) -> list[dict]:
    """Keep assistant tool calls and their tool results in one indivisible block."""
    return [
        message
        for message in messages
        if message["role"] in {"assistant", "tool"}
    ]
