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
  .venv/bin/python scripts/github_pr_smoke.py --check-config
```

Probe the real App token, Pull Request API, local fetch, and diff mapping without
publishing comments:

```bash
DEVAGENT_ENABLE_GITHUB_SMOKE=1 \
  .venv/bin/python scripts/github_pr_smoke.py --pull-number <PR_NUMBER>
```

## Webhook Run

Start DevAgent:

```bash
.venv/bin/uvicorn devagent.api.app:app --host 127.0.0.1 --port 8000
```

Expose port 8000 through an HTTPS forwarding service and configure the GitHub App
webhook URL as:

```text
https://<temporary-host>/api/v1/integrations/github/webhooks
```

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
Date:
Repository / PR URL:
Base SHA:
Initial head SHA:
Updated head SHA:

Opened delivery GUID:
Opened task_id:
Opened report_id:

Synchronize delivery GUID:
Synchronize task_id:
Synchronize report_id:

Redelivery GUID:
Redelivery result:

Summary comment URL:
Inline comment URL(s):
Summary comment count after synchronize:

Webhook to summary latency:
Evidence collection latency:
LLM latency:
Publishing latency:

Fixed LLM result:
Real provider result:
Final conclusion:
```

Do not record the App private key, JWT, installation token, webhook secret,
Authorization header, or LLM API key.
