from fastapi import FastAPI
from devagent.api.routes import tasks_router, permissions_router, stream_router
from devagent.config import get_config

config = get_config()

app = FastAPI(title=config.app_name, version=config.version)
app.include_router(tasks_router)
app.include_router(permissions_router)
app.include_router(stream_router)


@app.get("/health")
def get_health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": config.service_name,
        "version": config.version,
    }
