# Day 47：实现代码审查 API 与平台协议

## 今天目标

Day46 已经完成平台无关的 `CodeReviewService`：它接收本地 `base_ref`、`head_ref` 和
`workspace`，采集有界证据，调用 LLM，并返回经过严格校验的 `CodeReviewReport`。

Day47 要为这项能力增加 HTTP 入口，同时定义平台适配层必须遵守的协议：

```text
HTTP Request
  -> CodeReviewRequest
  -> FastAPI Depends(get_code_review_service)
  -> CodeReviewService.review(...)
  -> CodeReviewReport
  -> HTTP Response

Pull Request 平台
  -> PullRequestSource
  -> PullRequestSnapshot
  -> CodeReviewService
  -> ReviewPublisher

Webhook delivery_id
  -> WebhookDeliveryStore.claim()
  -> 原子判定是否允许处理
```

今日核心产物：

```text
src/devagent/review/ports.py
src/devagent/api/routes/reviews.py
src/devagent/api/schemas.py
src/devagent/api/routes/__init__.py
src/devagent/api/app.py
src/devagent/review/__init__.py
tests/api/test_reviews.py
tests/review/test_review_ports.py
docs/learning/week7/day47.md
```

接口：

```http
POST /api/v1/reviews/code
Content-Type: application/json
```

```json
{
  "base_ref": "main",
  "head_ref": "feature/payment",
  "workspace": "examples/sample_repo"
}
```

今日验收核心：

```text
1. 合法请求返回完整 CodeReviewReport
2. FastAPI 参数校验、业务输入错误、配置错误和上游失败具有稳定 HTTP 映射
3. API Key、模型和 base_url 从服务端环境读取，不进入请求 Schema
4. PullRequestSource、ReviewPublisher、WebhookDeliveryStore 保持平台无关
5. WebhookDeliveryStore 使用原子 claim 语义表达幂等边界
6. API 不调用 Publisher，不自动修改、批准、拒绝或合入代码
7. devagent.review.service 不导入 FastAPI、GitHub SDK 或平台实现
```

Day47 对齐 `learning_plan.md` 第 7 周“代码审查 API 与平台协议”，并保持 `plan.md`
规定的建议模式：首版只形成审查报告，不执行仓库写操作或平台决策。

## 背景与上下文

### API 层应该做什么

API 层是传输协议适配器，主要负责：

```text
解析和校验 HTTP JSON
通过 Depends 获得已配置的 Service
调用 Service
把领域报告序列化为响应
把结构化领域错误映射为 HTTP 状态码
```

API 层不应重新实现：

```text
Git compare
文件上下文采集
Prompt 构造
LLM 输出解析
Evidence 一致性校验
finding 业务规则
```

这些规则已经属于 Day46 的 Service 和 Day43 的领域模型。如果路由再次实现，CLI、API 和
平台 webhook 会形成三套不一致行为。

### 为什么需要平台协议

本地代码审查和 Pull Request 审查共享核心流程，但输入与输出通道不同：

```text
本地调用：用户直接提供 refs 和 workspace，报告直接作为 HTTP JSON 返回
平台调用：平台事件提供仓库和 PR 编号，需要获取 refs，最终把报告发布回平台
```

如果核心代码直接依赖 GitHub SDK，会产生这些问题：

```text
无法在纯本地仓库复用
单元测试需要模拟大量 SDK 对象
更换 GitLab 或其他平台时必须修改 Service
平台鉴权和网络异常侵入核心业务
```

因此 Day47 只让核心层认识三个能力协议：

```text
PullRequestSource      获取 PR 快照
ReviewPublisher       发布已校验报告
WebhookDeliveryStore  原子记录 webhook delivery_id
```

具体平台 SDK 是协议的实现者，不是领域 Service 的依赖。

### 同步 API 与平台异步入口的区别

`POST /api/v1/reviews/code` 是开发者主动调用的本地同步接口：请求等待 Service 返回报告，成功时
使用 `200 OK`。

平台 webhook 的响应时间、重投和后台任务约束不同，应通过幂等检查后快速确认，再异步完成审查。
Day47 的协议设计要允许这种调用方式，但当前 `/reviews/code` 不需要引入 `BackgroundTasks` 或
TaskManager。

### 为什么这是 POST，而不是 GET

虽然代码审查不会修改仓库，但它会启动一次新的计算：

