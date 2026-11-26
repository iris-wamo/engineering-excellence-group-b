# CI/CD and Release Engineering

## Overview
How a change gets from a pull request to a running release in Session 06: the PR quality gate
that has to pass first, then one image built per commit on main, deployed by digest to
production after approval, smoke tested, and rolled back when it misbehaves.

## Topics Covered
- PR quality gate and required checks
- Workflow caching, version pinning and reproducibility
- Tagged image build, approved production deploy and rollback
- Migrations during release and rollback
- Secrets and environment configuration
- What a green pipeline does not prove

## Release: build once, deploy many (#124)

A green quality gate says the code passed its tests. It does not say the built image starts,
migrates and serves real requests. The release pipeline builds one image per commit, deploys
that same image to production after approval, smoke tests it there, and gives a fast way back.

There are two environments:

| Environment | Where | What it is for |
|---|---|---|
| **local** | your machine, `make release-deploy TAG=…` | run any published tag on a persistent stack, smoke test it, practise rollback and migrations |
| **production** | GitHub Actions, environment `production`, main only | every green commit on main, after approval |

### The pipeline

```
merge to main
  └─ Session quality gate (push run, one per commit)
       └─ release.yml (workflow_run, only when the gate passed)
            build      linux/amd64 + linux/arm64 on native runners, pushed by digest
            publish    one multi-arch image: ghcr.io/iris-wamo/taskflow-api:sha-<full sha>
            production release-deploy.yml: waits for approval, then runs that digest,
                       migrates and smoke tests it
git tag v1.2.3 (on a commit already built from main)
  └─ release.yml: adds :v1.2.3 to that commit's existing image (no rebuild)
```

| Piece | Where |
|---|---|
| Image build and publish | `.github/workflows/release.yml` |
| Production deploy, and production rollback (run by hand) | `.github/workflows/release-deploy.yml` |
| Release stack | `compose.release.yaml` |
| Local deploy and rollback | `scripts/release.sh`, `make release-deploy / rollback / release-status / release-down` |
| Smoke test | `scripts/smoke_test.py` (+ `docker/release/smoke-fixture.sql`), unit tests in `tests/unit/test_smoke_test.py` |
| Which build is serving | `GET /version` → `{"version", "git_sha", "environment"}` |

**Identity.** Every image is tagged `sha-<full commit sha>`, and the Dockerfile writes the
commit into the image (`GIT_SHA`, `APP_VERSION`, OCI labels). `GET /version` reports it, and the
smoke test fails if the container answering is not the build that was meant to be deployed.

**Deploys are by digest.** Tags can be moved; a digest (`repo@sha256:…`) cannot. Production
gets the digest `publish` printed, and the local stack pins whatever tag it is given to its
digest, so local and production run exactly the same bytes for the same tag. Only
configuration (environment variables) differs between them.

**Approval.** The `production` GitHub environment has a required reviewer, so the production job
waits in the Actions UI until it is approved, and it only accepts deployments from protected
branches (main). A newer run waiting for approval replaces an older waiting one, so the
approver always approves the latest green build.

**Production rollback.** Run *Release deploy* by hand (Actions → Release deploy → Run workflow,
from main) with the previous good tag, e.g. `sha-<previous commit>`. It goes through the same
approval and smoke test. Production here is simulated: each run gets a fresh runner, so its
database starts empty and disappears afterwards. The CI run proves the image migrates a fresh
database, starts and passes the smoke test; it cannot show rollback against existing data.

**Local, where rollback matters.** The local stack is persistent and uses the same script and
images:

```bash
cp .env.local.example .env.local             # then set real secrets (git-ignored)
make release-deploy TAG=sha-<git sha>        # pull, migrate, start on 127.0.0.1:8001, smoke test
make release-status                          # running / last good + what /version reports
make rollback                                # previous good digest, no migration
make release-down                            # stop it, keeping the data
```

It runs with `ENVIRONMENT=staging`, so it gets production-like settings (the dev JWT secret is
refused), and `/version` reports `staging`. `scripts/release.sh` records the image it last
started (`running`) and every image that passed the smoke test (`good`) in `.release/<env>/`.
A failed deploy exits non-zero, adds a `FAILED` line to `.release/history.log` and does not
roll back by itself, so a person sees the failure and the logs first. What it prints depends on
where it failed: before the api was replaced (starting the databases or migrating) the previous
release is still serving and there is nothing to roll back; once the new api has started (an
unhealthy api or a failed smoke test) it prints `make rollback` and the command for the api
logs. `running` is only written at that point, so it always names what the api really runs.

### The smoke test

A handful of real calls a user makes, against the deployed stack, in order (any failure stops
the run and fails the deploy):

1. sign up (idempotent) and log in, proving the account is ours (`signup` phase)
2. `docker/release/smoke-fixture.sql` gives the smoke user its project (see below)
3. `GET /version` answers and reports the expected commit (`check` phase from here)
4. a bad token gets `401` with the error envelope
5. log in, then `GET /auth/me` with the token
6. create a task, assign it to the smoke user, move it `todo → in_progress`
7. the task list shows the new status; a missing task gets `404` with the error envelope

