# AGENTS.md

## Project Overview

DevAgent is a local AI Agent runtime for developer productivity scenarios. The project should follow `plan.md` as the source of truth for architecture, milestone order, module boundaries, and learning/development direction.

The core goal is to build a reliable Agent backend with typed messages, tool calling, permission control, event/trace observability, RAG/Memory, evaluation, and controlled multi-agent orchestration.

## Tech Stack

- Python 3.11+
- uv for Python version, virtual environment, dependency, lockfile, and command management
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
- Preserve existing comments that remain accurate and useful, especially comments that explain design intent, non-obvious behavior, safety boundaries, or tradeoffs. Do not delete user-authored comments merely to simplify the file; update or remove them only when they are outdated, incorrect, misleading, or truly redundant.
- When an existing useful comment does not follow the Better Comments marker convention, preserve its meaning and convert the marker in place; formatting cleanup is not a reason to delete useful context.
- Avoid putting provider-specific logic directly inside `AgentRuntime`.
- Tool execution must return a unified `ToolResult`.
- Never throw raw tool errors directly to the runtime loop.
- Path-related tools must prevent path traversal and stay inside the workspace.
- Shell tools must use timeout, cwd restriction, output truncation, and risk classification.
- High-risk tools must go through `PermissionManager` before runtime integration is considered complete.
- RAG tools must return evidence snippets with source, location, score, and enough metadata for evaluation.

## Testing Rules

- Run Python commands through uv, for example `uv run python`, `uv run pytest`, and `uv run uvicorn`.
- Use `uv sync --locked` to reproduce the committed environment. Use `uv add <package>` for runtime dependencies and `uv add --dev <package>` for development-only dependencies so `pyproject.toml` and `uv.lock` stay synchronized.
- Do not use system `python`, `pytest`, or `uvicorn`, invoke `.venv/bin/...` directly, or install project dependencies with `pip` unless uv is unavailable and the user explicitly asks for a fallback.
- When passing inline code or documentation text through a shell command, quote it so backticks, `$()`, and other shell substitutions cannot execute embedded commands.
- When documenting commands in daily docs, prefer the `uv run ...` form so verification uses the locked project environment.
- Add pytest tests for every new tool, manager, API route, runtime behavior, and RAG component.
- Test both success and failure cases.
- Mock LLM responses instead of calling real models in unit tests.
- Prefer small deterministic tests over large integration tests.
- For RAG and Evaluation, use fixed local fixtures so metrics are repeatable.

## Real Integration Acceptance Rules

- Mocks, fixed responses, fake HTTP clients, and local fixtures are test doubles. They
  verify contracts, failures, retries, and deterministic metrics, but they are never
  sufficient evidence that a user-facing Agent workflow is complete.
- Every user-facing LLM workflow must have two separate acceptance layers:
  deterministic automated tests and an explicit live-provider end-to-end run through
  the real service, runtime, tools, and output validation path.
- A live-provider run must save a sanitized report containing the provider/model,
  timestamp, input case IDs or target identifiers, latency, tool calls, schema
  validation result, business metrics, and failed cases. Never save API keys, tokens,
  private repository contents, or unredacted secrets.
- Real network runs stay outside default pytest and require an explicit enable flag so
  routine development cannot spend money or mutate external systems accidentally.
  The runner and its configuration/error handling must still have deterministic tests.
- Do not mark an external integration complete until its real platform path has been
  exercised. For example, GitHub review completion requires a real test repository,
  webhook, installation token, model analysis, and comment publication; a fake client
  proves only the adapter contract.
- Evaluation must distinguish retrieval quality from generated-answer quality.
  RAG completion requires both deterministic retrieval metrics and live-provider answer
  metrics such as correctness proxies, grounded citations, abstention, latency, and
  context cost.
- If credentials, a test repository, budget, or network access prevent a live run,
  mark the capability as implemented but live acceptance pending. Never replace the
  missing evidence with a mock result or describe it as an optional nice-to-have.

## Daily Documentation Rules

- Keep files matched by the `docs/learning/` ignore rule as local learning records.
  Update them when required, but never use `git add -f` or otherwise include them in
  a commit unless the user explicitly asks to version ignored learning documents.
- Daily docs should include: goal, context, implementation scope, key design choices, verification, and measurable result.
- When daily development introduces or relies on unfamiliar APIs, framework primitives, or protocol concepts, add a short learning note explaining what it does, why it is used here, and the key behavior to remember. For example, document FastAPI `StreamingResponse` when building stream/SSE endpoints.
- After each development session, update the relevant daily doc or module docs with what changed and how it was verified.
- Keep `plan.md` and `README.md` for weekly progress synchronization, not per-day churn, unless the user explicitly requests an immediate update.
- Daily docs must not include a "today not doing" section.
- Daily docs must not include a preview or plan for tomorrow.
- If a boundary is important, write it as scope wording, not as a negative checklist.
- Daily docs should reference the relevant `plan.md` milestone when possible.

## Interview-Driven Development Rules

- Default to Codex-led delivery: inspect the existing design, implement the complete
  vertical slice, add tests, synchronize documentation, verify the result, and create
  the focused local commit.
- Reserve one to three user-owned checkpoints per development day for work with high
  learning value. Good checkpoints include defining a core contract, explaining a
  design tradeoff, interpreting a failing test or trace, completing one critical test,
  or manually exercising an API. Do not hand off repetitive scaffolding or mechanical
  edits merely to create user work.
- Before a substantial implementation, explain the problem, data flow, module
  boundaries, chosen design, important alternatives, and failure or safety boundaries
  that are likely to be challenged in AI Agent or backend interviews.
- After implementation, connect the explanation to real code and measurable behavior.
  Include likely interview questions, concise answer points, and at least one debugging
  or extension scenario when the feature is substantial.
- Do not pause after every implementation step by default. Group mechanical work and
  pause only at a planned learning checkpoint, when a decision genuinely needs user
  input, or when the user explicitly requests guided development.
- Treat the user's ability to explain the data flow, tradeoffs, edge cases, test
  strategy, and relevant performance, reliability, observability, or security metrics
  as part of daily acceptance.
- Adapt the emphasis to the current module: Agent runtime, tool calling, RAG, memory,
  evaluation, and multi-agent work should foreground AI Agent interview depth, while
  APIs, persistence, concurrency, security, and operations should foreground backend
  engineering depth.

## Guided Development Rules

- When the user asks for step-by-step development guidance, inspect the current
  implementation and run the narrowest relevant test before proposing the next step.
- Break the daily task into dependency-ordered, independently verifiable steps. Give
  one active step at a time with its goal, relevant principle, exact files, focused
  code skeleton, and acceptance commands.
- Review the user's result from the previous step before advancing. Do not silently
  complete later steps or overwhelm the learning flow with the entire final solution.
- Keep temporary scaffolding explicit, for example with `NotImplementedError`, so an
  unfinished method cannot appear to succeed by returning `None`.

## Error Feedback Rules

- When the developer points out a mistake in implementation, planning, testing, documentation, or process, fix the immediate issue first.
- After fixing the issue, add a concise rule or clarification to `AGENTS.md` if the mistake could reasonably recur.
- The new rule should describe the prevention pattern, not just the specific incident.
- If the mistake only affects a narrow module, update the nearest module doc or daily doc as well as `AGENTS.md` when useful.
- Do not treat feedback as a one-off correction; fold durable lessons back into the project workflow.

## Git Commit Rules

- After each functional unit is implemented, verified, and synchronized with its corresponding documentation, create a local Git commit before starting the next feature. Stage only files related to that completed unit; do not include incomplete or unrelated working-tree changes.
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
