# Day 46：实现 CodeReviewService

## 今天目标

Day43 已经定义 `CodeReviewInput`、`CodeReviewFinding` 和 `CodeReviewReport`，Day44
提供基于 merge base 的 `git_compare`，Day45 则完成了证据驱动的代码审查 Prompt。
Day46 要把这些能力连接成一条可执行、可测试的业务链路：

```text
base_ref + head_ref + workspace
  -> git_compare
  -> diff Evidence
  -> read_file 补充变更文件上下文
  -> CodeReviewInput
  -> LLMClient.chat()
  -> CodeReviewReport.model_validate_json()
  -> 身份、引用与证据一致性校验
```

今日目标产物：

```text
src/devagent/review/service.py
src/devagent/review/__init__.py
tests/review/test_service.py
docs/learning/week7/day46.md
```

验收重点不是“模型能说出审查意见”，而是服务能够稳定保证：

```text
1. Git diff 和文件内容被转换为有界、可追溯的 Evidence
2. 工具失败优先降级为 missing_evidence，而不是泄漏原始异常
3. 没有任何有效证据时不调用 LLM，直接返回 insufficient_evidence
4. 模型非法 JSON、错误响应类型和空响应被转换为结构化服务错误
5. 悬空 evidence_id 被领域模型拒绝
6. 模型不能篡改 review_id、refs 或原始 Evidence
```

Day46 对齐 `learning_plan.md` 第 7 周的 `CodeReviewService` 任务，也延续
`plan.md` 中“每条 finding 必须绑定变更行或受影响代码证据”的约束。

## 背景与上下文

### Service 在代码审查链路中的位置

当前项目已经具备四块独立能力：

```text
review.models       定义输入、finding、证据和报告契约
tools.git_tools     生成确定性的 merge-base diff
prompts.code_review 描述模型审查规则和 JSON 输出契约
llm.base            提供 provider 无关的 LLMClient.chat()
```

`CodeReviewService` 的职责是编排这些能力，并在不可信边界之间做校验：

```text
Git / 文件系统 -> 可能失败、不完整、被截断
LLM             -> 可能返回空文本、工具调用、非法 JSON 或伪造字段
领域模型        -> 负责验证枚举、行号、状态和 evidence_id 引用
Service         -> 负责调用顺序、错误映射、身份一致性和证据原样保留
```

它不应该直接依赖 FastAPI、OpenAI SDK 或 GitHub SDK。Day47 的 API 和平台协议只需
注入并调用该 Service。

### 为什么不能直接把 patch 发给模型

直接发送 patch 虽然实现简单，但有三个问题：

```text
上下文不足：diff 只包含有限上下文，可能看不到被调用函数的完整行为
输入无界：大型变更可能超过模型上下文，导致成本和延迟失控
来源模糊：模型给出结论后，无法区分依据来自 diff 还是补充代码
```

因此，采集器要把不同来源标准化为 `Evidence`：

```text
E1 -> kind=git_diff，记录 merge-base patch
E2 -> kind=code，记录某个变更文件的有界内容
E3 -> kind=code，记录另一个变更文件的有界内容
```

模型只能引用这些 Evidence ID，Service 再验证报告中的 Evidence 是否和输入完全一致。

### 与 DiagnosisService 的关系

Day42 的 `DiagnosisService` 已经建立了可复用模式：

```text
注入 Collector
注入 LLMClient
构造 typed input
调用 Prompt builder
解析 Pydantic report
验证报告身份和证据一致性
转换外部异常
```

Day46 应沿用这个结构，降低认知成本。代码审查的特殊点在于：

```text
1. 输入有 base_ref/head_ref 两个 Git 身份
2. finding 必须定位 diff side 和行号
3. 除 diff 外，还需要读取变化后的 HEAD 文件作为补充上下文
4. patch 截断和单个文件读取失败通常属于证据不足，不是整个服务崩溃
```

## 今日开发范围

### 1. 创建审查服务与采集器

在 `src/devagent/review/service.py` 中实现：

```python
class CodeReviewEvidenceCollector(Protocol):
    def collect(
        self,
        *,
        review_id: str,
        base_ref: str,
        head_ref: str,
        workspace: Path,
    ) -> CodeReviewInput:
        ...


class LocalCodeReviewEvidenceCollector:
    ...


class CodeReviewService:
    ...
```

推荐同时定义：