Creating a project needs the admin role, and a fresh database has no admin, so
`docker/release/smoke-fixture.sql` gives the smoke user one dedicated project
(`release-smoke-test`). Smoke data stays in that project and is safe to ignore. Signup is
public, so anyone could register the smoke email first: the signup phase therefore only
continues if logging in with `SMOKE_PASSWORD` works, and the fixture never grants the project
to an account that is not ours (a pre-registered email fails the deploy instead).
`scripts/seed_data.py` is never used here: it truncates every table.

### Rollback and migrations

The image entrypoint runs `alembic upgrade head` before starting. That is convenient for
`make docker-up`, but it breaks rollback: the previous image does not contain the newer
migration file, so Alembic cannot even read the database's current revision. Reproduced:

```
$ docker run … taskflow-api:old           # after the new image migrated the database
ERROR [alembic.util.messaging] Can't locate revision identified by '0f0f0f0f0f0f'
FAILED: Can't locate revision identified by '0f0f0f0f0f0f'
exit 255                                   # with restart: unless-stopped, a crash loop
```

So the release stack does not use the entrypoint:

- **Deploy** runs migrations once, in the one-shot `migrate` service, *before* the
  new api starts. A failed migration stops the deploy with the old containers still running.
- **Rollback** starts the previous image with **no migration step**. The database stays on the
  newer schema, so this only works if the old code runs against it.

That is the rule every migration has to follow: **expand, then contract.** A release may only
*add* things the previous release can ignore (a nullable column, a new table, a new index).
Removing or renaming something the previous release still uses waits for a later release, once
the old code is out of service. Under that rule, rollback never needs a downgrade. Verified
locally: an image adding a nullable column was rolled back to the image before it, which ran
and passed the smoke test on the newer schema (`alembic_version` still at the new revision),
with every earlier row intact.

**When a downgrade is unavoidable** (the newer schema breaks the old code):

```bash
make rollback REV=<revision to go back to>
```

This first runs `alembic downgrade REV` with the **running (newer) image**, the only one that
contains the migration's `downgrade()`, then starts the previous image. Take a backup first:
downgrades that drop columns or tables lose the data written since the release, and some
upgrades (data migrations, enum value additions) cannot be fully reversed. The migration safety
checklist (`docs/session-03/migration-safety-checklist.md`) requires every migration's downgrade
to be tested, so this path exists, but it is the exception.

### Secrets and configuration

| What | Local | CI |
|---|---|---|
| Dev defaults (`make docker-up`, tests) | `.env` from `.env.example` | `.env` from `.env.example` |
| Release config | `.env.local` (from `.env.local.example`) | `.env.production`, written by `release-deploy.yml` from `.env.production.example` + the environment's secrets |
| `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `SMOKE_PASSWORD` | in `.env.local` | **secrets** of the `production` GitHub environment |
| Registry login | your `docker login ghcr.io` | `GITHUB_TOKEN` (`packages: write` only in the build jobs) |

Nothing secret is built into the image:

- every real `.env*` file is git-ignored and excluded by `.dockerignore`; the Dockerfile copies
  only `app/`, `packages/`, `alembic/`, `alembic.ini` and the virtualenv;
- the only build arguments are `GIT_SHA` and `APP_VERSION`;
- `Settings` refuses to start as `staging` or `production` with the dev `JWT_SECRET_KEY`.

Release stacks also turn off two development conveniences: `ALLOW_ANONYMOUS_DEFAULT_WORKSPACE`
is `false` (unauthenticated requests get `401` instead of acting in Workspace 1), and the api
port is published on `127.0.0.1` only. `/metrics` is served on that same port without a token
here; anywhere the api is reachable from outside, set `METRICS_TOKEN` as another environment
secret.

Checked on a built image: `docker image inspect` lists only the build identity and the Python
base image's variables (`GPG_KEY` there is the public key id of the CPython release signer),
`docker history` has no secret-like step, and there is no `.env` file anywhere in the image.

### What changes for a real production deployment

| Here | Real production |
|---|---|
| Compose on one machine or a throwaway runner | A managed runtime (ECS, Cloud Run, Kubernetes) pulling the same digest |
| Postgres, MongoDB, Redis containers with local volumes | Managed services with backups, point-in-time recovery, replicas |
| Restart the api (a few seconds of downtime) | Rolling or blue-green deploy behind a load balancer, health-check gated |
| Migrate, then start | Same order, as a one-off task; expand/contract becomes mandatory because old and new code run side by side during the rollout |
| Smoke test once after deploy | Smoke test plus automatic rollback on error-rate/latency alerts (the metrics from #125) |
| Secrets in GitHub environments / `.env.<env>` | A secret manager (Vault, AWS Secrets Manager) injected at runtime, rotated |
| One approver | Separate approvers from authors, change records, deploy windows |
| Tags pushed with `GITHUB_TOKEN` | Signed images (cosign), SBOMs, and admission policy that only runs signed digests |