```text
生成新的 review_id
读取 Git 与文件证据
调用付费或有配额的 LLM
产生新的报告
```

GET 应保持安全、可缓存且不用于携带复杂请求体。代码审查具有计算副作用和 JSON 输入，所以使用
POST 更符合 HTTP 语义。

## 今日开发范围

### 1. 定义平台无关模型和 Protocol

创建 `src/devagent/review/ports.py`，推荐包含：

```python
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import CodeReviewReport


class ReviewPortModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PullRequestLocator(ReviewPortModel):
    platform: str = Field(min_length=1, max_length=50)
    repository: str = Field(min_length=1, max_length=500)
    number: int = Field(ge=1)


class PullRequestSnapshot(ReviewPortModel):
    locator: PullRequestLocator
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    head_sha: str = Field(min_length=7, max_length=64)
    workspace: str = Field(min_length=1)


class ReviewPublishResult(ReviewPortModel):
    summary_published: bool
    inline_comment_count: int = Field(ge=0)
    downgraded_finding_count: int = Field(ge=0)
```

协议：

```python
class PullRequestSource(Protocol):
    def get_pull_request(
        self,
        locator: PullRequestLocator,
    ) -> PullRequestSnapshot:
        ...


class ReviewPublisher(Protocol):
    def publish(
        self,
        *,
        pull_request: PullRequestSnapshot,
        report: CodeReviewReport,
    ) -> ReviewPublishResult:
        ...


class WebhookDeliveryStore(Protocol):
    def claim(self, delivery_id: str) -> bool:
        ...

    def mark_completed(self, delivery_id: str) -> None:
        ...

    def release(self, delivery_id: str) -> None:
        ...
```

这些方法建议保持同步，与当前项目的 Service、TaskManager 和工具接口风格一致。平台适配器内部
可以使用同步 SDK；若将来整体迁移为 async，再统一调整边界。

### 2. 定义 HTTP 请求模型

在 `src/devagent/api/schemas.py` 增加：

```python
class CodeReviewRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "base_ref": "main",
                    "head_ref": "feature/payment",
                    "workspace": "examples/sample_repo",
                }
            ]
        },
    )

    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    workspace: str = Field(default=".", min_length=1, max_length=2_000)
```

可增加 `model_validator`，提前拒绝：

```text
base_ref/head_ref 首尾空白
base_ref == head_ref
```

即使 API Schema 已校验，`CodeReviewService` 仍保留相同防线，因为 Service 也可能由 CLI、测试
或平台适配器直接调用。

请求模型不要包含：

```text
api_key
model
base_url
provider
publish
approve
merge
```

模型配置属于服务端部署配置；发布与合入属于单独的受控平台动作，不能由这个本地审查请求开启。

### 3. 创建 Review Router

创建 `src/devagent/api/routes/reviews.py`：

```python
router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


@router.post("/code", response_model=CodeReviewReport)
def review_code(
    request: CodeReviewRequest,
    service: CodeReviewService = Depends(get_code_review_service),
) -> CodeReviewReport:
    ...
```

路由只做参数转发：

```python
return service.review(
    base_ref=request.base_ref,
    head_ref=request.head_ref,
    workspace=request.workspace,
)
```

不要在路由中实例化 Git 工具、拼 Prompt、解析模型 JSON 或调用 `ReviewPublisher`。

### 4. 创建 Service 依赖

`get_code_review_service()` 负责组合真实依赖：

```python
def get_code_review_service() -> CodeReviewService:
    llm_client = create_review_llm_client()
    return CodeReviewService(
        llm_client=llm_client,
        evidence_collector=LocalCodeReviewEvidenceCollector(),
    )
```

`create_review_llm_client()` 参考 Diagnosis 路由，从服务端环境读取：

```text
DEVAGENT_LLM_API_KEY，回退 OPENAI_API_KEY
DEVAGENT_LLM_MODEL
DEVAGENT_LLM_BASE_URL，可选
```

并启用 JSON 输出：

```python
OpenAICompatibleLLMClient(
    api_key=api_key,
    model=model,
    base_url=base_url,
    response_format={"type": "json_object"},
)
```

缺少必要配置时依赖返回 `503 Service Unavailable`，错误详情使用稳定结构：

```json
{
  "detail": {
    "code": "configuration_error",
    "message": "代码审查服务缺少 LLM API Key"
  }
}
```

不要回显环境变量值。

