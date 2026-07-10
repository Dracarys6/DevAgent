from dataclasses import dataclass


@dataclass(frozen=True)
class UploadConfig:
    min_timeout_seconds: int = 3
    safety_factor: float = 1.5


def estimate_upload_timeout(size_mb: float, bandwidth_mb_s: float) -> float:
    if size_mb <= 0:
        raise ValueError("size_mb must be greater than 0")
    if bandwidth_mb_s <= 0:
        raise ValueError("bandwidth_mb_s must be greater than 0")
    return size_mb / bandwidth_mb_s


class UploadManager:
    def __init__(self, config: UploadConfig | None = None) -> None:
        self.config = config or UploadConfig()

    def build_upload_timeout(self, size_mb: float, bandwidth_mb_s: float) -> float:
        # Day36 样例里故意保留一个回归：固定返回最小 timeout。
        return self.config.min_timeout_seconds
