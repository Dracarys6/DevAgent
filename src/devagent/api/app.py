from fastapi import FastAPI
from devagent.config import get_config

config = get_config()

app = FastAPI(title=config.app_name, version=config.version)


@app.get("/health")
def get_health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": config.service_name,
        "version": config.version,
    }