```python
class CodeReviewServiceErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    EVIDENCE_COLLECTION_FAILED = "evidence_collection_failed"
    LLM_CALL_FAILED = "llm_call_failed"
    UNEXPECTED_LLM_RESPONSE = "unexpected_llm_response"
    EMPTY_LLM_RESPONSE = "empty_llm_response"
    INVALID_REPORT = "invalid_report"
    REPORT_MISMATCH = "report_mismatch"


class CodeReviewServiceError(RuntimeError):
    def __init__(self, code: CodeReviewServiceErrorCode, message: str) -> None:
        ...
```

### 2. 采集有界证据

`LocalCodeReviewEvidenceCollector` 负责：

```text
1. 调用 git_compare(workspace, base_ref, head_ref)
2. 将 GitCompareResult.patch 转换为 E1 / GIT_DIFF Evidence
3. 从 changed_files 中选择可读取的 HEAD 文件
4. 最多读取 5 个文件，每个文件最多保留前 200 行
5. 将文件内容依次转换为 E2、E3... / CODE Evidence
6. 把截断、文件不存在和工具失败转换为 MissingEvidence
7. 返回经过 Pydantic 校验的 CodeReviewInput
```

建议常量：

```python
MAX_REVIEW_EVIDENCE_CHARS = 4_000
MAX_CONTEXT_FILES = 5
MAX_CONTEXT_LINES_PER_FILE = 200
```

由此可得到清晰的上下文上限：

```text
1 份 diff Evidence + 5 份 code Evidence
每份 excerpt 最多 4,000 字符
总 Evidence excerpt 最多约 24,000 字符
```

文件选择规则应保持确定性：按 `git_compare` 返回的 `changed_files` 顺序去重，只读取
`new_path` 存在的文件。删除文件没有 HEAD 版本，不应尝试读取；其删除内容仍可由 diff
Evidence 审查。

### 3. 编排 LLM 调用与报告校验

`CodeReviewService.review()` 推荐执行顺序：

```text
1. 校验 base_ref、head_ref 和 workspace
2. 生成 review_id
3. 调用 collector.collect(...)
4. 校验 collector 返回的 review_id、refs、workspace
5. 若没有 Evidence，则直接构造 insufficient_evidence 报告
6. 构造 system + user 两条 Message
7. 调用 LLMClient.chat(messages)
8. 要求 response.type == FINAL_ANSWER
9. 拒绝空 content
10. CodeReviewReport.model_validate_json(response.content)
11. 校验报告身份与输入 Evidence 完全一致
12. 返回 CodeReviewReport
```

推荐接口：

```python
class CodeReviewService:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        evidence_collector: CodeReviewEvidenceCollector,
        review_id_factory: Callable[[], str] | None = None,
    ) -> None:
        ...

    def review(
        self,
        *,
        base_ref: str,
        head_ref: str,
        workspace: str | Path,
    ) -> CodeReviewReport:
        ...
```

### 4. 更新公共导出

在 `src/devagent/review/__init__.py` 中保留现有模型导出，并增加：

```python
from .service import (
    CodeReviewEvidenceCollector,
    CodeReviewService,
    CodeReviewServiceError,
    CodeReviewServiceErrorCode,
    LocalCodeReviewEvidenceCollector,
)
```

不要删除或重命名 Day43 已有公共类型。

## 推荐接口或实现设计

### 1. 依赖注入而不是在 Service 内创建依赖

推荐由构造函数注入 `LLMClient` 和 collector：

```python
service = CodeReviewService(
    llm_client=client,
    evidence_collector=LocalCodeReviewEvidenceCollector(),
)
```

这样做的收益：

```text
单元测试可以使用 FixedLLMClient，不请求真实模型
采集器可以独立测试 Git 和文件系统边界
未来 GitHub PR 输入可以替换 collector，而不修改 Service
核心服务保持 provider 和平台无关
```

`review_id_factory` 也应可注入。测试可固定为 `lambda: "review-001"`，避免随机 UUID
让断言变得模糊。

### 2. Git diff Evidence 的映射

推荐将 `GitCompareResult` 映射为：

```python
Evidence(
    evidence_id="E1",
    kind=EvidenceKind.GIT_DIFF,
    tool_name="git_compare",
    source=result.head_sha,
    locator=(
        f"merge_base={result.merge_base};"
        f"base_sha={result.base_sha};"
        f"head_sha={result.head_sha};"
        f"hunks={result.hunk_count};"
        f"truncated={str(result.truncated).lower()}"
    ),
    excerpt=truncate(result.patch, MAX_REVIEW_EVIDENCE_CHARS),
)
```

