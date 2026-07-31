# AGENTS.md

## Scope

These rules apply to the `frontend/` directory. The root `AGENTS.md` still applies;
this file adds frontend-specific guidance.

## Stack and Boundaries

- Use React, TypeScript, and Vite. Keep TypeScript strict and avoid `any` unless an
  external boundary makes it unavoidable and the reason is documented.
- Keep backend contracts in `src/types.ts` and HTTP/SSE access in `src/api.ts`.
  Components must not duplicate endpoint construction or response parsing.
- Never expose LLM API keys or other server secrets to browser code. Provider
  credentials remain server-side environment variables.
- Treat the backend as the source of truth for tasks, traces, permissions, and
  diagnosis reports. Do not fabricate production-looking data in the UI.
- Prefer the existing React and CSS stack. Add a UI framework or state library only
  when its benefit clearly outweighs the added bundle and maintenance cost.

## Interface and Visual Rules

- Preserve the cool developer-console visual system: deep blue-gray surfaces,
  indigo primary actions, restrained violet accents, thin borders, and clear text
  contrast. Use color to communicate hierarchy or state, not as decoration alone.
- Keep the Agent result visually primary. Trace and raw event payloads are
  engineering details and should remain collapsible when a final result exists.
- Reuse CSS variables and existing component classes before introducing one-off
  colors or near-duplicate styles.
- Keep desktop information density while preserving the existing tablet and mobile
  breakpoints. Every layout change must be checked at narrow widths.
- Interactive controls need visible hover, focus, disabled, loading, empty, and
  error states where applicable.

## Verification and Documentation

- Run `npm run build` and `npm run lint` after every frontend behavior, type, or
  style change.
- Run `git diff --check` before committing.
- Update `docs/frontend.md` when frontend behavior, visual direction, API usage,
  setup, or architectural boundaries change.
- If a frontend change requires a backend contract change, verify the relevant
  `uv run --locked pytest` API tests as well as the frontend checks.

## Commit Habit

- After a coherent frontend change is complete and verified, create its focused
  commit in the same session instead of accumulating unrelated frontend work.
- Use the root commit format, normally `feat(frontend): <Chinese summary>`,
  `fix(frontend): <Chinese summary>`, or `refactor(frontend): <Chinese summary>`.
- Include the frontend code, related tests/configuration, `frontend/AGENTS.md`
  updates, and synchronized frontend documentation in the same commit.
- Inspect the worktree before staging and exclude unrelated user changes. Never use
  broad staging when other project files are already modified.
- A commit does not authorize `git push`; push only when the user explicitly asks.
