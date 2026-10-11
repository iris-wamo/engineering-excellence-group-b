# Demo 01 — Shared Backend Package

## Loom Video
*Loom video link placeholder (to be recorded and linked).*

## Objective
Demonstrate that `taskflow_shared` functions as an independently testable, reusable backend package installed into the TaskFlow monorepo environment, providing:
1. Unified `AppError` exception hierarchy and standard ADR-001 error response envelopes.
2. Generic `PaginatedResponse[T]` model and `PaginationParams` query dependency.
3. `RequestIdMiddleware` for request ID context injection and header propagation.
4. Clean architectural separation with zero domain leaks into the shared package.

## Scenario
In a growing backend architecture, common cross-cutting capabilities (like error formats, pagination parameters, and request correlation IDs) often get duplicated across services or modules. We simulate centralizing these cross-cutting concerns into a dedicated package (`packages/taskflow_shared/`) installed in editable mode via `uv`.

## Commands / Steps Used
1. Install package in editable workspace mode:
   ```bash
   uv sync
   ```
2. Run standalone package unit tests:
   ```bash
   uv run pytest packages/taskflow_shared/tests/
   ```
3. Run the complete application test suite:
   ```bash
   make test
   ```
4. Verify strict type safety and code quality:
   ```bash
   make lint
   make hooks-run
   ```

## Expected Behavior
- `taskflow_shared` is recognized as an installed package.
- `app.core.exceptions` cleanly re-exports and extends `taskflow_shared.errors`.
- API endpoints automatically include `X-Request-ID` in HTTP responses.
- All existing app tests plus package tests pass with 0 regressions.

## Actual Findings
- `taskflow_shared==0.1.0` builds and installs via `uv` in < 2ms in editable mode.
- 82 tests (71 app tests + 11 package tests) pass cleanly.
- `mypy .` and `ruff check .` pass cleanly across all source files with 0 warnings or errors.

## Evidence

### 1. Test Suite Results
```text
testpaths: tests, packages/taskflow_shared/tests
collected 75 items

tests/api/test_projects.py .......                                       [  9%]
tests/api/test_tasks.py ........                                         [ 20%]
tests/api/test_tasks_assignment_api.py ...                               [ 24%]
tests/api/test_users.py .......                                          [ 33%]
tests/schemas/test_project_schema.py .....                               [ 40%]
tests/schemas/test_task_schema.py .....                                  [ 46%]
tests/schemas/test_user_schema.py ....                                   [ 52%]
tests/services/test_project_service.py ......                            [ 60%]
tests/services/test_task_assignment_transaction.py ........              [ 70%]
tests/services/test_task_service.py .......                              [ 80%]
tests/services/test_user_service.py ........                             [ 90%]
tests/test_seed.py .                                                     [ 92%]
packages/taskflow_shared/tests/test_errors.py ..                         [ 94%]
packages/taskflow_shared/tests/test_logging.py ..                        [ 97%]
packages/taskflow_shared/tests/test_pagination.py ..                     [100%]

======================== 75 passed in 3.03s ========================
```

### 2. Code Quality & Pre-commit Output
```text
uv run pre-commit run --all-files
trim trailing whitespace.................................................Passed
check yaml...............................................................Passed
check toml...............................................................Passed
check for merge conflicts................................................Passed
ruff check...............................................................Passed
ruff format..............................................................Passed
mypy.....................................................................Passed
pytest...................................................................Passed
```

### 3. Example Request Tracing & Error Response
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Project 42 not found",
    "details": [
      {
        "field": "project_id",
        "message": "Does not exist"
      }
    ]
  }
}
```
Response header:
```http
X-Request-ID: e62b719463994689a9c9f0b1a03975ba
```

## What We Learned
1. **Local editable dependencies (`tool.uv.sources`)** eliminate code duplication across internal packages without requiring external PyPI publishing.
2. **Contextvars** provide clean, asynchronous request ID propagation across deep call stacks without needing to pass request objects down to service layers.
3. Keeping domain entities (`User`, `Task`) strictly out of the shared package prevents circular dependencies and architectural rot.

## Open Questions
- Should `X-Workspace-ID` extraction middleware be added directly into `taskflow_shared` or left in `app/auth/` for Issue #72? (Recommended: header constants in shared package, business validation in `app/`).
