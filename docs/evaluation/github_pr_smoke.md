# GitHub Pull Request Smoke Test

## Purpose

This runbook validates the real GitHub App path after deterministic tests pass:

```text
GitHub pull_request webhook
  -> signature and delivery checks
  -> installation access token
  -> controlled local Git workspace
  -> CodeReviewService
  -> one summary comment and optional inline comments
```

Use a dedicated, non-sensitive public repository. The smoke test does not approve,
request changes, merge, commit, or push code.

## GitHub App Setup

Create a private GitHub App owned by your test account.

Repository permissions:

```text
Metadata: Read
Contents: Read
Pull requests: Read and write
```

Subscribe only to the `Pull request` event. Enable webhooks, keep SSL verification
enabled, and configure a high-entropy webhook secret.

Install the App only on the dedicated test repository. Download its private key to a
local path outside the repository.

## Test Repository

Create a small public repository such as `owner/devagent-review-smoke`, then clone it
to a dedicated local workspace:

```bash
git clone https://github.com/owner/devagent-review-smoke.git \
  /absolute/path/to/devagent-review-smoke
```

Create a feature branch containing one known, testable defect. A useful sample is a
function that accepts a destination path and writes outside the intended workspace
when passed `../outside.txt`. Add a failing or missing boundary test so the expected
finding has a clear file and diff line.

Push the branch and open a Pull Request against the default branch. Do not merge it.

## Local Configuration

Add these values to the local `.env`; never commit their real values:

```dotenv
DEVAGENT_GITHUB_WEBHOOK_SECRET=<same secret configured in the GitHub App>
DEVAGENT_GITHUB_APP_CLIENT_ID=<GitHub App client ID>
DEVAGENT_GITHUB_APP_PRIVATE_KEY_PATH=/absolute/path/to/app.private-key.pem
DEVAGENT_GITHUB_INSTALLATION_ID=<installation ID used only by the probe command>
DEVAGENT_GITHUB_ALLOWED_REPOSITORY=owner/devagent-review-smoke
DEVAGENT_GITHUB_WORKSPACE=/absolute/path/to/devagent-review-smoke
DEVAGENT_GITHUB_API_BASE_URL=https://api.github.com
DEVAGENT_ENABLE_GITHUB_SMOKE=1
DEVAGENT_GITHUB_SMOKE_FIXED_LLM=1
```

The normal webhook path reads `installation.id` from the signed payload. The explicit
installation ID is only needed by the read-only probe command.

## Preflight

Check local files without network access:

```bash
DEVAGENT_ENABLE_GITHUB_SMOKE=1 \
  uv run --locked python scripts/github_pr_smoke.py --check-config
```

Probe the real App token, Pull Request API, local fetch, and diff mapping without
publishing comments:

```bash
DEVAGENT_ENABLE_GITHUB_SMOKE=1 \
  uv run --locked python scripts/github_pr_smoke.py --pull-number <PR_NUMBER>
```

## Webhook Run

Start DevAgent:

```bash
uv run --locked uvicorn devagent.api.app:app --host 127.0.0.1 --port 8000
```

Expose port 8000 through an HTTPS forwarding service and configure the GitHub App
webhook URL as:

```text
https://<temporary-host>/api/v1/integrations/github/webhooks
```

When direct HTTPS tunneling is unavailable, GitHub's documented `smee.io` development
proxy is also suitable. Configure the GitHub App with the Smee channel URL, then point
`smee-client` at the complete local webhook URL. Smee returns its own response to
GitHub, so the DevAgent response body and `task_id` must be observed locally.

Restart DevAgent after changing `.env`. The real task manager is assembled lazily and
caches credentials and installation tokens in memory.

Run these three deliveries:

1. Open or reopen the Pull Request and verify `202 accepted`.
2. Push a second commit and verify the `synchronize` delivery updates the existing
   DevAgent summary comment.
3. Redeliver the same delivery from GitHub App settings and verify the response is
   `duplicate`, with no additional LLM call or comment.

Keep `DEVAGENT_GITHUB_SMOKE_FIXED_LLM=1` for the first opened / synchronize /
redelivery run. It produces a deterministic no-finding report and proves the real App
token, webhook, workspace, evidence, summary upsert, and delivery path independently
of the provider.

Then set `DEVAGENT_GITHUB_SMOKE_FIXED_LLM=0`, restart DevAgent, and redeliver using a
new delivery or push another commit. This second run uses the configured real provider
and should identify the known defect with a valid inline location.

After an accepted delivery, query its status and `report_id`:

```bash
curl http://127.0.0.1:8000/api/v1/integrations/github/review-tasks/<TASK_ID>
```

## Acceptance Record

Fill this section after the real run. IDs and URLs are safe to record; credentials are
not.

```text
Date: 2026-07-24
Repository / PR URL: https://github.com/Dracarys6/devagent-review-smoke/pull/1
Base SHA: 6d1dfea2c1a9dc38422d8e9f3ccdffd63811d7b1
Initial head SHA: 1b90aeea271b9e027528d3b64756451584cc0012
Updated fixed-LLM head SHA: 737585c92917d20fc6d05dbe4385a40f50f5455c
Final real-provider head SHA: 8f59dc6dbf1ee8e7db105b70fc0b642e733ecd96

Opened delivery GUID: 70fc3ee0-870d-11f1-82e5-3ca7890780ae
Opened task_id: not observable through the Smee proxy response
Opened report_id: e6fe12d3-7136-4391-94c4-ba008576a010

Synchronize delivery GUID: ac4f7890-870d-11f1-85dd-fe3d403cf3ec
Synchronize task_id: not observable through the Smee proxy response
Synchronize report_id: 9bb9d281-bcd0-4907-9896-968fcf97e1c0

Redelivery GUID: ac4f7890-870d-11f1-85dd-fe3d403cf3ec
Redelivery result: duplicate; summary ID, updated_at, and report_id remained unchanged

Real-provider delivery GUID: 316ad460-870f-11f1-967b-c9017f3862d1
Real-provider task_id: not observable through the Smee proxy response
Real-provider report_id: 3ce108d6-e7a1-455c-97f0-6a86f75b83ea
Diagnostic signed-replay task_id: 3b6305a5-72a3-4f83-8a51-acb84ea1bd38
Diagnostic signed-replay report_id: 019f6dcf-29cc-4be9-a67b-8b835c373193

Summary comment URL: https://github.com/Dracarys6/devagent-review-smoke/pull/1#issuecomment-5065772571
Inline comment URL(s): https://github.com/Dracarys6/devagent-review-smoke/pull/1#discussion_r3642731530
Summary comment count after synchronize: 1

Webhook to summary latency: reopened 5.7s; fixed synchronize 7.2s; real provider 37.2s
Evidence collection latency: fixed local p95 210.112ms; real stages not separately instrumented
LLM latency: 26.3s for a direct real-provider run on the same base/head evidence
Publishing latency: not separately instrumented

Fixed LLM result: reopened, synchronize, and redelivery passed; summary count stayed 1
Real provider result: one HIGH security finding at src/downloads.py:7 RIGHT
Final conclusion: passed; real GitHub webhook, App auth, PR evidence, model, summary
  upsert, inline publishing, and delivery deduplication were all exercised
```

One earlier real-provider delivery did not publish and could not be correlated to a
task because Smee hides the local response body. A signed local replay completed, and
the subsequent native GitHub `synchronize` delivery completed in 37.2 seconds. This
leaves delivery-to-task correlation and per-stage production timing as observability
improvements; it does not change the final end-to-end result.

Do not record the App private key, JWT, installation token, webhook secret,
Authorization header, or LLM API key.
