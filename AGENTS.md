# AGENTS.md

## Project Direction

DevAgent is a local AI Agent runtime for developer productivity. Build it as a reliable backend with typed messages, tool calling, permission control, event/trace observability, RAG/Memory, evaluation, and controlled multi-agent orchestration.

- Treat `plan.md` as the source of truth for architecture, milestone order, module boundaries, and development direction. Keep `learning_plan.md` aligned with it rather than creating a second roadmap.
- Prefer one complete vertical slice—model -> manager/service -> API/runtime integration -> tests -> docs—before expanding scope. Do not add infrastructure without a milestone, metric, or demo in `plan.md`.
- Before resuming work or starting a new day, inspect the current Git HEAD, working tree, and relevant files. Do not rely on repository state remembered from an earlier session.

## Delivery Workflow

- Default to Codex-led delivery: inspect, implement, test, synchronize relevant documentation, verify, and create one focused local commit.
- Synchronize code, tests, and documentation when behavior, architecture, public APIs, or workflows change. Documentation-only and non-behavioral changes do not require new tests.
- During daily development, update the relevant ignored daily learning document and any affected tracked module documentation. Update `plan.md` and `README.md` during weekly wrap-up unless the user requests an immediate change.
- Describe meaningful feature outcomes with the metrics defined in `plan.md` or the relevant evaluation document. Tests are verification evidence, not the primary product outcome.
- Before substantial implementation, explain the data flow, module boundaries, key tradeoffs, and failure or safety boundaries. Afterward, connect those points to the code, measurable behavior, likely interview questions, and one debugging or extension scenario.
- Keep one to three user-owned learning checkpoints for substantial development days. Use checkpoints for contracts, tradeoffs, failure analysis, critical tests, or manual acceptance—not mechanical scaffolding.

### Guided Development

Apply this subsection only when the user asks for step-by-step guidance:

- Inspect the current implementation and run the narrowest relevant test before proposing the next step.
- Give one dependency-ordered step at a time with its goal, principle, exact files, focused skeleton, and acceptance commands. Review the user's result before advancing.
- Make unfinished scaffolding explicit, for example with `NotImplementedError`; never let an incomplete method appear to succeed by returning `None`.

## Architecture and Safety Invariants

- Keep core runtime logic independent from CLI and Web UI. Keep provider-specific logic behind `LLMClient` or another adapter, never directly in `AgentRuntime`.
- Use Pydantic v2 models for messages, tool calls/results, permissions, tasks, events, traces, and RAG records. Prefer explicit interfaces such as `BaseTool`, `ToolRegistry`, `LLMClient`, `AgentRuntime`, `PermissionManager`, `EventStore/EventBus`, `TaskManager`, and `Retriever`.
- Every tool execution returns a unified `ToolResult`; convert underlying exceptions to structured errors instead of leaking raw tool errors into the runtime loop.
- Path tools must prevent traversal and remain inside the workspace. Shell tools must restrict `cwd`, enforce a timeout, truncate output, and classify risk.
- High-risk tools must pass through `PermissionManager`. External and MCP tools follow the same permission boundary when integrated.
- RAG tools return evidence snippets with source, location, score, and evaluation metadata. Optimize RAG/Memory for evidence quality and context efficiency, and evaluate retrieval separately from generated-answer quality.
- Keep abstractions simple. Do not introduce LangChain unless a concrete need is documented in `plan.md`.

## Comments and Public Contracts

- Use docstrings for public APIs and longer contracts. Use Better Comments markers selectively for explanatory inline comments: `# *` important context, `# !` safety warning, `# ?` confirmation needed, and `# TODO:` concrete pending work; use equivalent syntax outside Python.
- Preserve accurate comments that explain intent, non-obvious behavior, safety boundaries, or tradeoffs. Update or remove them only when outdated, incorrect, misleading, or truly redundant; convert useful unmarked comments in place when touching them.

## Environment and Tests

- Run Python commands through uv: `uv run python`, `uv run pytest`, and `uv run uvicorn`. Reproduce the environment with `uv sync --locked`; add dependencies with `uv add` or `uv add --dev` so `pyproject.toml` and `uv.lock` stay synchronized.
- Do not use system Python tools, invoke `.venv/bin/...` directly, or install with pip unless uv is unavailable and the user explicitly approves a fallback.
- For every behavior change, add or update focused pytest coverage for success and relevant failure/safety paths. Prefer small deterministic tests; mock LLM responses and use fixed local RAG/evaluation fixtures.
- Default pytest must not access real models or external platforms. Quote shell arguments containing inline code or documentation so backticks, `$()`, and similar syntax cannot execute unexpectedly.

## Real Integration Acceptance

- Test doubles prove deterministic contracts, failures, retries, and metrics; they do not prove a user-facing LLM or external-platform workflow is complete.
- Such workflows require both deterministic automated tests and an explicit end-to-end run through the real service, runtime, tools, provider/platform, and output validation path.
- Keep real network runs outside default pytest behind an explicit enable flag. Deterministically test the runner's configuration and error handling.
- Save a sanitized live report with provider/model, timestamp, case or target identifiers, latency, tool calls, schema validation, business metrics, and failures. Never save credentials, private repository contents, or unredacted secrets.
- Exercise the real platform path before declaring an external integration complete. If credentials, a test target, budget, or network access are missing, report “implemented; live acceptance pending” rather than treating mock evidence as completion.

## Documentation Boundaries

- Daily docs under the ignored `docs/learning/` path are local learning records. Update them when relevant, but never force-add or commit them unless the user explicitly asks to version them.
- A daily doc records the goal, context, scope, design choices, verification, measurable result, and short notes for unfamiliar APIs or concepts. Reference the relevant `plan.md` milestone; express boundaries as scope rather than “not doing” lists, and omit tomorrow previews.
- Keep `learning_plan.md` at milestone level; put tutorials, implementation steps, and interview notes in daily docs. After restructuring a planning range, audit every Day heading in the affected week for consistent detail.
- README and architecture diagrams must describe only implemented behavior and must distinguish deterministic coverage from completed live acceptance.

## Feedback and Rule Maintenance

- When the user identifies a mistake, fix it first and then preserve the prevention lesson at the narrowest useful scope.
- Add to this file only durable, project-wide invariants. Put module-specific lessons in the nearest module or daily document, and consolidate an existing rule instead of appending a duplicate.

## Git Commits

- After a functional unit is implemented, verified, and documented, create one focused local commit before starting the next feature. Stage only related tracked files; keep ignored daily docs local.
- Use `<type>(<scope>): <Chinese summary>` with `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, or `chore`. Use `dayXX` for a day's main delivery and a module name such as `runtime`, `tools`, `rag`, `api`, or `agents` for focused work.
- State the completed behavior or outcome concisely, without vague wording or trailing punctuation. Use `!` for breaking changes and add a body only for an important design reason, migration note, or measurable outcome.
- Treat `git push` as a separate, user-authorized action. Never push as part of validation or an automated acceptance step.
