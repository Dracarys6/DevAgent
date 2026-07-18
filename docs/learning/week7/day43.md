# Day 43：定义代码审查领域模型与风险分类

## 今天目标

第 6 周已经完成 CI 失败诊断闭环：工具负责取证，`DiagnosisService` 负责调用模型，`DiagnosisReport` 负责拒绝无依据或结构错误的输出。第 7 周把同样的“证据驱动”原则迁移到代码合入审查场景，但审查与诊断回答的问题不同：

```text
诊断：已经发生了什么失败，为什么失败？
审查：base_ref...head_ref 的待合入变更引入了什么可行动风险？
```

Day43 先建立代码审查领域契约，使后续 Git 变更采集、Prompt、Service、API、GitHub adapter 和 Evaluation 都围绕同一组类型协作。

目标产物：

```text
src/devagent/review/__init__.py
src/devagent/review/models.py
tests/review/test_review_models.py
```

核心类型：

```text
CodeReviewInput
CodeReviewReport
ReviewFinding
ReviewSeverity
ReviewCategory
ReviewStatus
ReviewLineSide
```

今日验收核心：

```text
1. 每条 finding 都有唯一 ID、风险分类和严重级别
2. 每条 finding 都能定位到仓库相对文件、diff 侧和行号
3. 每条 finding 都引用已存在的 evidence_ids
4. 每条 finding 都有可执行的修改建议和验证步骤
5. 悬空证据引用、重复 ID、非法路径和非法行号无法通过 Pydantic
6. “审查完成且没有问题”与“证据不足”使用不同状态表达
```

Day43 对应 `plan.md` 的“代码合入审查复用 Evidence，但不复用 DiagnosisReport”边界，以及 `learning_plan.md` 第 7 周第一天的领域模型任务。

## 背景与上下文

### 从诊断报告到审查报告

Day42 的 `DiagnosisReport` 适合表达：

```text
症状
根因
相关变化
环境问题
```

代码审查需要表达：

```text
这次变更引入的风险类型
风险影响有多严重
问题位于哪个变更文件和哪一行
哪些 diff / 代码上下文支持该判断
开发者应该怎样修改
修改后怎样验证
```

如果直接复用 `DiagnosisReport`，会出现语义错位：

```text
FindingKind.ROOT_CAUSE 不能表达 compatibility 或 test_gap
DiagnosisStatus.DIAGNOSED 不能表达“审查完成且未发现问题”
诊断 Finding 没有文件、行号和修改建议
```

因此代码审查复用通用的 `Evidence` 和 `MissingEvidence`，但定义独立的 `CodeReviewInput`、`ReviewFinding` 和 `CodeReviewReport`。

### 什么是代码合入审查

本周审查的目标不是检查工作区当前所有文件，而是分析一个合入范围：

```text
base_ref...head_ref
```

例如：

```text
main...feature/upload-timeout
```

它表示从 base 与 head 的共同祖先出发，检查 head 分支新增的变化。Day43 只定义承载 base/head 和审查结果的模型；Git 取证会通过这些字段进入同一契约。

### 什么叫可行动 finding

下面的评论不可行动：

```text
这段代码不太好。
建议优化一下。
变量名可以更优雅。
```

合格 finding 至少回答六个问题：

```text
1. 问题是什么？
2. 属于哪类风险？
3. 严重级别是什么？
4. 位于哪个文件和变更行？
5. 哪些证据支持结论？
6. 应该如何修改并验证？
```

## 今日开发范围

今天形成下面的领域模型切片：

```text
base_ref + head_ref + workspace
  -> CodeReviewInput
  -> Evidence / MissingEvidence
  -> ReviewFinding
  -> CodeReviewReport
  -> Pydantic 引用与定位校验
```

实现任务：

```text
1. 创建 devagent.review 包
2. 定义严格 ReviewModel 基类，拒绝未知字段
3. 定义 ReviewSeverity 四级风险
4. 定义 ReviewCategory 六类风险
5. 定义 ReviewStatus，区分 reviewed 与 insufficient_evidence
6. 定义 ReviewLineSide，区分 base 与 head 侧行号
7. 定义包含文件、行号、证据、建议和验证方式的 ReviewFinding
8. 定义 CodeReviewInput，校验 base_ref 与 head_ref 不同
9. 定义 CodeReviewReport，校验 finding/evidence 引用完整性
10. 编写成功、失败、空 finding 和证据不足测试
```