`source` 表示证据来自哪个提交状态，`locator` 记录如何重新定位，`excerpt` 才是交给
模型的实际内容。不要把整个 `GitCompareResult.model_dump_json()` 塞进 excerpt，否则元数据
和核心 patch 会混在一起。

当 `result.truncated is True` 时仍然保留 E1，同时增加：

```python
MissingEvidence(
    needed="完整的 merge-base diff",
    reason=(
        f"git_compare 输出已截断：返回 {result.returned_patch_chars} 字符，"
        f"原始内容 {result.original_patch_chars} 字符"
    ),
    suggested_tool="git_compare",
)
```

### 3. 文件上下文 Evidence 的映射

对于变化后的 HEAD 文件，推荐生成：

```python
Evidence(
    evidence_id="E2",
    kind=EvidenceKind.CODE,
    tool_name="read_file",
    source=str(workspace),
    locator=f"path={relative_path};lines=1-{returned_line_count}",
    excerpt=bounded_content,
)
```

读取时必须保持 workspace 边界。优先复用项目现有安全路径校验或文件工具，不要通过字符串
拼接绕过路径约束。`Evidence.excerpt` 要求非空，因此空文件不额外生成 CODE Evidence；其新增、
删除或状态信息仍保留在 diff Evidence 中。

单个文件失败的推荐处理：

```text
保留已经成功采集的其他 Evidence
追加 MissingEvidence(needed=该文件内容, reason=简洁原因, suggested_tool=read_file)
继续完成 CodeReviewInput
```

不要把绝对路径、系统栈信息或可能包含凭据的原始异常完整写进 `reason`。

### 4. `read_file` 与 `search_code` 的边界

`learning_plan.md` 的链路允许 `read_file / search_code` 补充上下文。首版建议采用确定性的
`read_file`：读取发生变化的 HEAD 文件，能覆盖最直接的调用上下文。

未来需要 `search_code` 时，可以增加独立的 `CodeContextCollector`：

```python
class CodeContextCollector(Protocol):
    def collect(self, compare_result: GitCompareResult, workspace: Path) -> list[Evidence]:
        ...
```

不要在 Day46 通过正则从任意 patch 文本猜测函数名后自动搜索。那种做法难以稳定测试，也可能
引入大量无关上下文。今日先把“变化文件内容”这条可重复的补充路径做好。

### 5. 无证据时短路

如果 collector 返回：

```python
CodeReviewInput(
    evidence=[],
    missing_evidence=[...],
    ...,
)
```

Service 应直接返回：

```python
CodeReviewReport(
    review_id=review_input.review_id,
    base_ref=review_input.base_ref,
    head_ref=review_input.head_ref,
    status=CodeReviewStatus.INSUFFICIENT_EVIDENCE,
    summary="缺少可用于代码审查的变更证据。",
    findings=[],
    evidence=[],
    missing_evidence=review_input.missing_evidence,
)
```

这条确定性分支避免模型在没有事实输入时编造 finding，也节省一次无效 LLM 调用。若已有部分
Evidence，则仍然调用模型，并把 `missing_evidence` 一并放入 Prompt，让模型判断能否完成审查。

### 6. 消息构造与 LLM 响应类型

消息应复用 Day45 的 Prompt：

```python
messages = [
    Message.system(CODE_REVIEW_SYSTEM_PROMPT),
    Message.user(build_code_review_prompt(review_input)),
]
response = self._llm_client.chat(messages)
```

具体工厂方法要以项目当前 `Message` 模型为准。关键断言是：

```text
消息数量为 2
第一条是 system role
第二条是 user role
user content 包含固定 review_id 和输入 Evidence
```

`LLMResponseType.TOOL_CALLS` 在本服务中不是合法终态。Service 已经在调用模型前完成证据采集，
因此模型必须返回 `FINAL_ANSWER`。收到工具调用应转换为
`UNEXPECTED_LLM_RESPONSE`，不要在 Service 内启动第二套 Agent Loop。

### 7. Pydantic 校验与 Service 一致性校验

第一层由领域模型完成：

```python
report = CodeReviewReport.model_validate_json(response.content)
```

它负责拒绝：

