from pydantic import BaseModel


class AppConfig(BaseModel):
    app_name: str = "DevAgent"
    service_name: str = "devagent"
    version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = False


def get_config() -> AppConfig:
    return AppConfig()
