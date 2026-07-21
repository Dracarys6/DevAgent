# LLM 与 OpenAI API 适配

## 目标与上下文

DevAgent 的 `AgentRuntime` 只依赖内部 `LLMClient.chat(messages) -> LLMResponse`
协议。供应商请求格式、工具 schema 和响应解析都留在 `devagent.llm` 适配层，避免
Chat Completions 或 Responses API 的对象进入 Runtime。

本模块在保留原有 OpenAI-compatible Chat Completions 的基础上，增加 OpenAI
Responses API。它对齐 `plan.md` 的可靠 Agent Runtime 与受控工具编排目标，不改变
Runtime、ToolRegistry、ToolResult 或权限边界。

## 配置

复制安全模板：

```bash
cp .env.example .env
```

可用环境变量：

| 环境变量 | 作用 | 默认值 |
| --- | --- | --- |
| `DEVAGENT_LLM_API_KEY` | LLM API key；缺失时回退 `OPENAI_API_KEY` | 无 |
| `DEVAGENT_LLM_MODEL` | 模型 ID | 无 |
| `DEVAGENT_LLM_BASE_URL` | SDK base URL，兼容网关通常需要包含 `/v1` | OpenAI SDK 默认地址 |
| `DEVAGENT_LLM_API_MODE` | `chat_completions` 或 `responses` | `chat_completions` |
| `DEVAGENT_LLM_REASONING_EFFORT` | 可选 reasoning effort | 使用模型默认值 |

GPT-5.6 Agent 推荐配置：

```dotenv
DEVAGENT_LLM_API_KEY=你的密钥
DEVAGENT_LLM_MODEL=gpt-5.6-luna
DEVAGENT_LLM_BASE_URL=https://api.openai.com/v1
DEVAGENT_LLM_API_MODE=responses
DEVAGENT_LLM_REASONING_EFFORT=medium
```

使用第三方 OpenAI-compatible 网关时，以网关文档为准替换 `BASE_URL`。如果它要求
`/v1/chat/completions` 或 `/v1/responses`，`DEVAGENT_LLM_BASE_URL` 必须以 `/v1`
结尾。修改 `.env` 后应重启 DevAgent；项目使用 `load_dotenv(..., override=False)`，
运行中进程不会覆盖已加载的同名环境变量。

CLI 可以临时覆盖模式和 reasoning：

```bash
.venv/bin/devagent "请分析项目" \
  --workspace . \
  --provider real \
  --model gpt-5.6-luna \
  --api-mode responses \
  --reasoning-effort medium
```

## 两种 API 模式

| 模式 | 使用场景 | 工具调用表示 | 结构化输出参数 |
| --- | --- | --- | --- |
| `chat_completions` | DeepSeek 等兼容接口、旧调用链 | `assistant.tool_calls` + `tool` message | `response_format` |
| `responses` | GPT-5.6 reasoning、工具调用和新 OpenAI 工作流 | `function_call` + `function_call_output` | `text.format` |

默认值仍是 `chat_completions`，避免升级时改变现有兼容供应商行为。GPT-5.6 在 Chat
Completions 中携带 function tools 时，如果没有配置 reasoning，适配器会显式发送
`reasoning_effort="none"`；如果显式配置为其他值，会在发起网络请求前提示改用
Responses API。

Responses 适配器使用 `store=False`，沿用项目原有的本地消息历史策略。模型返回的
reasoning items、function calls 和 call IDs 会保存在 assistant metadata 中，下一轮按
原始 output items 重放；工具结果转换为 `function_call_output`。这样不会只保留文本而
丢失 GPT 多轮工具推理所需的关联信息。

代码评审设置的输出 token 上限在两种模式中分别映射为：

- Chat Completions：`max_tokens`
- Responses：`max_output_tokens`

## 响应与错误契约

Chat Completions 解析 `choices[0].message`；Responses 解析 `output` 中的
`function_call` 或 message `output_text`，并兼容 refusal 文本。

适配层会拒绝以下情况并让 Runtime 进入 `llm_error`：

- Chat 端点返回 HTML/字符串，例如 base URL 缺少 `/v1`；
- Chat 响应没有 `choices` 或 `message`；
- Responses 状态不是 `completed`；
- Responses 缺少 `output`、`output_text` 和 `function_call`；
- 工具 arguments 不是 JSON object；
- API mode 或 reasoning effort 配置无效。

诊断和代码评审 API 会把无效 LLM 配置映射为 `configuration_error`，避免返回无上下文
的 500 错误。错误信息不包含 API key 或完整供应商响应。

## 验证与可量化结果

基线问题是只有一种 Chat 响应解析器，Responses 返回没有 `choices` 时必然失败，且错误
无法区分协议不匹配与 base URL 路由错误。

本次目标与结果：

| 指标 | 基线 | 目标与结果 |
| --- | --- | --- |
| 支持的 OpenAI 文本 API 契约 | 1 种 | 2 种：Chat Completions + Responses |
| 两轮工具上下文关联完整率 | Responses 不可用 | 固定夹具中 reasoning/function call/call ID/tool output 重放率 100% |
| GPT-5.6 Chat tools reasoning 冲突 | 请求后由远端报错 | 网络请求前 100% 拦截显式非 `none` 配置 |
| HTML 错路由诊断 | `缺少 choices` | 明确提示检查 base URL 与 `/v1` 前缀 |
| 单元测试外部模型调用 | 无明确 Responses 覆盖 | 全部使用固定 fake response，真实 key 调用次数为 0 |

复现验证：

```bash
.venv/bin/pytest tests/llm/test_openai_client.py -q
.venv/bin/pytest tests/task/test_manager.py tests/cli/test_cli.py -q
.venv/bin/pytest tests/api/test_diagnoses.py tests/api/test_reviews.py -q
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
git diff --check
```

## 学习说明：Responses API

Responses API 的 `output` 是有类型的 item 列表，而不是 Chat Completions 的
`choices[0].message`。工具调用 item 使用 `call_id` 将模型生成的 `function_call` 与应用
回传的 `function_call_output` 关联。对于 reasoning 模型，多轮手工管理上下文时还需要
保留相关 output items；只把最终文本重新拼成普通 assistant message 会丢失工具和推理
状态。

参考 OpenAI 官方文档：

- [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Responses API create reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
