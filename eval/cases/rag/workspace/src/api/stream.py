from asyncio import Queue


async def stream_events(event_bus: "EventBus"):
    queue: Queue["AgentEvent"] = Queue()
    subscription = event_bus.subscribe(queue.put_nowait)
    try:
        while True:
            yield await queue.get()
    finally:
        event_bus.unsubscribe(subscription)

# StreamingResponse consumes this async generator as an SSE response body.