### 5. 映射 Service 错误

推荐映射：

| CodeReviewServiceErrorCode | HTTP 状态 | 含义 |
| --- | --- | --- |
| `INVALID_REQUEST` | `400 Bad Request` | JSON 结构合法，但 workspace 或业务输入无效 |
| `EVIDENCE_COLLECTION_FAILED` | `502 Bad Gateway` | Git/文件证据无法可靠标准化 |
| `LLM_CALL_FAILED` | `502 Bad Gateway` | 模型 provider 调用失败 |
| `UNEXPECTED_LLM_RESPONSE` | `502 Bad Gateway` | 模型返回工具调用等错误终态 |
| `EMPTY_LLM_RESPONSE` | `502 Bad Gateway` | 模型没有返回可解析内容 |
| `INVALID_REPORT` | `502 Bad Gateway` | 模型报告不满足领域契约 |
| `REPORT_MISMATCH` | `502 Bad Gateway` | 模型篡改请求身份或 Evidence |

区分 `422` 与 `400`：

```text
422 -> FastAPI/Pydantic 在进入路由前发现请求字段格式错误
400 -> 请求字段格式正确，但 Service 发现业务输入无效
```

`insufficient_evidence` 是一个合法的 `CodeReviewReport`，不是异常，应返回 `200`。

### 6. 注册 Router 和公共导出

在 `src/devagent/api/routes/__init__.py` 增加：

```python
from .reviews import router as reviews_router
```

在 `src/devagent/api/app.py` 增加：

```python
app.include_router(reviews_router)
```

在 `src/devagent/review/__init__.py` 导出 ports 模型和协议，同时保留当前惰性 Service 导出，
避免重新引入 `models -> prompts -> service` 循环依赖。

## 推荐接口或实现设计

### 1. `PullRequestLocator` 与 `PullRequestSnapshot` 为什么分开

`PullRequestLocator` 是获取对象所需的最小标识：

```json
{
  "platform": "github",
  "repository": "owner/project",
  "number": 42
}
```

`PullRequestSnapshot` 是某个时刻已经解析出的审查输入：

```json
{
  "locator": {
    "platform": "github",
    "repository": "owner/project",
    "number": 42
  },
  "base_ref": "main",
  "head_ref": "feature/payment",
  "head_sha": "0123456789abcdef...",
  "workspace": "/bounded/review/workspaces/delivery-123"
}
```

把它们分开有两个好处：

```text
调用方只需先知道 locator，Source 负责解析平台状态
Publisher 使用 snapshot，可确认发布报告对应哪个 head_sha
```

PR 在审查过程中可能收到新提交。`head_sha` 是防止旧报告误发到新版本的重要身份字段。

### 2. `ReviewPublisher` 返回结果而不是 `None`

平台可能无法把每条 finding 都映射成 inline comment，例如：

```text
finding 行号不在当前 diff
目标文件已被后续提交修改
平台限制单次评论数量
平台 API 暂时拒绝某条评论
```

返回 `ReviewPublishResult` 可以量化发布结果：

```text
summary_published
inline_comment_count
downgraded_finding_count
```

`downgraded_finding_count` 表示无法做 inline 定位、但已降级写入摘要的 finding 数量。它比简单
返回 `True/False` 更适合 Trace 和 Evaluation。

### 3. Webhook 幂等为什么需要原子 `claim`

平台可能因超时或网络问题重复投递同一个 `delivery_id`。错误实现通常是：

```python
if not store.contains(delivery_id):
    store.add(delivery_id)
    process()
```

两个并发请求可能同时看到 `contains == False`，然后都执行审查和发布。检查与写入必须是一个
原子动作：

```python
if not store.claim(delivery_id):
    return duplicate_response
```

推荐状态语义：

```text
claim == True   -> 当前调用获得处理权，delivery 进入 processing
claim == False  -> delivery 已 processing 或 completed，不重复处理
mark_completed  -> 成功完成，保留幂等记录
release         -> 可重试失败时释放 processing 占用
```

首个内存实现还应有容量上限和清理顺序，防止 delivery ID 无界增长。Protocol 不规定具体锁和
容器，让实现可以选择线程锁、数据库唯一约束或 Redis 原子命令。

### 4. FastAPI `Depends` 如何工作

`Depends(get_code_review_service)` 告诉 FastAPI：调用路由前先调用依赖函数，并把返回值注入
`service` 参数。