今日产出的模型保持平台无关：仓库 ref、相对路径和 diff 侧属于 Git 审查语义，不包含 GitHub webhook、installation token、PR URL 或 comment ID。

## 推荐接口或实现设计

### 1. 推荐文件结构

```text
src/devagent/review/
├── __init__.py
└── models.py

tests/review/
└── test_review_models.py
```

`src/devagent/review/__init__.py` 只导出稳定公共类型：

```python
from .models import (
    CodeReviewInput,
    CodeReviewReport,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)

__all__ = [
    "CodeReviewInput",
    "CodeReviewReport",
    "ReviewCategory",
    "ReviewFinding",
    "ReviewLineSide",
    "ReviewSeverity",
    "ReviewStatus",
]
```

### 2. ReviewModel：严格字段边界

沿用 diagnosis 模型风格：

```python
from pydantic import BaseModel, ConfigDict


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

`extra="forbid"` 很重要。模型如果返回了契约之外的 `confidence_score`、`github_url` 或 `auto_fix`，Pydantic 应明确拒绝，而不是静默忽略字段漂移。

### 3. ReviewSeverity：严重级别

推荐四级：

```python
class ReviewSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

严重级别判断的是影响，不是模型有多确定：

| 级别 | 含义 | 示例 |
| --- | --- | --- |
| `critical` | 可能造成严重安全事件、数据丢失或不可逆破坏 | 绕过认证、泄漏密钥、删除生产数据 |
| `high` | 很可能导致核心功能错误、兼容性破坏或显著安全风险 | 金额计算错误、公开 API 破坏、权限校验缺失 |
| `medium` | 局部正确性、性能或维护风险，有明确修改价值 | 资源未关闭、明显 N+1 查询、关键边界未处理 |
| `low` | 非阻塞但仍然可行动的问题 | 次要错误处理缺口、局部重复导致后续易错 |

纯格式偏好不应成为 finding：

```text
变量名不是我喜欢的风格
空行数量不同
可以换一种同样正确的写法
```

### 4. ReviewCategory：风险分类

与计划保持一致：

```python
class ReviewCategory(str, Enum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    COMPATIBILITY = "compatibility"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    TEST_GAP = "test_gap"
```

分类与严重级别是两个维度：

```text
security + critical：认证绕过
security + medium：错误信息暴露内部实现但没有敏感数据
correctness + high：支付金额计算错误
test_gap + medium：关键失败分支没有测试
```

### 5. ReviewStatus：不要把“无问题”写成证据不足

推荐：

```python
class ReviewStatus(str, Enum):
    REVIEWED = "reviewed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
```

二者语义：

```text
reviewed + findings=[]
  已检查现有变更证据，没有发现符合报告标准的可行动风险。

insufficient_evidence + missing_evidence 非空
  缺少 diff、文件内容或必要上下文，无法完成可信审查。
```

不要使用 `passed` 或 `approved`。本周输出的是非阻塞建议，不代表 DevAgent 有权批准合入。

### 6. ReviewLineSide：定位 base/head 侧

一个 diff 同时包含删除行和新增行：

```python
class ReviewLineSide(str, Enum):
    BASE = "base"
    HEAD = "head"
```

含义：

```text
base：问题定位在被删除或被替换的旧代码侧
head：问题定位在新增或修改后的目标代码侧
```

核心领域使用 `base/head`，保持平台无关。平台 adapter 可以将它映射为目标平台需要的定位字段。

### 7. ReviewFinding 模型

推荐：

