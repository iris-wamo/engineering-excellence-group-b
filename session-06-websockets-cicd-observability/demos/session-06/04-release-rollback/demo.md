# Demo 04 — Release and Rollback

## Loom Video
- **Loom Link**: `[Manual follow-up: insert the Loom URL once recorded]`
- **What to record (2–3 min)**: a merge producing a `sha-<commit>` image in GHCR, the production
  job waiting for approval and passing, then on the local stack a bad release caught by the
  smoke test and `make rollback` bringing the previous version back.

## Objective
Show that a release is one known image, deployed the same way locally and to production, and
that a bad release is caught before anyone relies on it and can be undone in one command,
including across a database migration. Design and reasoning: `docs/session-06/ci-cd.md`
(Release).

Two environments: **local** (your machine, persistent, `make release-deploy`) and
**production** (GitHub Actions on main, after approval).

## Steps

```bash
cp .env.local.example .env.local         # set real secrets
make release-deploy TAG=sha-<git sha>    # pull, migrate, start, smoke test
make release-deploy IMAGE=<bad image>    # deliberately broken release
make rollback                            # previous good digest, no migration
make release-status
```
Production: merge to main → approve the *production* job. Production rollback: Actions →
*Release deploy* → Run workflow with `tag: sha-<previous good commit>`.

## Evidence: CI (after merge)
- **Image tags in GHCR**: `[Manual follow-up: link the package page / list the sha-<commit> tags]`
- **Release run** (build → publish → approval → production): `[Manual follow-up: run URL]`
- **Production rollback run** (Release deploy, run by hand with the previous tag): `[Manual follow-up: run URL]`

## Evidence: local release stack (2026-11-26)

Test images, built from this branch with distinct `GIT_SHA` build args:

| Image | What it is | Digest (prefix) |
|---|---|---|
| `good-1` | this branch | `7b4bc8ae2e38` |
| `migr-2` | `good-1` plus a migration adding a nullable `task.release_note` column | `775ec446a2ca` |
| `bad-3` | `migr-2` with `todo → in_progress` removed from the workflow rules. It boots and answers `/version`; only real use shows the bug | `8b32277f014e` |

The local stack runs with `ENVIRONMENT=staging` (production-like settings), which is what
`/version` reports below.

### 1. Why the entrypoint cannot be used for rollback
After `migr-2` migrated the database, starting `good-1` with the image's normal entrypoint:
```
ERROR [alembic.util.messaging] Can't locate revision identified by '0f0f0f0f0f0f'
FAILED: Can't locate revision identified by '0f0f0f0f0f0f'
exit 255
```
The release stack therefore migrates in a separate one-shot `migrate` service and skips it on
rollback.

### 2. Deploy a release with a migration
```
$ make release-deploy IMAGE=taskflow-api:migr-2
==> [local] deploying taskflow-api@sha256:775ec446a2ca… (git sha: 2222222222222222222222222222222222222222)
==> [local] alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade cbf85300077c -> 0f0f0f0f0f0f, repro: add a nullable column (rollback demo only)
==> [local] smoke test
  [PASS] smoke user exists (signup)
  [PASS] login as the smoke user returns a token
  [PASS] GET /version answers
         serving {'version': 'migr-2', 'git_sha': '2222222222222222222222222222222222222222', 'environment': 'staging'}
  [PASS] serving the expected build (222222222222)
  [PASS] a bad token is rejected with 401 and the error envelope
  [PASS] login as the smoke user returns a token
  [PASS] GET /auth/me with the token
  [PASS] create a task
  [PASS] assign the task to the smoke user
  [PASS] change the task status todo -> in_progress
  [PASS] list tasks shows the task with its new status
  [PASS] a missing task answers 404 with the error envelope
Smoke test passed (10 checks)
==> [local] released taskflow-api@sha256:775ec446a2ca…
```

