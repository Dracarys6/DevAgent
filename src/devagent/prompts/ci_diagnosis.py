import json

from devagent.diagnosis.models import DiagnosisInput, DiagnosisReport


CI_DIAGNOSIS_SYSTEM_PROMPT = """你是一个 CI 诊断 Agent。请严格遵循以下规则：
1. 只依据 INPUT Evidence 中的证据作出事实性陈述。
2. 每个 finding 和 recommendation 必须填写 evidence_ids。
3. evidence_ids 只能引用 INPUT Evidence 中已有的 evidence_id。
4. 不把错误日志、首个异常或相关 diff 自动写成确定根因。
5. 当证据无法支持结论时，status 使用 insufficient_evidence。
6. 将缺少的信息写入 missing_evidence，并用 suggested_tool 说明取证方式。
7. report_id 必须等于 INPUT report_id，scenario 必须是 ci_failure。
8. target 必须等于 INPUT commit_id。
9. evidence 必须原样复制 INPUT evidence，不能增加、删除或改写。
10. summary、finding.statement、recommendation 的 action、rationale、
    verification_steps，以及 missing_evidence 的 needed、reason 必须使用简体中文。
11. 代码标识、文件路径、测试名称、异常名称、evidence 原文、JSON 字段名和枚举值
    保持原文，不要为了中文输出而翻译或改写。
12. 只输出与 DiagnosisReport JSON Schema 匹配的 JSON 对象，不要 Markdown 围栏。"""


def build_ci_diagnosis_prompt(diagnosis_input: DiagnosisInput) -> str:
    """把已标准化的诊断输入构造成紧凑、可解析的用户 Prompt。"""
    payload = diagnosis_input.model_dump(mode="json")
    serialized_input = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    serialized_schema = json.dumps(
        DiagnosisReport.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "CI 诊断输入：\n"
        f"{serialized_input}\n"
        "DiagnosisReport JSON Schema：\n"
        f"{serialized_schema}\n"
        "仅返回 DiagnosisReport JSON 对象；解释性文本使用简体中文。"
    )