```python
from typing import Annotated

from pydantic import Field, model_validator

from devagent.diagnosis.models import EvidenceId


NonEmptyText = Annotated[str, Field(min_length=1)]
FindingId = Annotated[str, Field(pattern=r"^R[1-9][0-9]*$")]


class ReviewFinding(ReviewModel):
    finding_id: FindingId
    severity: ReviewSeverity
    category: ReviewCategory
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    file_path: str = Field(min_length=1, max_length=1_000)
    line_start: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)
    side: ReviewLineSide = ReviewLineSide.HEAD
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    suggestion: str = Field(min_length=1, max_length=2_000)
    verification_steps: list[NonEmptyText] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_line_range(self) -> "ReviewFinding":
        if self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end 不能小于 line_start")
        return self
```

`finding_id` 使用 `R1`、`R2`，便于报告、Evaluation、Trace 和平台评论关联。

### 8. 校验仓库相对路径

finding 的 `file_path` 应是仓库相对 POSIX 路径：

```text
src/devagent/api/app.py
examples/sample_repo/src/sample_app/uploader.py
```

应拒绝：

```text
/etc/passwd
../outside.py
src\windows\path.py
.
```

推荐 validator：

```python
from pathlib import PurePosixPath

from pydantic import field_validator


@field_validator("file_path")
@classmethod
def validate_file_path(cls, value: str) -> str:
    path = PurePosixPath(value)
    if value == "." or path.is_absolute() or ".." in path.parts:
        raise ValueError("file_path 必须是仓库内相对路径")
    if "\\" in value:
        raise ValueError("file_path 必须使用 POSIX 分隔符")
    return value
```

这里的校验保证报告定位格式稳定，但不代替文件工具的 workspace 安全检查。报告路径本身不会触发文件读取。

### 9. CodeReviewInput

复用第 6 周的 `Evidence` 与 `MissingEvidence`，不复制一套相同模型：

```python
from devagent.diagnosis import Evidence, MissingEvidence


class CodeReviewInput(ReviewModel):
    review_id: str = Field(min_length=1)
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    workspace: str = Field(default=".", min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_input(self) -> "CodeReviewInput":
        if self.base_ref == self.head_ref:
            raise ValueError("base_ref 与 head_ref 不能相同")
        _validate_unique_evidence_ids(self.evidence)
        return self
```

ref 只在模型层检查非空、长度和两者不同。具体 Git ref 是否存在、是否允许作为命令参数，由只读 Git 工具使用参数分隔和 subprocess 参数列表验证。

### 10. CodeReviewReport

推荐：

```python
class CodeReviewReport(ReviewModel):
    review_id: str = Field(min_length=1)
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    status: ReviewStatus
    summary: str = Field(min_length=1, max_length=2_000)
    findings: list[ReviewFinding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
```

报告 validator 至少校验：

```text
1. evidence_id 唯一
2. finding_id 唯一
3. finding.evidence_ids 全部存在于 report.evidence
4. insufficient_evidence 必须包含 missing_evidence
5. reviewed 允许 findings 为空
```

实现骨架：

```python
@model_validator(mode="after")
def validate_report(self) -> "CodeReviewReport":
    evidence_ids = [item.evidence_id for item in self.evidence]
    _validate_unique_values(evidence_ids, "evidence_id")

    finding_ids = [item.finding_id for item in self.findings]
    _validate_unique_values(finding_ids, "finding_id")

    known_evidence_ids = set(evidence_ids)
    referenced_ids = {
        evidence_id
        for finding in self.findings
        for evidence_id in finding.evidence_ids
    }
    dangling_ids = sorted(referenced_ids - known_evidence_ids)
    if dangling_ids:
        raise ValueError(f"引用了不存在的 evidence_id: {dangling_ids}")

    if (
        self.status == ReviewStatus.INSUFFICIENT_EVIDENCE
        and not self.missing_evidence
    ):
        raise ValueError("证据不足报告必须说明 missing_evidence")
    return self
```

### 11. 为什么 reviewed 可以没有 finding

无缺陷变更是 Evaluation 必须覆盖的场景：

```python
CodeReviewReport(
    review_id="review-clean-001",
    base_ref="main",
    head_ref="feature/docs",
    status=ReviewStatus.REVIEWED,
    summary="现有证据中未发现可行动的合入风险。",
    findings=[],
    evidence=[...],
)
```

如果强制 `reviewed` 至少有一条 finding，模型为了通过 Schema 可能制造问题，直接提高误报率。

