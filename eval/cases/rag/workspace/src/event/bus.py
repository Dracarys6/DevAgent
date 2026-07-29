class EventBus:
    """Publish each AgentEvent to current subscribers."""

    def publish(self, event: "AgentEvent") -> None:
        for subscriber in self.subscribers:
            subscriber(event)