```text
非法 JSON
未知枚举
非法行号范围
reviewed / insufficient_evidence 状态组合错误
finding 引用不存在的 evidence_id
```

第二层由 Service 完成：

```python
if report.review_id != review_input.review_id:
    raise report_mismatch(...)
if report.base_ref != review_input.base_ref or report.head_ref != review_input.head_ref:
    raise report_mismatch(...)
if report.evidence != review_input.evidence:
    raise report_mismatch(...)
```

为什么要精确比较整个 Evidence，而不仅比较 ID：模型可能保留 `E1`，却修改 excerpt、source
或 locator，使报告看起来引用了原证据，实际内容已经被改写。Evidence 应被视为不可变事实输入。

### 8. 错误与证据不足的分界

建议按以下表格转换：

| 场景 | 结果 |
| --- | --- |
| base/head 为空、workspace 非法 | `INVALID_REQUEST` |
| `git_compare` 的预期执行失败 | `missing_evidence`，无其他证据时短路 |
| 单个文件不存在或不可读 | 保留其他 Evidence，并追加 `missing_evidence` |
| collector 返回字段与请求不一致 | `EVIDENCE_COLLECTION_FAILED` |
| collector 内部出现非预期数据结构 | `EVIDENCE_COLLECTION_FAILED` |
| `LLMClient.chat()` 抛异常 | `LLM_CALL_FAILED` |
| 模型返回 `TOOL_CALLS` | `UNEXPECTED_LLM_RESPONSE` |
| 模型最终文本为空 | `EMPTY_LLM_RESPONSE` |
| 文本不是合法 `CodeReviewReport` | `INVALID_REPORT` |
| 报告身份或 Evidence 被模型修改 | `REPORT_MISMATCH` |

原则是：外部事实拿不到，通常属于“证据不足”；系统自身契约被破坏，则属于结构化服务错误。

### 9. 异常消息脱敏

错误对象可以保留稳定 code 和面向调用方的简洁 message：

```python
try:
    response = self._llm_client.chat(messages)
except Exception as exc:
    raise CodeReviewServiceError(
        CodeReviewServiceErrorCode.LLM_CALL_FAILED,
        "代码审查模型调用失败",
    ) from exc
```

`raise ... from exc` 保留内部异常链，便于日志和调试；对外 `str(error)` 不应包含 API key、
完整 provider 响应或本机绝对路径。

## 测试与验收标准

### 1. 测试替身

在 `tests/review/test_service.py` 中定义最小替身：

```python
class FixedCollector:
    def __init__(self, review_input: CodeReviewInput) -> None:
        self.review_input = review_input
        self.calls: list[dict[str, object]] = []

    def collect(self, **kwargs: object) -> CodeReviewInput:
        self.calls.append(kwargs)
        return self.review_input


class FixedLLMClient:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.messages: list[list[Message]] = []

    def chat(self, messages: list[Message]) -> LLMResponse:
        self.messages.append(messages)
        return self.response
```

也可以增加 `RaisingLLMClient`，专门验证 provider 异常转换和错误消息脱敏。

### 2. LocalCodeReviewEvidenceCollector 测试

至少覆盖：

```text
1. 成功将 patch 转换为 E1 / GIT_DIFF Evidence
2. 成功读取变化后的文件并生成连续 E2、E3
3. deleted file 不会触发文件读取
4. 重复 new_path 只读取一次
5. 最多读取 MAX_CONTEXT_FILES 个文件
6. 每份 excerpt 不超过 MAX_REVIEW_EVIDENCE_CHARS
7. 空文件不生成违反 Evidence 非空契约的 CODE Evidence
8. patch 截断时保留 E1 并添加 MissingEvidence
9. 单个文件读取失败时保留其他证据并添加 MissingEvidence
10. 已知 GitCompareError 降级为 MissingEvidence
11. reader 返回非法类型时转换为 EVIDENCE_COLLECTION_FAILED
12. 所有读取路径都保持在 workspace 内
```

Git 与文件读取函数应注入或 monkeypatch，测试不依赖当前仓库的真实提交历史。

### 3. CodeReviewService 成功测试

固定输入和固定 LLM JSON，断言：

```text
review_id_factory 被用于生成 review_id
collector 收到正确 base_ref、head_ref 和 workspace
LLM 恰好收到 system/user 两条消息
Prompt 包含完整 CodeReviewInput
返回值是 CodeReviewReport
review_id、refs 和 Evidence 保持不变
```