### 12. 固定审查案例

准备一个最小正确性案例：

```text
变更：build_upload_timeout 固定返回 3 秒
证据 E1：git diff 新增 return self.config.min_timeout_seconds
证据 E2：相关测试要求大文件 timeout >= 12
```

finding：

```python
ReviewFinding(
    finding_id="R1",
    severity=ReviewSeverity.HIGH,
    category=ReviewCategory.CORRECTNESS,
    title="大文件上传仍固定使用最小超时",
    description=(
        "修改后的 build_upload_timeout 忽略 size_mb 和 bandwidth_mb_s，"
        "大文件上传会在预计完成前超时。"
    ),
    file_path="src/sample_app/uploader.py",
    line_start=24,
    side=ReviewLineSide.HEAD,
    evidence_ids=["E1", "E2"],
    suggestion="根据预计上传耗时和 safety_factor 计算 timeout，并保留最小值下限。",
    verification_steps=[
        "运行大文件上传 timeout 单元测试",
        "补充不同文件大小和带宽的参数化测试",
    ],
)
```

这条 finding 是可行动的，因为它同时包含影响、位置、证据、修改方向和验证方式。

## 测试与验收标准

### 第一阶段：枚举与基本字段

在 `tests/review/test_review_models.py` 验证：

```text
1. ReviewSeverity 包含 critical/high/medium/low
2. ReviewCategory 包含六类计划风险
3. ReviewStatus 区分 reviewed/insufficient_evidence
4. ReviewLineSide 区分 base/head
5. 未知枚举值被拒绝
6. ReviewModel 拒绝额外字段
```

### 第二阶段：ReviewFinding

成功测试：

```text
1. 正确性 finding 包含完整定位和证据
2. line_end 可以为空或大于等于 line_start
3. base/head 两侧定位都可表达
4. JSON round trip 后对象保持一致
```

失败测试：

```text
1. finding_id 不符合 R1 格式
2. file_path 为空、绝对路径、包含 .. 或反斜杠
3. line_start 小于 1
4. line_end 小于 line_start
5. evidence_ids 为空
6. suggestion 为空
7. verification_steps 为空
```

### 第三阶段：CodeReviewInput

```text
1. base_ref 与 head_ref 不同时通过
2. base_ref 与 head_ref 相同时拒绝
3. evidence_id 重复时拒绝
4. workspace 为空时拒绝
5. missing_evidence 可以作为取证状态进入输入
```

### 第四阶段：CodeReviewReport

```text
1. 有 finding 的 reviewed 报告通过
2. 没有 finding 的 reviewed 报告通过
3. insufficient_evidence 且包含 missing_evidence 时通过
4. insufficient_evidence 没有 missing_evidence 时拒绝
5. finding 引用未知 evidence_id 时拒绝
6. evidence_id 重复时拒绝
7. finding_id 重复时拒绝
8. 六类 category 都能进入报告
9. 报告 JSON round trip 后引用不丢失
```

### 推荐测试函数

```python
def test_code_review_report_accepts_actionable_finding(): ...
def test_code_review_report_accepts_clean_review(): ...
def test_code_review_report_rejects_dangling_evidence_id(): ...
def test_code_review_report_rejects_duplicate_finding_id(): ...
def test_insufficient_report_requires_missing_evidence(): ...
def test_review_finding_requires_repository_relative_path(): ...
def test_review_finding_rejects_reversed_line_range(): ...
def test_code_review_input_requires_distinct_refs(): ...
```

### 推荐验收命令

```bash
.venv/bin/pytest tests/review/test_review_models.py -q
.venv/bin/pytest tests/review tests/diagnosis -q
.venv/bin/python -m compileall -q src/devagent/review tests/review
.venv/bin/pytest -q
```

项目虚拟环境安装 Ruff 后可以执行：

```bash
.venv/bin/ruff check src/devagent/review tests/review
.venv/bin/ruff format --check src/devagent/review tests/review
```

### 基础通过

```text
[x] review 包可以正常导入
[x] 所有枚举值与 learning_plan.md 一致
[x] ReviewFinding 包含文件、行号、证据、建议和验证方式
[x] CodeReviewReport 可以表达有问题、无问题和证据不足
```