```python
def review_code(
    request: CodeReviewRequest,
    service: CodeReviewService = Depends(get_code_review_service),
) -> CodeReviewReport:
    ...
```

测试可以替换依赖：

```python
app.dependency_overrides[get_code_review_service] = lambda: StubReviewService()
```

这样 TestClient 不会读取真实 `.env`、运行 Git 或调用模型。测试结束后必须清理
`app.dependency_overrides`，避免一个测试污染另一个测试。

### 5. `response_model` 的作用

FastAPI 的 `response_model=CodeReviewReport` 会：

```text
生成 OpenAPI 响应 Schema
验证路由返回值能否形成 CodeReviewReport
按模型规则序列化枚举和嵌套 Evidence
过滤或拒绝不符合声明的响应数据
```

它是 HTTP 出口校验，但不能替代 Service 的一致性校验。Service 必须在返回前确认 Evidence 没有
被模型篡改；路由只验证最终对象形状。

### 6. 配置为什么放在服务端环境

如果请求体允许传入 `api_key`、`base_url` 或 provider，调用者可能：

```text
让服务访问任意外部地址
绕过部署方选择的模型和审计策略
把凭据写入请求日志或 Trace
使相同 API 的运行行为不可预测
```

因此 Review API 与 Diagnosis API 一样使用服务端 `.env`。OpenAPI 示例只展示业务输入，不出现
字符串占位的敏感配置字段。

### 7. API 为什么不接收 `publish=true`

“生成审查报告”和“向外部平台发布评论”是不同权限等级的动作：

```text
生成报告 -> 本地只读 Git、文件读取、LLM 调用
发布评论 -> 外部网络写操作、平台身份、速率限制和审计
批准/合入 -> 更高风险的仓库状态变更
```

`/reviews/code` 只返回报告。Publisher 由受控平台编排显式调用，不由任意 HTTP 请求中的布尔字段
触发。这样也能通过测试证明本地审查接口没有平台写副作用。

### 8. 不要在 Core Service 中导入 Ports 实现

依赖方向应保持：

```text
review.models / review.service / review.ports
                 ^
                 |
api route 或 platform integration 负责组合
```

`CodeReviewService` 不需要知道 PR 编号或评论 API。编排层从 `PullRequestSource` 得到 snapshot，
调用 Service，再把报告交给 `ReviewPublisher`。这符合依赖倒置原则：核心依赖抽象，外部适配器
实现抽象。

## 测试与验收标准

### 1. API 测试替身与清理

在 `tests/api/test_reviews.py` 使用：

```python
class StubReviewService:
    def __init__(self, report: CodeReviewReport) -> None:
        self.report = report
        self.calls: list[dict[str, str]] = []

    def review(self, **kwargs: str) -> CodeReviewReport:
        self.calls.append(kwargs)
        return self.report
```

并增加自动 fixture：

```python
@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
```

### 2. 成功响应测试

固定一个合法 `CodeReviewReport`，断言：

```text
POST /api/v1/reviews/code 返回 200
StubReviewService 恰好调用一次
base_ref、head_ref、workspace 原样传递
响应 JSON 能被 CodeReviewReport.model_validate() 恢复
findings、Evidence、side 和 line 信息完整保留
```

再增加一个 `insufficient_evidence` 报告，断言它仍返回 `200`，而不是 `4xx/5xx`。

### 3. 请求校验测试

至少覆盖：

```text
缺少 base_ref -> 422
缺少 head_ref -> 422
空 ref -> 422
ref 首尾空白 -> 422
base_ref == head_ref -> 422
空 workspace -> 422
未知字段 -> 422
ref 或 workspace 超长 -> 422
```

这些场景应在进入 Stub Service 前被拒绝，断言 `calls == []`。

### 4. 错误映射测试

使用抛出固定 `CodeReviewServiceError` 的 Stub，逐项验证：

```text
INVALID_REQUEST -> 400 + detail.code=invalid_request
EVIDENCE_COLLECTION_FAILED -> 502
LLM_CALL_FAILED -> 502
UNEXPECTED_LLM_RESPONSE -> 502
EMPTY_LLM_RESPONSE -> 502
INVALID_REPORT -> 502
REPORT_MISMATCH -> 502

> 2026-07-31 契约更新：`REPORT_MISMATCH` 保留为兼容错误码和既有 API 映射，但当前
> `CodeReviewService` 不再信任或比较模型复制的权威字段。模型生成 Draft，Service 绑定
> `review_id`、refs 和 evidence 后再完成最终校验。
```

