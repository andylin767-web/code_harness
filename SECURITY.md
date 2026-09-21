# Security policy

## Reporting a vulnerability

Please use GitHub's private security-advisory workflow for vulnerabilities. Do
not include credentials, private prompts, raw traces, or exploit details in a
public issue.

## Secrets and local data

- Keep credentials in `.env` or the process environment. `.env` is ignored by Git.
- Reference MCP credentials as `${VARIABLE_NAME}` in `settings.json`.
- Treat `.code-harness/`, `traces/`, `.tasks/`, and `.mailboxes/` as private runtime data.
- Review trace files before sharing them; redaction is defense in depth, not a guarantee.
- If a secret is committed, revoke it first, then remove it from the complete Git history before publishing.

The CI workflow scans the full Git history with Gitleaks on every push and pull request.
