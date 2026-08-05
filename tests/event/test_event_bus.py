import pytest

from devagent.event import (
    BaseEvent,
    EventBusDeliveryError,
    EventType,
    InMemoryEventBus,
    InMemoryStructuredEventStore,
)


def make_event(
    task_id: str = "task_1",
    sequence_id: int = 1,
    message: str = "started",
) -> BaseEvent:
    return BaseEvent(
        task_id=task_id,
        event_type=EventType.AGENT_STARTED,
        sequence_id=sequence_id,
        message=message,
    )


def test_publish_then_list_events_returns_event():
    bus = InMemoryEventBus()
    event = make_event(sequence_id=1)

    bus.publish(event)

    events = bus.list_events("task_1")
    assert len(events) == 1
    assert events[0].sequence_id == 1
    assert events[0].message == "started"


def test_list_events_returns_copy_to_protect_bus_state():
    bus = InMemoryEventBus()
    bus.publish(make_event(sequence_id=1))

    events = bus.list_events("task_1")
    events[0].message = "modified"

    assert bus.list_events("task_1")[0].message == "started"


def test_publish_stores_copy_to_protect_bus_state():
    bus = InMemoryEventBus()
    event = make_event(sequence_id=1)

    bus.publish(event)
    event.message = "modified after publish"

    assert bus.list_events("task_1")[0].message == "started"


def test_single_subscriber_receives_published_event():
    bus = InMemoryEventBus()
    received: list[BaseEvent] = []

    bus.subscribe("task_1", received.append)
    bus.publish(make_event(sequence_id=1))

    assert [event.sequence_id for event in received] == [1]


def test_multiple_subscribers_receive_same_task_event():
    bus = InMemoryEventBus()
    first: list[BaseEvent] = []
    second: list[BaseEvent] = []

    first_subscription = bus.subscribe("task_1", first.append)
    second_subscription = bus.subscribe("task_1", second.append)
    bus.publish(make_event(sequence_id=1))

    assert first_subscription.subscription_id != second_subscription.subscription_id
    assert [event.sequence_id for event in first] == [1]
    assert [event.sequence_id for event in second] == [1]


def test_subscribers_only_receive_matching_task_events():
    bus = InMemoryEventBus()
    task_1_events: list[BaseEvent] = []
    task_2_events: list[BaseEvent] = []

    bus.subscribe("task_1", task_1_events.append)
    bus.subscribe("task_2", task_2_events.append)
    bus.publish(make_event(task_id="task_1", sequence_id=1))

    assert [event.task_id for event in task_1_events] == ["task_1"]
    assert task_2_events == []


def test_unsubscribe_stops_delivery():
    bus = InMemoryEventBus()
    received: list[BaseEvent] = []
    subscription = bus.subscribe("task_1", received.append)

    assert bus.unsubscribe(subscription.subscription_id) is True
    bus.publish(make_event(sequence_id=1))

    assert received == []


def test_unsubscribe_missing_subscription_returns_false():
    bus = InMemoryEventBus()

    assert bus.unsubscribe("missing-subscription") is False


def test_failing_subscriber_does_not_block_other_subscribers():
    bus = InMemoryEventBus()
    received: list[BaseEvent] = []

    def broken_handler(event: BaseEvent) -> None:
        raise RuntimeError("boom")

    broken_subscription = bus.subscribe("task_1", broken_handler)
    bus.subscribe("task_1", received.append)

    with pytest.raises(EventBusDeliveryError) as exc_info:
        bus.publish(make_event(sequence_id=1))

    assert [event.sequence_id for event in received] == [1]
    assert len(exc_info.value.failures) == 1
    assert (
        exc_info.value.failures[0].subscription_id
        == broken_subscription.subscription_id
    )
    assert exc_info.value.failures[0].error_message == "boom"


def test_multiple_failing_subscribers_are_reported_together():
    bus = InMemoryEventBus()

    def first_broken_handler(event: BaseEvent) -> None:
        raise RuntimeError("first")

    def second_broken_handler(event: BaseEvent) -> None:
        raise RuntimeError("second")

    first_subscription = bus.subscribe("task_1", first_broken_handler)
    second_subscription = bus.subscribe("task_1", second_broken_handler)

    with pytest.raises(EventBusDeliveryError) as exc_info:
        bus.publish(make_event(sequence_id=1))

    assert [failure.subscription_id for failure in exc_info.value.failures] == [
        first_subscription.subscription_id,
        second_subscription.subscription_id,
    ]
    assert [failure.error_message for failure in exc_info.value.failures] == [
        "first",
        "second",
    ]


def test_subscribe_with_replay_from_sequence_id_replays_missing_history():
    bus = InMemoryEventBus()
    received: list[BaseEvent] = []
    bus.publish(make_event(sequence_id=1))
    bus.publish(make_event(sequence_id=2))
    bus.publish(make_event(sequence_id=3))

    bus.subscribe("task_1", received.append, replay_from_sequence_id=1)

    assert [event.sequence_id for event in received] == [2, 3]


def test_list_events_after_sequence_id_returns_later_events_only():
    bus = InMemoryEventBus()
    bus.publish(make_event(sequence_id=1))
    bus.publish(make_event(sequence_id=2))
    bus.publish(make_event(sequence_id=3))

    events = bus.list_events("task_1", after_sequence_id=1)

    assert [event.sequence_id for event in events] == [2, 3]


def test_subscriber_receives_copy_to_protect_stored_event():
    bus = InMemoryEventBus()
    received: list[BaseEvent] = []
    bus.subscribe("task_1", received.append)

    bus.publish(make_event(sequence_id=1))
    received[0].message = "modified by subscriber"

    assert bus.list_events("task_1")[0].message == "started"


def test_replayed_events_are_copies_to_protect_stored_event():
    bus = InMemoryEventBus()
    received: list[BaseEvent] = []
    bus.publish(make_event(sequence_id=1))

    bus.subscribe("task_1", received.append, replay_from_sequence_id=0)
    received[0].message = "modified replay"

    assert bus.list_events("task_1")[0].message == "started"


def test_publish_persists_before_delivering_to_subscriber() -> None:
    calls: list[str] = []

    class RecordingStore(InMemoryStructuredEventStore):
        def append(self, event: BaseEvent) -> None:
            calls.append("store")
            super().append(event)

    bus = InMemoryEventBus(RecordingStore())
    bus.subscribe("task_1", lambda _event: calls.append("subscriber"))

    bus.publish(make_event())

    assert calls == ["store", "subscriber"]


def test_store_failure_prevents_subscriber_delivery() -> None:
    received: list[BaseEvent] = []

    class FailingStore(InMemoryStructuredEventStore):
        def append(self, event: BaseEvent) -> None:
            raise RuntimeError("storage unavailable")

    bus = InMemoryEventBus(FailingStore())
    bus.subscribe("task_1", received.append)

    with pytest.raises(RuntimeError, match="storage unavailable"):
        bus.publish(make_event())

    assert received == []


def test_subscriber_failure_does_not_remove_persisted_event() -> None:
    bus = InMemoryEventBus()

    def fail(_event: BaseEvent) -> None:
        raise RuntimeError("subscriber failed")

    bus.subscribe("task_1", fail)

    with pytest.raises(EventBusDeliveryError):
        bus.publish(make_event())

    assert [event.sequence_id for event in bus.list_events("task_1")] == [1]
