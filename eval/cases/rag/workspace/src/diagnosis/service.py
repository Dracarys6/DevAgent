class DiagnosisService:
    def validate_report(self, report: "DiagnosisReport") -> None:
        """Every finding evidence_ids entry must reference known Evidence."""
        known_ids = {item.evidence_id for item in report.evidence}
        for finding in report.findings:
            if not set(finding.evidence_ids) <= known_ids:
                raise ValueError("DiagnosisReport contains an unknown evidence reference")
