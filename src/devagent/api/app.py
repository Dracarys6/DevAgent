from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from devagent.api.routes import (
    tasks_router,
    permissions_router,
    stream_router,
    websocket_router,
    traces_router,
    diagnoses_router,
    reviews_router,
    git_commits_router,
    github_webhooks_router,
)
from devagent.config import get_config

config = get_config()

app = FastAPI(title=config.app_name, version=config.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(permissions_router)
app.include_router(stream_router)
app.include_router(websocket_router)
app.include_router(traces_router)
app.include_router(diagnoses_router)
app.include_router(reviews_router)
app.include_router(git_commits_router)
app.include_router(github_webhooks_router)


@app.get("/health")
def get_health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": config.service_name,
        "version": config.version,
    }
