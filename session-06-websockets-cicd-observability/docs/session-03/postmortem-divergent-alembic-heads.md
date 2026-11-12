# Post-Mortem Report: Divergent Alembic Migration Heads on `main`

| Metadata | Details |
|---|---|
| **Incident ID / Issue** | [#76](https://github.com/iris-wamo/engineering-excellence-group-b/issues/76) / [PR #77](https://github.com/iris-wamo/engineering-excellence-group-b/pull/77) |
| **Date** | 2026-10-01 |
| **Severity** | High (Deployment & Dev Setup Blocker) |
| **Components Affected** | Alembic Migrations, Docker Entrypoint, Database Setup |
| **Status** | Resolved & Verified |
| **Lead Engineer** | Suhaib Ahmad (`suhaibahmad-dev-wamo`) |

---

## 1. Executive Summary

Following the merge of all Session 03 feature PRs (#59, #60, and #65) into the `main` branch, the migration graph diverged into **3 independent heads** (`cd823c0995ed`, `5c60a4a4906c`, `f7715786b494`).

Because Alembic requires a single unambiguous target revision when invoking `upgrade head`, executing `alembic upgrade head`, `make migrate`, and container startup via `docker/entrypoint.sh` threw fatal errors:
```text
FAILED: Multiple head revisions are present for given argument 'head';
please specify a specific target revision, '<branchname>@head' to narrow to a specific head, or 'heads' for all heads
```

This blocked local developer onboarding, fresh Docker container deployments, and the clean directory fork for `session-04`. The issue was resolved by linearizing the revisions into a single dependency chain and verifying full rollback and backfill compatibility on seeded data.

---

## 2. Root Cause Analysis (The 5 Whys)

1. **Why did `alembic upgrade head` fail on `main`?**
   Alembic detected multiple competing head revisions (`cd823c0995ed`, `5c60a4a4906c`, `f7715786b494`) instead of a single linear tip.

2. **Why were multiple heads present?**
   Three separate feature branches each introduced a new migration file, but all three migrations declared `down_revision = "aae8fcd27de6"` (or branched from an earlier point) independently.

3. **Why did git merge not flag this as a conflict?**
   Alembic migration files use timestamped/unique filenames (e.g. `2026_09_12_...py`, `2026_09_24_...py`). Because distinct files were created in the `alembic/versions/` directory, Git considered each file an independent addition and completed clean, non-conflicting merges into `main`.

4. **Why weren't the branches rebased on top of `main`'s latest migration before merging?**
   PRs were reviewed and merged in parallel without verifying the global migration graph state (`alembic heads`) at the time of merge.

5. **Why did CI/pre-commit checks not catch the multiple heads?**
   Existing pre-commit hooks and CI pipelines ran code formatting (`ruff`), type checking (`mypy`), and unit tests (`pytest`). The test suite creates schema directly via `Base.metadata.create_all` in `conftest.py` rather than running Alembic migrations, so tests passed despite broken migration history.

```
                    ┌── PR #59 ──> 096305ddb2ff ──> cd823c0995ed (HEAD 1)
                    │
aae8fcd27de6 (base) ├── PR #65 ───────────────────> 5c60a4a4906c (HEAD 2)
                    │
                    └── PR #60 ───────────────────> f7715786b494 (HEAD 3)
```

---

## 3. Impact Assessment

- **Developer Environment**: Running `make migrate` failed immediately with error code 255.
- **Docker Deployment**: `docker/entrypoint.sh` executes `alembic upgrade head` before booting `uvicorn`. Any fresh container build or wipe (`docker compose down -v && docker compose up`) failed during entrypoint execution.
- **Session 04 Handover**: The team was preparing to branch/fork `session-04-shared-backend-domain-rbac` from `session-03`. Forking with divergent migration heads would have propagated the broken migration chain into Session 04.

---

## 4. Resolution & Linearization Strategy

The team evaluated two resolution patterns:

| Option | Approach | Tradeoffs | Verdict |
|---|---|---|---|
| **A. Alembic Merge Revision** | Run `alembic merge heads` to create a 6th merge migration file joining all 3 heads. | Leaves a branching/diamond graph in history; complicates step-by-step rollbacks (`downgrade -1`). | Rejected |
| **B. Revision Linearization** | Chain the existing 5 migrations into a single, chronological, and logical linear sequence. | Requires updating `down_revision` pointers in 2 files, but produces a clean, predictable, single-line timeline. | **Adopted** |

### Selected Linearized Timeline

```
<base> ──> aae8fcd27de6 ──> 096305ddb2ff ──> cd823c0995ed ──> 5c60a4a4906c ──> f7715786b494 (head)
```

1. **`aae8fcd27de6`**: Base schema (`project`, `user`, `project_user`, `task`).
2. **`096305ddb2ff`**: History/audit tables (`activity_log`, `notification`, `task_assignment_history`, `task_status_history`).
3. **`cd823c0995ed`**: Project slug 3-phase backfill & check constraints (kept immediately after `096305ddb2ff` per [Demo 02](demos/02-alembic-migrations/demo.md) documentation).
4. **`5c60a4a4906c`**: Raw MongoDB task import linkage column (`task.mongo_import_id`).
5. **`f7715786b494` (HEAD)**: Composite index (`ix_task_status_priority_id` on `task`). Positioned at `head` to preserve [Demo 03](demos/03-index-explain-analyze/demo.md) workflow where `downgrade -1` removes the index and `upgrade head` re-applies it.

---

## 5. Verification & Test Evidence

| Verification Step | Command Run | Expected Result | Actual Outcome |
|---|---|---|---|
| **Single Head Verification** | `uv run alembic heads` | Exactly 1 head (`f7715786b494`) | `f7715786b494 (head)` — **PASS** |
| **Full History Linear Graph** | `uv run alembic history` | Single line without branched forks | 5 sequential steps from `<base>` to `head` — **PASS** |
| **Complete Rollback Reversibility** | `uv run alembic downgrade base` | Clean schema teardown to empty DB | All 5 migrations dropped cleanly — **PASS** |
| **Clean Forward Execution** | `uv run alembic upgrade head` | Sequential execution of 5 migrations | Upgraded `base` -> `f7715786b494` cleanly — **PASS** |
| **3-Phase Backfill on Populated Data** | `make seed` + `downgrade 096305ddb2ff` + `upgrade head` | Slugs safely backfilled on existing projects | All 5 projects backfilled (`taskflow-backend-mvp-1`, etc.) without null violations — **PASS** |
| **Zero Schema Drift Check** | `uv run alembic check` | 100% sync between ORM models and DB schema | `No new upgrade operations detected` — **PASS** |
| **Application Test Suite** | `uv run pytest` | All service and API tests pass | `69 passed in 2.94s` — **PASS** |

---

## 6. Preventative Action Items & Recommendations

To prevent future migration divergency when teams work across parallel PRs:

1. **Automated CI Migration Check**:
   - Add a step to the PR CI pipeline:
     ```bash
     uv run alembic heads | wc -l
     ```
     Ensure output is exactly `1`. If greater than 1, fail the build with a descriptive error: *"Multiple Alembic heads detected. Please rebase migration on current main head."*
2. **Migration Smoke Test in Test Suite**:
   - In addition to `Base.metadata.create_all`, add a test fixture or test case that runs `alembic upgrade head` and `alembic downgrade base` in a temporary test database during CI runs.
3. **Pre-Merge Review Checklist**:
   - When reviewing PRs that introduce files in `alembic/versions/`, reviewers must check:
     - [ ] Does `down_revision` match the latest revision ID on `main`?
     - [ ] Does `alembic heads` show only 1 head on the PR branch rebased on `origin/main`?
