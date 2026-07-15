from .ci_diagnosis import build_ci_diagnosis_prompt, CI_DIAGNOSIS_SYSTEM_PROMPT
from .log_diagnosis import build_log_diagnosis_prompt, LOG_DIAGNOSIS_SYSTEM_PROMPT

__all__ = [
    "build_ci_diagnosis_prompt",
    "CI_DIAGNOSIS_SYSTEM_PROMPT",
    "build_log_diagnosis_prompt",
    "LOG_DIAGNOSIS_SYSTEM_PROMPT",
]
