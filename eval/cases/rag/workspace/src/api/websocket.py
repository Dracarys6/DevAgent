async def websocket_events(websocket: "WebSocket", event_bus: "EventBus") -> None:
    await websocket.accept()
    subscription = event_bus.subscribe()
    try:
        async for event in subscription:
            await websocket.send_json(event.model_dump(mode="json"))
    finally:
        event_bus.unsubscribe(subscription)

# A disconnect exits iteration and releases the subscription.