### 工程通过

```text
[x] 所有模型 extra=forbid
[x] 悬空 evidence 引用和重复 ID 被拒绝
[x] 仓库路径和行号范围经过校验
[x] 模型可稳定 JSON round trip
[x] 全量回归通过
```

### 业务通过

```text
[x] finding 不是纯风格偏好
[x] severity 表达影响，而不是置信度
[x] clean review 不会为了满足 Schema 制造 finding
[x] insufficient_evidence 明确记录缺失信息
[x] 每条 finding 都可定位、可解释、可修改、可验证
```

## 可量化结果

Day43 建立的是领域契约基线，不提前测量模型召回率和误报率。今日记录：

| 指标 | Day43 目标 | 统计方式 |
| --- | --- | --- |
| Finding 证据引用完整率 | 100% | 所有 finding.evidence_ids 均存在 |
| Finding 文件与行号可定位率 | 100% | 固定 finding 均有合法 path/side/line |
| 可行动信息完整率 | 100% | suggestion 和 verification_steps 均非空 |
| 风险分类覆盖 | 6 / 6 | 每种 ReviewCategory 至少一个模型案例 |
| 严重级别覆盖 | 4 / 4 | 每种 ReviewSeverity 至少一个模型案例 |
| 非法契约拦截率 | 100% | 固定非法输入全部触发 ValidationError |
| 模型校验 p95 | 小于 5 ms | 合法报告本地校验 1,000 次 |

第 7 周整体质量指标的基线目标保持为：

```text
HIGH / CRITICAL 风险召回率 >= 85%
可行动 finding 准确率 >= 70%
误报率 <= 20%
审查上下文字符数相比整文件注入降低 >= 40%
```

这些指标需要固定缺陷集和无缺陷变更集才能计算。Day43 的贡献是先让每个 finding 具备可统计的 category、severity、location 和 evidence_ids。

完成后记录：

```text
合法模型案例数：17
非法模型拦截数：29 / 29
证据引用完整率：100%
文件与行号可定位率：100%
模型校验 p95：0.1192 ms
```

## 关键原理

### 1. 代码审查不是静态代码总结

代码总结回答“这段代码做什么”；代码审查回答“这次待合入变更引入什么风险”。Finding 必须围绕变更影响，而不是复述函数逻辑。

### 2. three-dot diff 与共同祖先

`base_ref...head_ref` 使用 merge base 作为起点，关注 head 分支相对共同祖先新增的变化。它比直接比较两个分支尖端更接近 Pull Request 的合入语义。

要记住：

```text
base..head：集合语义上关注 head 有而 base 没有的提交
base...head：Git diff 中通常表示 merge-base(base, head) 到 head 的变化
```

Day43 的 `CodeReviewInput` 明确保存 base/head，为后续证据采集保留正确语义。

### 3. Category、Severity 和 Confidence 不是一回事

```text
Category：问题属于哪种风险
Severity：问题发生后的影响有多大
Confidence：现有证据对结论支持有多强
```

Day43 先用 evidence 强制约束结论，不增加独立 confidence 字段。不能因为模型“很确定”，就把低影响问题升级为 high。

### 4. 为什么 finding 必须定位到行

文件级评论会让开发者重新搜索问题，增加人工验证成本。行级定位可以：

```text
直接回到 diff 复核
生成 inline comment
统计定位正确率
判断评论是否仍适用于新版本 diff
```

定位失败的内容不应伪造行号；调用方可以把它降级到报告摘要或记录为缺失证据。

### 5. 为什么建议和验证方式都必填

只有建议没有验证方式：开发者不知道修复是否有效。

只有验证方式没有修改建议：开发者仍需重新分析问题。

二者共同构成可行动 finding：

```text
suggestion：怎样改变实现
verification_steps：怎样证明改变有效且没有回归
```

### 6. 为什么无 finding 是合法结果

审查系统必须允许“没有发现值得报告的问题”。否则模型会被 Schema 激励去制造低价值评论，导致误报和开发者不信任。

无 finding 不等于没有执行审查；`status=reviewed` 与 evidence 表明系统已经完成分析。

