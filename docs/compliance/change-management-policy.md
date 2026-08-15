# Change Management Policy

**Status:** operational — this repository is the change record, and CI is the
gate. Every production-affecting change moves through the branch → PR → CI →
review → merge → release path below.

## 1. Policy

1. **No direct-to-main.** Production code, tests, and CI configuration change
   only through a pull request reviewed by someone other than the author.
2. **CI is a gate, not a suggestion.** A PR does not merge unless the full suite
   passes and the secrets scan is clean. WS-4 additionally gates on the
   `ws4-security` job against Postgres 16 (tenancy, RBAC, identity, audit).
3. **Evidence is preserved.** Every merge leaves the commit (its hash), the PR
   (its review trail), and the CI run (its report) in the repository. A bare
   "N passed" claim is never standalone — it references its commit/run.
4. **Secrets change is a secret change.** Adding/rotating any secret is a
   normal code change: a PR, reviewed, with the new secret delivered out of band
   (never in the PR body or the tree).
5. **Rollback is a normal change.** Reverting a bad merge uses the same path —
   a revert PR with its own CI run. There is no "hotfix directly to prod".

## 2. Branch strategy

- `main` is the only long-lived branch and the only releasable state.
- Work happens on short-lived feature branches (`ws4/<topic>`); PRs target `main`.
- A release is a git tag on `main` (see §4). Tags are immutable once pushed.

## 3. PR checklist (merged with the review)

- [ ] Full suite green (`pytest tests/`) at the merge commit.
- [ ] Secrets scan clean (`python scripts/secret_scan.py`).
- [ ] WS-4 changes additionally green on `ws4-security` (Postgres 16).
- [ ] `ruff check` and `ruff format --check` clean on changed packages.
- [ ] Cross-reference pass done where the diff touches numbers/definitions used
      in more than one place (thresholds, tier limits, N_min, contract hashes).
- [ ] No secrets or credential-shaped values in the diff or the PR body.

## 4. Release process

1. Cut a release branch from a green `main`, run the full suite once more at the
   exact release commit, and record the run's commit + result.
2. Tag `vX.Y.Z`, push the tag (immutable).
3. Build the Docker image from the tag (CI `docker` job) and record its digest.
4. Deploy the tagged image; the deploy step is itself recorded (runbook/log).

## 5. Change management in practice (what CI enforces)

| Change type | Requires | Enforced by |
|---|---|---|
| Code / tests / CI | PR + review + full suite + scans | `.github/workflows/ci.yml`, `.github/workflows/ws4-security.yml` |
| Secret add/rotate | PR + review, delivered out of band | secrets scan blocks committed secrets; review trail is the record |
| Doc changes (no code) | PR + review | repository review trail |
| Security fix | Same path; incident-response runbook applies if live | runbook + change management both recorded |

## 6. Exceptions

Exceptions are recorded as PRs themselves (documented deviation, reviewed, and
auditable). Emergency changes during an incident still go through a PR; the
incident-response runbook keeps the timeline honest while the normal gate runs.
