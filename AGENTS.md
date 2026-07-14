# AGENTS.md

## Project Overview

DevAgent is a local AI Agent runtime for developer productivity scenarios. The project should follow `plan.md` as the source of truth for architecture, milestone order, module boundaries, and learning/development direction.

The core goal is to build a reliable Agent backend with typed messages, tool calling, permission control, event/trace observability, RAG/Memory, evaluation, and controlled multi-agent orchestration.

## Tech Stack

- Python 3.11+
- Pydantic v2 for schemas and validation
- pytest for deterministic unit and integration tests
- pathlib for file path handling
- subprocess for restricted shell execution
- FastAPI for HTTP APIs and future WebSocket/SSE interfaces

## Planning Rules

- Use `plan.md` to decide what to build next. During daily development, record temporary implementation/plan gaps in the daily doc; update `plan.md` only after the weekly development cycle is complete unless the user explicitly asks for an immediate plan change.
- Keep daily learning docs aligned with the current milestone in `plan.md`; do not let daily docs introduce a separate roadmap.
- Keep `learning_plan.md` at milestone level: retain stage goals, daily scope, deliverables, and acceptance criteria; put API tutorials, detailed principles, implementation steps, and interview notes in the corresponding daily docs.
- After condensing or restructuring a planning range, audit every Day heading in the full affected week so adjacent days keep the same level of detail and no tutorial-style section is left behind.
- Do not add speculative infrastructure unless it supports a milestone, metric, or demo already described in `plan.md`.
- Prefer completing one vertical slice before expanding scope: model -> manager/service -> API/runtime integration -> tests -> docs.
- Every development change must include the corresponding daily or module-level documentation update when behavior, architecture, public API, workflow, or learning notes change.
- Update `plan.md` and `README.md` during weekly development wrap-up after the week's implementation, verification, and progress review are complete.
- A development task is not complete until code, tests, and docs are synchronized.

## Quantified Outcome Rules

- Describe feature outcomes with measurable engineering or product metrics whenever possible.
- Good metrics include retrieval latency, context token reduction, evidence hit rate, tool hit rate, false positive reduction, manual diagnosis time reduction, permission block rate, trace replay completeness, and API response latency.
- Do not present "tests passed" as the main project outcome. Tests are verification, not the user-facing or engineering impact.
- When adding RAG, Evaluation, CI diagnosis, log analysis, or trace features, define a baseline and a target metric before calling the feature complete.
- Example RAG targets:
  - Top-5 evidence hit rate reaches at least 80% on the local eval set.
  - Average context payload is reduced by at least 40% compared with full-file/log injection.
  - Manual evidence lookup steps for CI/log diagnosis are reduced by at least 30%.
  - Retrieval p95 latency stays below 800 ms on the local sample corpus.

## Coding Rules

- Keep core runtime logic independent from CLI or Web UI.
- Use typed Pydantic models for messages, tool calls, tool results, permissions, tasks, events, traces, and RAG records.
- Use Better Comments-style markers for explanatory inline comments: `# *` for important context, `# !` for warnings or safety constraints, `# ?` for questions that require confirmation, and `# TODO:` for concrete pending work. Use the equivalent comment syntax in non-Python files.
- Keep markers semantically meaningful; do not tag every comment. Continue to use docstrings for public APIs and longer contract documentation.
- Avoid putting provider-specific logic directly inside `AgentRuntime`.
- Tool execution must return a unified `ToolResult`.
- Never throw raw tool errors directly to the runtime loop.
- Path-related tools must prevent path traversal and stay inside the workspace.
- Shell tools must use timeout, cwd restriction, output truncation, and risk classification.
- High-risk tools must go through `PermissionManager` before runtime integration is considered complete.
- RAG tools must return evidence snippets with source, location, score, and enough metadata for evaluation.

## Testing Rules

- Run Python commands through the project virtual environment: `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/uvicorn`, or other `.venv/bin/...` entrypoints.
- Do not use system `python`, `pytest`, or `uvicorn` for this project unless the virtual environment is missing and the user explicitly asks for a fallback.
- When passing inline code or documentation text through a shell command, quote it so backticks, `$()`, and other shell substitutions cannot execute embedded commands.
- When documenting commands in daily docs, prefer the `.venv/bin/...` form so verification is reproducible.
- Add pytest tests for every new tool, manager, API route, runtime behavior, and RAG component.
- Test both success and failure cases.
- Mock LLM responses instead of calling real models in unit tests.
- Prefer small deterministic tests over large integration tests.
- For RAG and Evaluation, use fixed local fixtures so metrics are repeatable.

## Daily Documentation Rules

- Daily docs should include: goal, context, implementation scope, key design choices, verification, and measurable result.
- When daily development introduces or relies on unfamiliar APIs, framework primitives, or protocol concepts, add a short learning note explaining what it does, why it is used here, and the key behavior to remember. For example, document FastAPI `StreamingResponse` when building stream/SSE endpoints.
- After each development session, update the relevant daily doc or module docs with what changed and how it was verified.
- Keep `plan.md` and `README.md` for weekly progress synchronization, not per-day churn, unless the user explicitly requests an immediate update.
- Daily docs must not include a "today not doing" section.
- Daily docs must not include a preview or plan for tomorrow.
- If a boundary is important, write it as scope wording, not as a negative checklist.
- Daily docs should reference the relevant `plan.md` milestone when possible.

## Error Feedback Rules

- When the developer points out a mistake in implementation, planning, testing, documentation, or process, fix the immediate issue first.
- After fixing the issue, add a concise rule or clarification to `AGENTS.md` if the mistake could reasonably recur.
- The new rule should describe the prevention pattern, not just the specific incident.
- If the mistake only affects a narrow module, update the nearest module doc or daily doc as well as `AGENTS.md` when useful.
- Do not treat feedback as a one-off correction; fold durable lessons back into the project workflow.

## Git Commit Rules

- Use the format `<type>(<scope>): <Chinese summary>` for new commits.
- Use one of these types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, or `chore`.
- Use `dayXX` as the scope for a day's main learning/development delivery. For focused fixes or maintenance, use the module scope, such as `runtime`, `tools`, `rag`, `api`, or `agents`.
- Write a concise Chinese summary that states the completed behavior or outcome. Avoid vague subjects such as "update code" or "modify files", and do not end the subject with punctuation.
- Keep one commit focused on one complete topic. Include its code, tests, and corresponding daily or module documentation in the same commit.
- Add a commit body only when it helps explain an important design reason, migration note, or measurable outcome. Do not use test pass counts as the main outcome.
- Mark breaking changes with `!`, for example `refactor(runtime)!: 调整工具调用接口`.
- Examples: `feat(day37): 实现受限 Git 工具`, `fix(runtime): 修复工具异常未转换为 ToolResult`, and `docs(agents): 补充 Git 提交信息规范`.
- Treat `git push` as a separate action after committing. Run it only when the user explicitly requests a push; never invoke it through validation, command substitution, or an automated acceptance step.

## Design Preferences

- Keep abstractions simple first.
- Do not introduce LangChain unless there is a clear reason and `plan.md` is updated.
- Prefer explicit interfaces: `BaseTool`, `ToolRegistry`, `LLMClient`, `AgentRuntime`, `PermissionManager`, `EventStore/EventBus`, `TaskManager`, `Retriever`.
- Separate model provider adaptation from runtime message structure.
- Build RAG/Memory for evidence quality and context efficiency, not as a standalone demo.
