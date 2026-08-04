from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from devagent.event import BaseEvent, InMemoryEventBus


class TraceStep(BaseModel):
    sequence_id: int
    event_id: str
    event_type: str
    message: str
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class TraceSummary(BaseModel):
    task_id: str
    event_count: int
    first_sequence_id: int | None = None
    last_sequence_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    final_status: str | None = None
    final_answer: str | None = None
    llm_call_count: int = 0
    tool_call_count: int = 0
    permission_request_count: int = 0
    error_count: int = 0


class TaskTrace(BaseModel):
    task_id: str
    summary: TraceSummary
    steps: list[TraceStep] = Field(default_factory=list)


BASE_EVENT_FIELDS = [
    "event_id",
    "task_id",
    "session_id",
    "event_type",
    "sequence_id",
    "message",
    "payload",
    "timestamp",
]


class TraceService:
    def __init__(self, event_bus: InMemoryEventBus) -> None:
        self.event_bus = event_bus

    def get_trace(self, task_id: str) -> TaskTrace:
        events = self.event_bus.list_events(task_id)
        steps = sorted(
            [self._event_to_step(event) for event in events],
            key=lambda x: x.sequence_id,
        )
        summary = self._generate_summary(task_id, steps)
        return TaskTrace(task_id=task_id, summary=summary, steps=steps)

    def _event_to_step(self, event: BaseEvent) -> TraceStep:
        data = event.model_dump(mode="json")
        details = {
            key: value for key, value in data.items() if key not in BASE_EVENT_FIELDS
        }
        return TraceStep(
            sequence_id=event.sequence_id,
            event_id=event.event_id,
            event_type=event.event_type.value,
            message=event.message,
            timestamp=event.timestamp,
            payload=event.payload,
            details=details,
        )

    def _generate_summary(self, task_id: str, steps: list[TraceStep]) -> TraceSummary:
        summary = TraceSummary(task_id=task_id, event_count=len(steps))
        if steps:
            summary.first_sequence_id = steps[0].sequence_id
            summary.last_sequence_id = steps[-1].sequence_id
            summary.started_at = steps[0].timestamp

            for step in steps:
                if step.event_type == "agent_finished":
                    summary.finished_at = step.timestamp
                    summary.final_status = step.details.get("status")
                    summary.final_answer = step.details.get("final_answer")
                elif step.event_type == "agent_error":
                    summary.final_status = step.payload.get("status")
                    summary.error_count += 1
                elif step.event_type == "llm_call_finished":
                    summary.llm_call_count += 1
                elif step.event_type == "tool_call_finished":
                    summary.tool_call_count += 1
                elif step.event_type == "tool_call_failed":
                    summary.tool_call_count += 1
                    summary.error_count += 1
                elif step.event_type == "permission_requested":
                    summary.permission_request_count += 1

        return summary