### 3. A bad release caught by the smoke test
```
$ make release-deploy IMAGE=taskflow-api:bad-3
==> [local] deploying taskflow-api@sha256:8b32277f014e… (git sha: 3333333333333333333333333333333333333333)
         serving {'version': 'bad-3', 'git_sha': '3333333333333333333333333333333333333333', 'environment': 'staging'}
  [PASS] serving the expected build (333333333333)
  [FAIL] change the task status todo -> in_progress (HTTP 400: {'error': {'code': 'INVALID_STATUS_TRANSITION', 'message': 'Cannot transition task from todo to in_progress', ...}})
Smoke test FAILED after 7 passing check(s)
==> [local] DEPLOY FAILED: taskflow-api@sha256:8b32277f014e… is running but did not pass.
    Last good release: taskflow-api@sha256:775ec446a2ca…
    Roll back:  make rollback
```
The deploy exited non-zero, and `bad-3` was never added to the good list, so no rollback can
ever pick it.

### 4. Rollback to the previous version
```
$ make rollback
==> [local] rolling back from taskflow-api@sha256:8b32277f014e… to taskflow-api@sha256:775ec446a2ca…
==> [local] skipping migrations (rollback: this image may not know the newest revision)
  [PASS] serving the expected build (222222222222)
Smoke test passed (10 checks)
```

### 5. Rollback across a migration (expand/contract)
Rolling back again, from `migr-2` to `good-1`, leaves the newer schema in place:
```
$ make rollback
==> [local] rolling back from taskflow-api@sha256:775ec446a2ca… to taskflow-api@sha256:7b4bc8ae2e38…
==> [local] skipping migrations (rollback: this image may not know the newest revision)
         serving {'version': 'good-1', 'git_sha': '1111111111111111111111111111111111111111', 'environment': 'staging'}
Smoke test passed (10 checks)
```
The old code ran on the newer schema. Redeploying `migr-2` afterwards ran `alembic upgrade
head` with nothing to do: the database had stayed at `0f0f0f0f0f0f` through the rollback.

### 6. Rollback with a downgrade (the exception)
```
$ make rollback REV=cbf85300077c
==> [local] alembic downgrade cbf85300077c, using the running image taskflow-api@sha256:775ec446a2ca…
INFO  [alembic.runtime.migration] Running downgrade 0f0f0f0f0f0f -> cbf85300077c, repro: add a nullable column (rollback demo only)
==> [local] rolling back from taskflow-api@sha256:775ec446a2ca… to taskflow-api@sha256:7b4bc8ae2e38…
Smoke test passed (10 checks)

alembic_version: cbf85300077c   task rows: 7 (every smoke task kept)   task.release_note: dropped
```

### 7. Nothing secret in the image
```
$ docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' taskflow-api:good-1
PATH=/app/.venv/bin:...   LANG=C.UTF-8   GPG_KEY=7169605F…(CPython signer, public)
PYTHON_VERSION=3.12.16    PYTHON_SHA256=…  PYTHONDONTWRITEBYTECODE=1  PYTHONUNBUFFERED=1
APP_VERSION=good-1        GIT_SHA=1111111111111111111111111111111111111111
$ docker history --no-trunc … | grep -iE "secret|password|token|jwt"   → nothing
$ ls -a /app → .venv alembic alembic.ini app packages;   no .env file anywhere in the image
```

## What we learned
1. **"The image starts" is not "the release works".** `bad-3` booted, migrated and answered
   `/version`; only a real user action (changing a status) showed it was broken.
2. **Rollback is a property of the migrations, not of the deploy script.** Redeploying the old
   image is easy; it only works if that image can run on the newer schema. Expand/contract makes
   rollback a plain redeploy; anything else needs a downgrade, a backup and luck.
3. **Running migrations in the entrypoint couples "start" to "migrate".** Fine for local
   development, but the previous image cannot start at all once the database is ahead of it.
4. **Pin by digest.** A tag says what a build was called; a digest says what it is. Promotion
   and rollback both use digests so nothing can change under them.

## Open questions
1. Should a failed deploy roll back automatically? Today it stops and prints the command, so a
   person sees the failure first. With real traffic, automatic rollback on a failed smoke test
   (and on error-rate alerts from #125) would shorten the outage.
2. The smoke user and its project live in production (and on the local stack). Is a dedicated synthetic tenant (its own
   workspace) worth adding so smoke data never shows up next to real projects?
