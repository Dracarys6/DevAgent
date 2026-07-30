from .models import (
    EvidenceKind,
    Evidence,
    FindingKind,
    Finding,
    Confidence,
    Recommendation,
    MissingEvidence,
    DiagnosisScenario,
    DiagnosisStatus,
    DiagnosisReport,
    DiagnosisReportDraft,
    DiagnosisInput,
    LogDiagnosisInput,
)

__all__ = [
    "EvidenceKind",
    "Evidence",
    "FindingKind",
    "Finding",
    "Confidence",
    "Recommendation",
    "MissingEvidence",
    "DiagnosisScenario",
    "DiagnosisStatus",
    "DiagnosisReport",
    "DiagnosisReportDraft",
    "DiagnosisInput",
    "LogDiagnosisInput",
    "DiagnosisService",
    "DiagnosisServiceError",
    "DiagnosisServiceErrorCode",
    "CIEvidenceCollector",
    "LocalCIEvidenceCollector",
    "ReportIdFactory",
]


def __getattr__(name: str):
    """按需加载服务类型，避免模型与 Prompt 包之间形成循环导入。"""
    service_exports = {
        "DiagnosisService",
        "DiagnosisServiceError",
        "DiagnosisServiceErrorCode",
        "CIEvidenceCollector",
        "LocalCIEvidenceCollector",
        "ReportIdFactory",
    }
    if name not in service_exports:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import service

    return getattr(service, name)
