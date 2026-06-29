from devagent.agent import AgentEvent, AgentEventType
from devagent.event import InMemoryEventStore


def make_event(message: str, event_type: AgentEventType = AgentEventType.RUN_START):
    return AgentEvent(type=event_type, message=message)


def test_append_then_list_returns_event():
    store = InMemoryEventStore()
    event = make_event("开始")

    store.append("task-1", event)

    events = store.list("task-1")
    assert len(events) == 1
    assert events[0].message == "开始"


def test_append_many_keeps_event_order():
    store = InMemoryEventStore()

    store.append_many(
        "task-1",
        [
            make_event("开始", AgentEventType.RUN_START),
            make_event("结束", AgentEventType.RUN_END),
        ],
    )

    events = store.list("task-1")
    assert [event.type for event in events] == [
        AgentEventType.RUN_START,
        AgentEventType.RUN_END,
    ]


def test_list_unknown_task_returns_empty_list():
    store = InMemoryEventStore()

    assert store.list("missing-task") == []


def test_list_returns_copy_to_protect_store_state():
    store = InMemoryEventStore()
    store.append("task-1", make_event("开始"))

    events = store.list("task-1")
    events[0].message = "被外部修改"

    assert store.list("task-1")[0].message == "开始"


def test_append_stores_copy_to_protect_store_state():
    store = InMemoryEventStore()
    event = make_event("开始")

    store.append("task-1", event)
    event.message = "被外部修改"

    assert store.list("task-1")[0].message == "开始"


def test_append_many_stores_copies_to_protect_store_state():
    store = InMemoryEventStore()
    events = [make_event("开始")]

    store.append_many("task-1", events)
    events[0].message = "被外部修改"

    assert store.list("task-1")[0].message == "开始"


def test_clear_removes_events_for_task():
    store = InMemoryEventStore()
    store.append("task-1", make_event("开始"))

    store.clear("task-1")

    assert store.list("task-1") == []