响应 detail 只包含稳定 `code` 和脱敏 `message`。

### 5. LLM 配置测试

monkeypatch 环境与客户端类，验证：

```text
DEVAGENT_LLM_API_KEY 优先，OPENAI_API_KEY 可回退
DEVAGENT_LLM_MODEL 必填
DEVAGENT_LLM_BASE_URL 可选
response_format == {"type": "json_object"}
缺 API Key -> 503 configuration_error
缺 model -> 503 configuration_error
错误响应不包含任何环境变量值
```

单元测试不请求真实模型。

### 6. OpenAPI 与路由注册测试

断言 `/openapi.json` 中：

```text
存在 /api/v1/reviews/code
POST operation 存在
requestBody 引用 CodeReviewRequest
200 response 引用 CodeReviewReport
示例 refs 和 workspace 合法
请求 Schema 不包含 api_key、model、base_url、publish、approve、merge
```

### 7. Ports 契约测试

在 `tests/review/test_review_ports.py` 覆盖模型约束：

```text
PullRequestLocator 拒绝空 platform/repository 和 number <= 0
PullRequestSnapshot 保留 locator、refs、head_sha、workspace
ReviewPublishResult 拒绝负评论数量
所有 Port Model 拒绝未知字段
```

再用最小 Fake 证明结构化子类型可用：

```python
class FakeDeliveryStore:
    def claim(self, delivery_id: str) -> bool:
        ...

    def mark_completed(self, delivery_id: str) -> None:
        ...

    def release(self, delivery_id: str) -> None:
        ...
```

Protocol 测试重点是方法语义和类型边界，不需要访问真实平台。

### 8. 架构边界测试或静态断言

检查：

```text
src/devagent/review/service.py 不导入 fastapi
src/devagent/review/service.py 不导入 github 或平台 SDK
reviews route 不导入 ReviewPublisher
POST /reviews/code 不调用任何 publish/approve/merge 方法
```

如果不希望写脆弱的源码字符串测试，可以通过 Stub 依赖的调用记录证明路由只调用
`service.review()`，并在人工审查中确认 import 边界。

### 9. 验证命令

先运行聚焦测试：

```bash
.venv/bin/pytest tests/review/test_review_ports.py tests/api/test_reviews.py -q
```

再运行关联回归：

```bash
.venv/bin/pytest \
  tests/review \
  tests/api/test_reviews.py \
  tests/api/test_diagnoses.py \
  tests/api/test_health.py -q
```

最后运行全量测试和本日范围静态检查：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check \
  src/devagent/review \
  src/devagent/api/routes/reviews.py \
  src/devagent/api/schemas.py \
  src/devagent/api/routes/__init__.py \
  src/devagent/api/app.py \
  tests/review/test_review_ports.py \
  tests/api/test_reviews.py
```

## 可量化结果

Day47 完成后记录：

| 指标 | 计算方式 | 目标 |
| --- | --- | --- |
| API 参数传递完整率 | Stub 收到的正确字段 / 请求业务字段 | `100%` |
| 报告序列化完整率 | JSON 往返后相等的固定报告 / 全部固定报告 | `100%` |
| Service 错误映射覆盖率 | 有明确 HTTP 映射的错误码 / 全部 Service 错误码 | `100%` |
| 配置泄漏用例阻断率 | 不包含固定 secret 的错误响应 / 配置失败用例 | `100%` |
| 平台写副作用次数 | `/reviews/code` 固定 API 用例中的 Publisher 调用 | `0` |
| Core 平台耦合数 | `review.service` 中 FastAPI/平台 SDK import 数 | `0` |
| OpenAPI 业务字段完整率 | Schema 中存在的预期业务字段 / 3 | `100%` |
| TestClient API p95 | 固定 Stub Service 连续请求 500 次 | `< 20 ms` |

平台协议还应记录：

```text
Webhook claim 原子语义：同一 delivery_id 首次 True，重复调用 False
发布结果可观测字段：summary、inline、downgraded 三类结果完整率 100%
```

## 关键原理

### 1. Ports and Adapters 是什么

Port 是核心业务希望外部世界提供的接口，Adapter 是某个平台对接口的具体实现：

```text
Port: PullRequestSource.get_pull_request()
Adapter: GitHubPullRequestSource

