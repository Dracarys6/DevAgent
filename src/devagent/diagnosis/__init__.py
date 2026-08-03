from .models import (
    Confidence,
    DiagnosisInput,
    DiagnosisReport,
    DiagnosisReportDraft,
    DiagnosisScenario,
    DiagnosisStatus,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    LogDiagnosisInput,
    MissingEvidence,
    Recommendation,
)
from .retrieval_evidence import map_retrieval_evidence

__all__ = [
    "CIEvidenceCollector",
    "Confidence",
    "DiagnosisInput",
    "DiagnosisReport",
    "DiagnosisReportDraft",
    "DiagnosisScenario",
    "DiagnosisService",
    "DiagnosisServiceError",
    "DiagnosisServiceErrorCode",
    "DiagnosisStatus",
    "Evidence",
    "EvidenceKind",
    "Finding",
    "FindingKind",
    "LocalCIEvidenceCollector",
    "LocalLogEvidenceCollector",
    "LogDiagnosisInput",
    "LogEvidenceCollector",
    "MissingEvidence",
    "Recommendation",
    "ReportIdFactory",
    "map_retrieval_evidence",
]


def __getattr__(name: str):
    """按需加载服务类型，避免模型与 Prompt 包之间形成循环导入。"""
    service_exports = {
        "DiagnosisService",
        "DiagnosisServiceError",
        "DiagnosisServiceErrorCode",
        "CIEvidenceCollector",
        "LogEvidenceCollector",
        "LocalCIEvidenceCollector",
        "LocalLogEvidenceCollector",
        "ReportIdFactory",
    }
    if name not in service_exports:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import service

    return getattr(service, name)
