# Testing Strategy

How the test suite is organized, how to run each part, and which helpers to use when writing a new test.

## Layout

- **`tests/unit/`** (marker `unit`, no Docker): pure domain logic, such as workflow rules and side effects and the RBAC matrix.
  - **`schemas/`**: Pydantic request/response validation.
- **`tests/integration/`** (marker `integration`, real PostgreSQL and MongoDB):
  - **`api/`**: HTTP behavior, such as status codes, error envelopes, pagination, filters and invalid requests.
  - **`services/`**: service-layer behavior, such as transactions, imports and concurrency.
  - **`test_seed.py`**: the seed script.
- **`tests/auth/`** (marker `auth`, real databases): authentication, the RBAC matrix end to end, and workspace (tenant) isolation. It is kept apart from `integration/` so security checks can run on their own with `-m auth`.
- **`tests/fixtures/`**: shared fixtures and factories. Not collected as tests.
- **`tests/conftest.py`**: registers `tests/fixtures/database.py` through `pytest_plugins`, defines the shared fixtures and applies the markers.
- **`packages/taskflow_shared/tests/`** (marker `unit`): the shared package.

Markers are applied automatically from the top-level folder (see `pytest_collection_modifyitems` in `tests/conftest.py`), so a new test file only needs to go in the right folder.

## Running tests

Start PostgreSQL and MongoDB first with `make docker-up`, except for unit tests.

```bash
# Everything
uv run pytest

# Unit tests only: no Docker, under a second
uv run pytest -m unit

# Integration and auth tests
uv run pytest -m "not unit"

# Authentication, RBAC and tenancy only
uv run pytest -m auth

# One file, filtered by test name
uv run pytest tests/integration/api/test_invalid_requests.py -k missing
```

## How test data is isolated

- **PostgreSQL**: tests use a separate `<db>_test` database. The schema is created once per session by `test_database`, with Workspace 1 inserted the way the migration does. Each test gets `db_session`, which runs inside one outer transaction that is rolled back afterwards. Application code that calls `commit()` only commits a savepoint, so nothing leaks between tests.
- **Isolation is tested**: `integration/test_db_session_isolation.py` drives `rolled_back_session` (what `db_session` is built on) and checks from a separate connection that commits, exceptions and application-level `rollback()` calls leave nothing behind.
- **MongoDB**: `settings.mongo_db` points at `<db>_test` for the whole run. The `raw_task_imports` collection is emptied at the start of every test that uses `db_session`.
- **Opt-in setup**: a test that never asks for `db_session` (directly, or through `client` or `factory`) never connects to a database. That is what keeps `-m unit` free of Docker.
- **Real commits**: tests that need data committed across sessions request `test_database` and open their own sessions, for example `integration/services/test_task_status_concurrency.py`. They must clean up the rows they create.

## Fixtures and helpers

### Core fixtures

Defined in `tests/conftest.py` and `tests/fixtures/database.py`.

| Fixture | Gives you |
| --- | --- |
| `db_session` | A rolled-back `AsyncSession` on the test database |
| `client` | An `httpx.AsyncClient` for the app, sharing `db_session` |
| `factory` | A `DataFactory` bound to `db_session` |
| `viewer_headers` | Headers for a Workspace 1 member with no role |
| `project` | A ready-made project in Workspace 1 |
| `make_user` | Signs up and logs in through the real API |
| `admin_headers` | Headers for an admin created with `make_user` |
| `test_database` | The test database URL, schema created |

### Data factory

`DataFactory` in `tests/fixtures/factories.py` inserts rows directly, with unique defaults, so a test only spells out what matters to it.

- `factory.workspace()`: a workspace with no members.
- `factory.user()`: a user enrolled in Workspace 1. Pass `workspace_ids=(...)` for other workspaces, or `()` for none. No password is stored unless you pass `password=...`.
- `factory.add_to_workspace(user, workspace)`: a workspace membership.
- `factory.project()`: a project in Workspace 1. Pass `workspace=...` for another one.
- `factory.grant_role(user, project, role)`: a project role. This also makes the user a project member.
- `factory.task(project)`: a task in the project's workspace. `status=...` can start it anywhere in the workflow.
- `factory.member(project, role)`: a user in the project's workspace holding `role`, returned as an `AuthedUser` whose `.headers` already carry a token and `X-Workspace-ID`.