至少准备一个 `reviewed + findings=[]` 报告和一个包含 finding 的合法报告。

### 4. 无证据短路测试

构造只有 `missing_evidence` 的输入，断言：

```text
status == insufficient_evidence
findings == []
missing_evidence 与采集结果一致
LLMClient.chat 调用次数 == 0
```

这是 Day46 最重要的确定性安全测试之一。

### 5. LLM 输出失败测试

逐项验证：

```text
TOOL_CALLS                 -> UNEXPECTED_LLM_RESPONSE
FINAL_ANSWER + 空字符串    -> EMPTY_LLM_RESPONSE
非 JSON                    -> INVALID_REPORT
字段类型错误               -> INVALID_REPORT
悬空 evidence_id           -> INVALID_REPORT
非法 status/findings 组合  -> INVALID_REPORT
```

不要只断言抛出 `Exception`，应精确断言 `CodeReviewServiceError.code`。

### 6. 报告篡改测试

模型输出即使通过 Pydantic，也可能违反请求身份。分别测试：

```text
review_id 不一致       -> REPORT_MISMATCH
base_ref 不一致        -> REPORT_MISMATCH
head_ref 不一致        -> REPORT_MISMATCH
Evidence source 被修改 -> REPORT_MISMATCH
Evidence locator 被修改 -> REPORT_MISMATCH
Evidence excerpt 被修改 -> REPORT_MISMATCH
Evidence 顺序被修改     -> REPORT_MISMATCH
```

### 7. 输入与外部异常测试

覆盖：

```text
空 base_ref / head_ref 不调用 collector 和 LLM
不存在或不是目录的 workspace 不调用 collector 和 LLM
collector 返回错误 review_id/refs 时转换为 EVIDENCE_COLLECTION_FAILED
collector 抛非预期异常时转换为 EVIDENCE_COLLECTION_FAILED
LLM provider 抛异常时转换为 LLM_CALL_FAILED
面向调用方的消息不包含 provider 原始 secret 文本
```

### 8. 验证命令

开发过程中先运行聚焦测试：

```bash
.venv/bin/pytest tests/review/test_service.py -q
```

再运行关联回归：

```bash
.venv/bin/pytest \
  tests/review \
  tests/prompts/test_code_review.py \
  tests/tools/test_git_tools.py \
  tests/llm -q
```

最后运行全量测试和静态检查（以项目当前已配置命令为准）：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

若项目尚未安装 `ruff`，在完成记录中如实写明未运行，不把缺少工具描述为代码失败。

## 可量化结果

Day46 完成后记录以下指标，不把 pytest 数量作为主要成果：

| 指标 | 计算方式 | 目标 |
| --- | --- | --- |
| Evidence 引用完整率 | 有效 finding 引用均存在 / 全部引用 | `100%` |
| Evidence 原样保留率 | 输出与输入完全相等的 Evidence / 输出 Evidence | `100%` |
| 工具失败结构化率 | 被转换为 MissingEvidence 或服务错误的固定失败用例 / 全部失败用例 | `100%` |
| 无证据 LLM 节省率 | 无 Evidence 用例中被跳过的 LLM 调用 / 预期调用 | `100%` |
| 非法模型输出拦截率 | 被拒绝的非法固定输出 / 全部非法固定输出 | `100%` |
| Evidence excerpt 上限 | diff + 最多 5 个文件 | `<= 24,000 字符` |
| Service 本地编排 p95 | 固定 collector/client 连续执行 1,000 次 | `< 10 ms` |

上下文缩减率可用以下方式测量：

```text
baseline_chars = 完整 patch + 所有变化后文件全文字符数
bounded_chars = 实际 CodeReviewInput 中所有 Evidence.excerpt 字符数
context_reduction = 1 - bounded_chars / baseline_chars
```

在大型固定样例上的目标为至少 `40%`。若当前样例本身小于上限，结果可能是 `0%`，完成记录
应如实写值，不为了达标人为扩大样例。

## 关键原理

### 1. Protocol 是什么，为什么用于 Collector

`typing.Protocol` 描述“对象需要具备什么方法”，而不要求继承某个共同基类：

```python
class CodeReviewEvidenceCollector(Protocol):
    def collect(...) -> CodeReviewInput:
        ...
```

