from collections.abc import Callable
from copy import deepcopy
from uuid import uuid4

from pydantic import BaseModel

from .models import BaseEvent

EventHandler = Callable[[BaseEvent], None]


class EventSubscription(BaseModel):
    subscription_id: str
    task_id: str


class EventSubscriberError(BaseModel):
    subscription_id: str
    error_message: str


class EventBusDeliveryError(RuntimeError):
    def __init__(self, failures: list[EventSubscriberError]) -> None:
        self.failures = failures
        super().__init__(
            f"事件投递失败: {len(failures)} 个订阅者处理失败"
        )


class _Subscriber(BaseModel):
    subscription_id: str
    task_id: str
    handler: EventHandler

    model_config = {"arbitrary_types_allowed": True}


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, _Subscriber] = {}
        self._events_by_task_id: dict[str, list[BaseEvent]] = {}

    def publish(self, event: BaseEvent) -> None:
        stored_event = deepcopy(event)
        self._events_by_task_id.setdefault(event.task_id, []).append(stored_event)

        failures: list[EventSubscriberError] = []
        subscribers = [
            subscriber
            for subscriber in self._subscribers.values()
            if subscriber.task_id == event.task_id
        ]
        for subscriber in subscribers:
            try:
                subscriber.handler(deepcopy(event))
            # ! 订阅者是任意回调，事件总线必须隔离并汇总其所有异常。
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    EventSubscriberError(
                        subscription_id=subscriber.subscription_id,
                        error_message=str(exc),
                    )
                )

        if failures:
            raise EventBusDeliveryError(failures)

    def subscribe(
        self,
        task_id: str,
        handler: EventHandler,
        replay_from_sequence_id: int | None = None,
    ) -> EventSubscription:
        subscription = EventSubscription(
            subscription_id=str(uuid4()),
            task_id=task_id,
        )
        self._subscribers[subscription.subscription_id] = _Subscriber(
            subscription_id=subscription.subscription_id,
            task_id=task_id,
            handler=handler,
        )

        if replay_from_sequence_id is not None:
            for event in self.list_events(
                task_id,
                after_sequence_id=replay_from_sequence_id,
            ):
                handler(event)

        return subscription

    def unsubscribe(self, subscription_id: str) -> bool:
        return self._subscribers.pop(subscription_id, None) is not None

    def list_events(
        self,
        task_id: str,
        after_sequence_id: int | None = None,
    ) -> list[BaseEvent]:
        events = self._events_by_task_id.get(task_id, [])
        return [
            deepcopy(event)
            for event in events
            if after_sequence_id is None or event.sequence_id > after_sequence_id
        ]