The `user`, `assignee` and `workspace` arguments accept either the model or its id, so `AuthedUser.id` can be passed straight through.

### Tokens and headers

Defined in `tests/fixtures/auth.py`.

| Helper | Use |
| --- | --- |
| `auth_headers_for(user_id)` | Valid bearer headers. Pass `workspace_id=...` to scope them |
| `token_for(user_id)` | A valid token on its own |
| `bearer(token)` | The header for any token |
| `expired_token_for(user_id)` | Correctly signed but expired |
| `forged_token_for(user_id)` | Signed with the wrong key |
| `AuthedUser` | The `(id, headers)` pair from `factory.member` and `make_user` |
| `MakeUser` | The type of the `make_user` fixture, for annotations |
| `AUTH_USER` | The user the `auth_headers` fixture signs up |

Minted tokens behave exactly like login tokens. `tests/auth/test_access_tokens.py` checks that.

## Which helper to use

- **Setting up state**: use `factory`. It is fast (no password hashing, no HTTP) and can create what the API refuses to, such as the first admin, a task already in `review`, or a user in no workspace.
- **The behavior under test**: use `client`, and assert on what the API returns, not on what the factory wrote.
- **Signup or login is the subject of the test**: use `make_user` or the `/auth` endpoints.
- **Pure logic**: use no fixtures and build models in memory. `unit/test_task_workflow_transition.py` shows a fake session that records `db.add` calls.

```python
async def test_manager_can_assign(client: AsyncClient, factory: DataFactory) -> None:
    project = await factory.project()
    lead = await factory.member(project, ProjectRole.manager)
    dev = await factory.member(project)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign", json={"assignee_id": dev.id}, headers=lead.headers
    )

    assert response.status_code == 200
```

## Conventions

- **Arrange, act, assert**, separated by blank lines, with one behavior per test.
- **Name tests after the behavior**, for example `test_member_cannot_assign_task`.
- **Assert the error code as well as the status** for failures (`response.json()["error"]["code"]`). Clients branch on the code.
- **Cover both directions.** Each RBAC permission, workflow transition and tenancy boundary needs an allowed test and a denied test.
- **Parametrize tables** (roles × endpoints, invalid payloads, illegal transitions) instead of copying a test per row, and give the cases readable `ids`.
- **Cross-tenant access must return 404**, never 403, so another tenant's ids stay hidden. Test it with two workspaces from `factory.workspace()`.
- **Authenticate requests** with `viewer_headers` or `factory.member`. Don't rely on anonymous requests falling back to Workspace 1, because that fallback is due to be switched off.
- **Don't hard-code ids** other than Workspace 1. Use what the factory returns, and `MISSING_ID` from `tests/fixtures/factories.py` for not-found cases.
- **Import helpers and types from `tests.fixtures`**, never from `tests/conftest.py`. pytest loads conftest files itself.

## Where the session-04 features are covered

### Task status workflow (#69)

- Unit: `unit/test_task_workflow_rules.py`, `unit/test_task_workflow_transition.py`
- Integration: `integration/api/test_task_workflow.py`, `integration/api/test_task_lifecycle_api.py`, `integration/services/test_task_status_concurrency.py`
- Auth: `auth/test_rbac_matrix_in_workspace.py` (only the assignee may move a task)

### Signup, login and tokens

- Unit: `unit/schemas/`
- Auth: `auth/test_auth_api.py`, `auth/test_access_tokens.py`

### Roles and permissions (#71)

- Unit: `unit/test_rbac_matrix.py`
- Auth: `auth/test_rbac_api.py`, `auth/test_rbac_matrix_in_workspace.py`

### Multi-tenancy (#72)

- Integration: `integration/api/test_task_lifecycle_api.py`
- Auth: `auth/test_workspace_isolation.py`

### Raw import to normalized data (#73)

- Unit: `unit/schemas/test_task_import_schema.py`
- Integration: `integration/services/test_task_import_service.py`, `integration/api/test_task_imports.py`
- Auth: `auth/test_workspace_isolation.py` (import scoping)

### Invalid requests

- Unit: `unit/schemas/`
- Integration: `integration/api/test_invalid_requests.py`, `integration/api/test_error_handling.py`