Port: ReviewPublisher.publish()
Adapter: GitHubReviewPublisher
```

核心代码面向 Port 编程，就能在单元测试中使用 Fake Adapter，也能在不修改 Service 的情况下
接入其他平台。这种结构也称六边形架构的一部分。

### 2. `Protocol` 与继承式 ABC 的区别

`Protocol` 使用结构化子类型：对象只要实现正确的方法签名，就满足接口，不要求显式继承。

```python
class FakePullRequestSource:
    def get_pull_request(self, locator: PullRequestLocator) -> PullRequestSnapshot:
        ...
```

这让第三方 SDK 包装器和测试 Fake 更轻量。需要记住：Protocol 主要帮助静态类型检查，Pydantic
模型仍负责运行时数据校验。

### 3. 幂等性是什么

幂等表示同一个操作重复执行，不会产生额外业务效果。Webhook 场景中，同一个 delivery 重投十次，
最多只能形成一次审查和一次发布。

HTTP 请求重复不等于 Python 函数重复；系统需要稳定的幂等键。平台提供的 `delivery_id` 就是这个键。
原子 `claim` 同时完成“检查是否处理过”和“占用处理权”，避免并发竞态。

### 4. `200`、`202`、`400`、`422`、`502`、`503` 的区别

```text
200 OK                  同步审查已经完成，返回报告
202 Accepted            请求已接受但后台任务尚未完成
400 Bad Request         业务输入无效，例如 workspace 不存在
422 Unprocessable Entity JSON 能解析，但不满足请求 Schema
502 Bad Gateway         依赖的 Git/LLM 输出失败或不可信
503 Service Unavailable 服务缺少运行配置，当前无法提供能力
```

状态码应表达失败发生在哪一层，而不是所有错误都返回 500。

### 5. FastAPI 依赖覆盖为什么适合测试

`app.dependency_overrides` 在测试期间把真实依赖函数映射到替身。请求仍然经过完整的路由匹配、
Pydantic 校验、异常转换和响应序列化，但不会访问网络或 Git。

它比 monkeypatch 路由内部全局对象更稳定，因为依赖关系本来就是公开的组合边界。

### 6. OpenAPI Schema 为什么也是接口契约

FastAPI 根据请求模型和 `response_model` 自动生成 OpenAPI。前端、SDK 生成器和人工调试工具都依赖
这份契约。如果示例自动填入无效字符串，开发者会得到误导性的首次调用体验。

因此要测试 OpenAPI 中的路径、字段和合法示例，而不仅测试 Python 路由函数。

### 7. 为什么 API Schema 与领域模型可以重复校验

API Schema 保护 HTTP 边界，领域 Service 保护所有调用入口：

```text
HTTP -> CodeReviewRequest -> CodeReviewService
CLI ----------------------> CodeReviewService
Platform orchestration ---> CodeReviewService
```

如果只在 API 校验，其他入口就可能绕过规则。两层校验不是无意义重复，而是不同信任边界的防御。

### 8. 为什么平台发布必须和报告生成分离

报告生成是只读分析，平台发布是外部写操作。分离后可以：

```text
先保存和人工检查报告，再决定是否发布
对发布动作单独做权限、重试和速率限制
避免模型直接决定 approve 或 merge
在平台失败时保留已经生成的报告
```

这也是项目“建议模式”的安全基础。

## 面试问题

### 1. 为什么 CodeReview API 使用 POST？

参考回答：

> 请求会生成新的 review_id、读取证据并调用 LLM，属于启动一次计算，不适合被缓存或用 GET 请求体
> 表达。POST 能承载结构化输入，并正确表达非幂等的分析操作。

### 2. `Depends` 如何提升可测试性？

参考回答：

> 路由依赖公开的 Service provider，而不是创建全局真实对象。测试通过
> `app.dependency_overrides` 注入 Stub，仍走完整 HTTP 栈，同时避免真实 Git、环境配置和网络调用。

### 3. 为什么需要 PullRequestSource 和 ReviewPublisher 两个接口？

参考回答：

> PR 读取和评论发布是两个方向、两个权限等级的外部能力。分开后可以独立测试、独立重试，并让
> 核心 Service 只处理本地 refs、workspace 和报告，不依赖具体平台 SDK。

### 4. 如何防止 webhook 重复处理？

参考回答：

> 使用平台 delivery_id 作为幂等键，由 DeliveryStore 提供原子 `claim`。首次 claim 返回 True 并
> 占用处理权，processing 或 completed 状态的重复 delivery 返回 False，避免并发检查写入竞态。

### 5. 为什么 insufficient_evidence 返回 200？

参考回答：

> 它是领域契约中的合法结果，表示系统成功完成证据评估，但证据不足以形成可信 finding。只有请求、
> 配置或依赖执行失败才映射为 HTTP 错误。

### 6. 如何证明 API 不会自动合入代码？

参考回答：

> 路由依赖只有 `CodeReviewService`，请求 Schema 没有 publish、approve 或 merge 字段，成功测试只
> 记录 `service.review()` 调用；核心 Service 也不导入平台 Publisher 或写 Git 工具。

### 7. 为什么要记录 head_sha？

参考回答：

> 分支名会移动。head_sha 把 PR 快照和报告绑定到具体提交，发布前可以检查平台当前 head 是否仍然
> 一致，避免把旧代码的评论发布到新版本。

### 8. 什么时候使用 502，什么时候使用 503？

参考回答：

> 已配置服务在调用 Git/LLM 时失败或返回不可信结果用 502；服务自身缺少 API Key、模型名等部署
> 配置、当前无法提供能力时用 503。请求字段错误则使用 422 或 400。

## 今日完成后记录区

### 实际完成内容

```text
- [x] 创建 review/ports.py 与平台无关模型
- [x] 实现 PullRequestSource、ReviewPublisher、WebhookDeliveryStore Protocol
- [x] 创建 CodeReviewRequest
- [x] 创建 POST /api/v1/reviews/code
- [x] 实现 Service 依赖与 LLM 服务端配置
- [x] 注册 reviews router
- [x] 更新 review 公共导出
- [x] 完成 API 成功、校验、错误映射和 OpenAPI 测试
- [x] 完成 Ports 模型与幂等语义测试
- [x] 运行关联回归和全量测试
```

### 实际验证命令与结果

```text
.venv/bin/pytest tests/review/test_review_ports.py tests/api/test_reviews.py -q
结果：45 passed，1 条来自 Starlette TestClient/httpx 兼容层的既有弃用警告