任何实现了相同 `collect` 签名的对象都可以被 `CodeReviewService` 使用。这叫结构化子类型。
它适合本项目，因为本地 Git、未来 GitHub PR 和测试替身的数据来源不同，但都能产出同一个
`CodeReviewInput`。

需要记住：Protocol 主要帮助静态类型检查；运行时仍应校验 collector 返回对象的字段和身份。

### 2. 依赖注入不只是为了 Mock

依赖注入把“业务流程”和“依赖如何创建”分开：

```text
CodeReviewService 只知道 LLMClient 和 Collector 契约
CLI/API 负责选择真实 OpenAIClient 或其他 provider
测试负责选择 FixedLLMClient
```

除了测试便利，它还保证 `review.service` 不依赖 OpenAI、FastAPI 或 GitHub SDK，维持核心
运行时的模块边界。

### 3. 为什么工具失败不一定是异常终止

代码审查本质上是证据驱动的判断。某个文件读取失败意味着“无法证明某些结论”，不一定意味着
整个请求无法返回有用结果：

```text
有 diff、缺一个文件 -> 模型可基于有限证据审查或返回 insufficient_evidence
连 diff 都没有       -> Service 确定性返回 insufficient_evidence
collector 伪造身份    -> 系统契约损坏，必须抛结构化错误
```

这种设计称为 graceful degradation（优雅降级）：尽量保留已获得的价值，同时明确缺失内容，
而不是把部分失败伪装成完整成功。

### 4. `model_validate_json()` 做了什么

Pydantic v2 的 `Model.model_validate_json(text)` 会完成两步：

```text
JSON 文本解析
按模型字段、枚举和自定义 validator 进行校验
```

它比先 `json.loads()` 再手工取字段更适合这里，因为模型输出同时可能存在语法错误和领域约束
错误。两类错误都应被 Service 统一映射为 `INVALID_REPORT`，原始 `ValidationError` 通过异常链
保留给内部调试。

### 5. 为什么 Pydantic 之后还要校验身份

Pydantic 能证明报告“形状合法”，却不知道当前请求的真实 `review_id` 和 refs。例如模型返回另一个
合法 UUID，字段类型仍然正确。因此 Service 还要做跨对象不变量校验：

```text
report.review_id == review_input.review_id
report.base_ref == review_input.base_ref
report.head_ref == review_input.head_ref
report.evidence == review_input.evidence
```

这与数据库乐观锁、支付回调订单号核对的思想相同：格式合法不代表属于本次业务请求。

### 6. Evidence 为什么必须原样复制

Evidence 是审查结论的事实锚点。允许模型改写 Evidence 会造成“引用漂移”：finding 引用了 E1，
但 E1 已被模型改成更支持其判断的文本。精确比较整个对象可以阻止这种情况。

模型可以在 finding 的 `description` 中解释证据，但不能改写 `source`、`locator` 或 `excerpt`。

### 7. 为什么要限制上下文大小

模型输入越长，不代表审查越准确。无界全文会带来：

```text
更高 token 成本
更长响应延迟
更多无关代码干扰
更容易超过 provider 上下文窗口
测试结果难以重复
```

固定文件数、行数和字符数让成本可预测，也为后续 RAG 或 `search_code` 优化提供明确 baseline。

### 8. 为什么不在 Service 中执行模型 Tool Calls

项目已有 Agent Runtime 负责工具调用循环。`CodeReviewService` 是一个边界清晰的单次业务服务：
它先确定性采集证据，再要求模型返回最终报告。如果在这里继续执行模型 Tool Calls，会复制
Runtime 的权限、上限、错误转换和事件逻辑。

所以收到 `TOOL_CALLS` 时应报告 `UNEXPECTED_LLM_RESPONSE`。未来若代码审查需要自主工具循环，
应复用 Runtime 或增加受控编排层，而不是悄悄扩展 Service。

## 面试问题

### 1. CodeReviewService 为什么需要 Collector 抽象？

参考回答：

> Collector 将 Git、文件系统或平台 API 的证据获取，与模型编排和报告校验分开。Service 只依赖
> `CodeReviewInput` 契约，因此本地仓库、GitHub PR 和测试替身可以互换，核心服务保持平台无关。

### 2. 工具失败应该抛异常还是返回证据不足？

参考回答：

> 取决于失败是否破坏系统契约。Git diff 或单文件内容拿不到属于外部证据缺失，应记录
> `MissingEvidence` 并尽量降级；collector 返回错误身份或非法结构属于内部契约损坏，应转换为
> 结构化服务错误。

