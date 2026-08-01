# GitHub Pull Request Review

GitHub sends a `pull_request` webhook with an `X-Hub-Signature-256` header. DevAgent
computes HMAC-SHA256 over the raw request body and uses a constant-time comparison
before parsing JSON.

Each accepted request also carries an `X-GitHub-Delivery` identifier. The delivery
store rejects redelivery as `duplicate`, preventing another model call or comment.

GitHub App authentication exchanges an App JWT for a short-lived installation token.
The App uses Metadata read, Contents read, and Pull requests write permissions.

Review findings are published with diff `line` and `side`. When a line cannot be
mapped reliably, the publisher falls back to the single updatable summary comment.