### 7. 为什么证据不足不是 clean review

```text
reviewed + findings=[]：看过足够证据，没有发现问题
insufficient_evidence：没有足够证据判断是否有问题
```

把两者混在一起会让“工具失败”看起来像“代码安全”，这是危险的假阴性。

### 8. 为什么审查不复用 DiagnosisReport

共享模型应该建立在相同语义上，而不是字段长得相似。诊断和审查都需要 Evidence，但 finding 分类、状态、定位和操作建议不同。复用 Evidence 可以保持引用一致；拆分报告可以保持领域语言准确。

### 9. model_validator 解决什么问题

字段级 `Field` 能验证单个值，`model_validator(mode="after")` 用来验证跨字段关系：

```text
line_end >= line_start
base_ref != head_ref
finding.evidence_ids 属于 report.evidence
insufficient_evidence 必须有 missing_evidence
```

这些约束无法可靠地只靠 Prompt 保证，必须在模型边界再次验证。

### 10. 为什么核心模型保持平台无关

本地 Git、GitHub Pull Request 或其他代码托管平台都可以提供：

```text
base/head
变更文件
diff 行
证据
```

核心模型保存这些稳定概念，不保存某个平台的 token、delivery ID 或评论接口参数。平台 adapter 负责把领域报告映射为摘要或 inline comment。

## 面试问题

1. 为什么代码审查不能直接复用 DiagnosisReport？
2. `ReviewCategory` 和 `ReviewSeverity` 分别表达什么？
3. 如何区分 high severity 与 high confidence？
4. 为什么每条 finding 必须引用 evidence_ids？
5. 为什么文件级定位不够，行号和 diff side 有什么价值？
6. 为什么 reviewed 报告允许 findings 为空？
7. clean review 与 insufficient_evidence 有什么区别？
8. 如何防止模型为了满足 Schema 编造审查问题？
9. 为什么修改建议和验证步骤都应该是必填字段？
10. `model_validator(mode="after")` 适合验证哪些跨字段关系？
11. `base_ref...head_ref` 为什么更符合 Pull Request 审查语义？
12. 为什么核心 CodeReviewReport 不应该包含 GitHub token 或 comment ID？

## 今日完成后记录区

### 实际完成内容

```text
- 创建平台无关的 devagent.review 领域包并导出稳定公共类型
- 定义四级 severity、六类 category、review 状态和 diff line side
- 定义 CodeReviewInput、ReviewFinding 和 CodeReviewReport 严格契约
- 校验 ref、仓库相对路径、行号范围、唯一 ID 和 evidence 引用完整性
- 区分已完成的 clean review 与证据不足报告
```

### 实际修改文件

```text
- src/devagent/review/__init__.py
- src/devagent/review/models.py
- tests/review/test_review_models.py
- docs/learning/week7/day43.md
- learning_plan.md
```

### 验收命令与结果

```text
- .venv/bin/pytest tests/review/test_review_models.py -q：46 passed
- .venv/bin/pytest tests/review tests/diagnosis -q：74 passed
- .venv/bin/python -m compileall -q src/devagent/review tests/review：通过
- .venv/bin/pytest -q：526 passed，1 个第三方 StarletteDeprecationWarning
```

### 可量化结果

```text
合法模型案例数：17
非法模型拦截数：29 / 29
证据引用完整率：100%
文件与行号可定位率：100%
风险分类覆盖：6 / 6
严重级别覆盖：4 / 4
模型校验 p95：0.1192 ms
```

### 遇到的问题与解决方式

```text
- 初版 severity 成员使用 Critical，统一改为 CRITICAL，保持枚举命名一致
- 初版只在 CodeReviewInput 拒绝相同 ref，提取共享校验并应用到报告
- 初版测试从 review.models 偶然导入 Evidence，改为从 diagnosis 公共入口导入
- 增加路径逃逸、重复 ID、悬空引用、非法分类与 JSON 往返等契约测试
```

### 周起点记录

```text
- 第 7 周从平台无关的审查领域契约开始
- Week6 的 Diagnosis/Evidence 设计作为本周证据驱动审查基线
```