### 3. 为什么 `model_validate_json()` 后还要比较 Evidence？

参考回答：

> Pydantic 只能验证报告结构和引用关系，不能知道模型是否改写了本次输入证据。Service 精确比较
> Evidence 对象，确保 source、locator、excerpt 和顺序均未被模型篡改，避免引用漂移。

### 4. 没有 Evidence 时为什么不调用 LLM？

参考回答：

> 没有事实输入时调用模型只会增加幻觉、成本和延迟。Service 可以确定性返回
> `insufficient_evidence`，保留 `MissingEvidence`，并把该分支作为可测试的安全约束。

### 5. 如何控制代码审查的 token 成本？

参考回答：

> 对 diff 和文件 Evidence 设置字符上限，限制补充文件数量和每文件行数，并记录截断信息。随后用
> 完整输入作为 baseline 测量 context reduction，再通过检索提高有限预算下的证据命中率。

### 6. 为什么不让 CodeReviewService 直接使用 OpenAI SDK？

参考回答：

> 直接依赖 provider 会让核心服务难以测试和迁移，也会让模型配置渗入业务逻辑。通过 `LLMClient`
> 接口注入，Service 只处理统一消息和响应，API/CLI 负责选择 provider。

### 7. 怎样测试模型输出而不请求真实模型？

参考回答：

> 使用固定 `LLMClient` 返回确定的 `LLMResponse`，覆盖合法报告、非法 JSON、空响应、工具调用和
> provider 异常。这样测试关注 Service 契约，结果可重复且不产生网络成本。

## 今日完成后记录区

### 实际完成内容

```text
- [x] 创建 review/service.py
- [x] 实现 CodeReviewEvidenceCollector Protocol
- [x] 实现 LocalCodeReviewEvidenceCollector
- [x] 实现 CodeReviewService 与结构化错误
- [x] 更新 review 公共导出
- [x] 完成 collector 成功、截断和失败测试
- [x] 完成 Service 成功、短路、非法输出和篡改测试
- [x] 运行关联回归与全量测试
```

### 实际验证命令与结果

```text
.venv/bin/pytest tests/review/test_review_service.py -q
结果：35 passed

.venv/bin/pytest tests/review tests/prompts/test_code_review.py tests/tools/test_git_tools.py tests/diagnosis tests/llm -q
结果：178 passed

.venv/bin/pytest -q
结果：607 passed，1 条来自 Starlette TestClient/httpx 兼容层的既有弃用警告

.venv/bin/ruff check src/devagent/review src/devagent/diagnosis/__init__.py src/devagent/prompts/code_review.py tests/review
结果：All checks passed

.venv/bin/ruff check src tests
结果：发现 11 个既有问题，位于本日未修改的 WebSocket、read_file 和旧测试文件；
本次没有扩大范围修改这些文件。
```

### 实际可量化结果

```text
Evidence 引用完整率：100%
Evidence 原样保留率：100%
工具失败结构化率：100%（固定 Git、文件、Collector、LLM 失败用例）
无证据 LLM 节省率：100%
非法模型输出拦截率：100%（固定空响应、工具调用、非法 JSON、悬空引用用例）
最大 Evidence excerpt 字符数：24,000
Service 本地编排 p95：0.30 ms（固定 Collector/LLMClient，1,000 次）
固定大型样例上下文缩减率：73.33%（90,000 -> 24,000 字符）
```

### 实现偏差与原因

```text
1. 首版补充上下文只实现确定性的 read_file，没有从 patch 猜测符号后调用 search_code；
   后续可通过独立 CodeContextCollector 扩展。
2. read_file 读取当前 workspace 内容，因此 CODE Evidence 的 source 记录 workspace；
   GIT_DIFF Evidence 单独记录 head_sha，避免把当前文件错误标记为任意 Git blob。
3. 空文件不生成 CODE Evidence，因为共享 Evidence 模型要求 excerpt 非空；文件状态仍存在于 diff。
4. diagnosis 与 review 包的 Service 公共导出改为惰性加载，修复 models、prompts、service
   之间的循环导入，同时保持原有 from devagent.<package> import <Service> 用法不变。
5. CodeReviewReport JSON Schema 在 Prompt 模块预序列化，Service 本地编排 p95 从 17.20 ms
   降至 0.30 ms，Prompt 内容与公共接口不变。
```