.venv/bin/pytest tests/api tests/review tests/diagnosis tests/prompts/test_code_review.py -q
结果：236 passed，1 条既有弃用警告

.venv/bin/pytest -q
结果：652 passed，1 条既有弃用警告

.venv/bin/ruff check src/devagent/review src/devagent/api/routes/reviews.py \
  src/devagent/api/schemas.py src/devagent/api/routes/__init__.py \
  src/devagent/api/app.py src/devagent/api/__init__.py \
  tests/review/test_review_ports.py tests/api/test_reviews.py
结果：All checks passed

.venv/bin/ruff check src tests
结果：发现 11 个既有问题，位于本日未修改的 WebSocket、read_file 和旧测试文件；
本次没有扩大范围修改这些文件。
```

### 实际可量化结果

```text
API 参数传递完整率：100%（base_ref、head_ref、workspace 3/3）
报告序列化完整率：100%（finding、定位和 Evidence JSON 往返保持相等）
Service 错误映射覆盖率：100%（8/8 个 ErrorCode）
配置泄漏用例阻断率：100%
平台写副作用次数：0
Core 平台耦合数：0
OpenAPI 业务字段完整率：100%（3/3）
TestClient API p95：17.64 ms（固定 Stub Service，500 次）
Webhook claim 原子语义：首次 True、重复 False，release 后允许重试
发布结果可观测字段完整率：100%（summary、inline、downgraded 3/3）
```

### 实现偏差与原因

```text
1. 除 learning_plan.md 指定的 API 测试外，新增 tests/review/test_review_ports.py，
   让平台模型约束和 DeliveryStore claim 语义拥有独立的确定性验证。
2. CodeReviewServiceErrorCode 增加 configuration_error，与现有 Diagnosis API 的配置错误
   结构保持一致，并稳定映射为 HTTP 503。
3. Review 和 Diagnosis 路由直接从 models/service 子模块导入类型，公共包仍保留惰性 Service
   导出，避免 models、prompts 和 service 的循环导入重新出现。
4. /reviews/code 保持同步 200 响应，没有引入 TaskManager 或 Publisher；平台发布协议只定义
   边界，不会被本地审查请求隐式触发。
```
