import json

from devagent.diagnosis import DiagnosisInput


CI_DIAGNOSIS_SYSTEM_PROMPT = """你是一个 CI 诊断 Agent。请严格遵循以下规则：
1. 只依据 INPUT Evidence 中的证据作出事实性陈述。
2. 每个 finding 和 recommendation 必须填写 evidence_ids。
3. evidence_ids 只能引用 INPUT Evidence 中已有的 evidence_id。
4. 不把错误日志、首个异常或相关 diff 自动写成确定根因。
5. 当证据无法支持结论时，status 使用 insufficient_evidence。
6. 将缺少的信息写入 missing_evidence，并用 suggested_tool 说明取证方式。
7. 只输出与 DiagnosisReport 匹配的 JSON 对象，不要 Markdown 围栏。"""


def build_ci_diagnosis_prompt(diagnosis_input: DiagnosisInput) -> str:
    """把已标准化的诊断输入构造成紧凑、可解析的用户 Prompt。"""
    payload = diagnosis_input.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        "CI diagnosis input:\n"
        f"{serialized}\n"
        "Return only a DiagnosisReport JSON object."
    )
