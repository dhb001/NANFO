# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities **privately**. Do not open a public issue,
pull request, discussion or commit that describes the problem.

1. **Preferred:** GitHub private vulnerability reporting — on the repository page open
   **Security → Advisories → Report a vulnerability**. The report stays visible only to
   you and the maintainers and becomes a draft security advisory.
   GitHub offers this form only on public repositories where the owner enabled it
   (Settings → Code security → Private vulnerability reporting).
2. **While that form is unavailable** (for example while the repository is private),
   contact the maintainer, [@dhb001](https://github.com/dhb001), through GitHub and ask
   for a private channel before sharing details.

Please include the affected component and commit, reproduction steps, the impact you
expect, and whether the issue is already public. Never include real credentials,
tokens, personal data or private research evidence; describe them or redact them.

What to expect: an acknowledgement within 5 working days, an initial assessment within
10 working days, and coordinated disclosure once a fix or mitigation is available.
We credit reporters in the advisory unless you prefer otherwise.

## Supported versions

NANFO has no versioned releases yet. Only the latest commit on `main` is supported and
receives security fixes. Historical research artifacts are **frozen evidence**, not
supported software (see *Scope*).

| Version | Supported |
| --- | --- |
| `main` (latest commit) | Yes |
| Older commits, campaign source snapshots (`nanfo-experimental-campaign-*/source`) | No |

## Scope

In scope:

- Backend API, WebSocket gateway, workers and database migrations (`backend/`).
- Frontend application (`frontend/`).
- Deployment stack, gateway and container images (`deploy/`, `backend/docker-compose.yml`).
- CI workflows, supply-chain pins and repository security policy (`.github/`, `security/`,
  `scripts/`).
- The AI engine and emulation code paths used by current, non-frozen runtimes.

Out of scope, or accepted with documented compensating controls:

- **Frozen runtimes** that ADR-028 §1 forbids changing (the historical lab image and its
  pinned requirements, the qualified AI runtime including `torch 2.8.0+cpu`). Their
  known advisories, owners, expiries and successor plans are recorded in
  [`security/dependency-exceptions.v1.json`](security/dependency-exceptions.v1.json);
  they run only in isolated, operator-owned environments.
- **71 expired receiver tokens** that remain in Git history (commit `3f9f1f1`). They were
  removed from the tree, are no longer valid, and are the only credentials the history
  scan accepts (`.gitleaks.toml`); its other accepted findings are individually reviewed
  false positives, pinned to exact historical commits in `.gitleaksignore` or allowlisted
  by exact file and exact expression in `.gitleaks.toml`. Purging the
  tokens from history is an owner action (ADR-028 §5).
- Findings that require a compromised operator host, a malicious lab switch or a
  tampered, hash-verified checkpoint supplied by the operator.
- Denial of service from unbounded traffic against a local development stack.

## How the repository protects itself

- CI gates (`.github/workflows/`): locked dependency audits with expiring, reviewed
  exceptions; tracked-file evidence/credential scanning; a full-history `gitleaks` scan;
  container image scanning (`trivy`) and Dockerfile linting; full-SHA pinned actions.
- Required status checks on `main` are prepared in
  [`.github/rulesets/main.json`](.github/rulesets/main.json); see
  [CONTRIBUTING.md](CONTRIBUTING.md#branch-protection-owner-action) for how the owner
  applies them.
- Secrets are generated locally (`scripts/dev-start.sh`, mode 0600) or staged into
  per-service volumes in deployment; they are never committed.
