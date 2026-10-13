# Demo 06 — Multi-Tenancy (Workspaces) Isolation


## Objective
Prove that TaskFlow enforces strict tenant isolation:
1. Projects and tasks belong to a workspace.
2. Users in one workspace cannot see, access, or change data belonging to another workspace.
3. Cross-workspace resource access returns `404 Not Found` (preventing information leakage about entity existence).
4. Attempting to switch to an unauthorized workspace returns `403 Forbidden`.
5. Existing data continues to work without regression.

---

## Scenario
We establish two separate workspaces:
- **Workspace 1 (`Acme Corp`, id: 1)** with User `Alice` (`alice@acme.com`), Project `Acme Portal` (id: 10), and Task `Acme Task 1` (id: 101).
- **Workspace 2 (`Globex Corp`, id: 2)** with User `Bob` (`bob@globex.com`), Project `Globex Engine` (id: 20), and Task `Globex Task 2` (id: 201).
- **User `Charlie` (`charlie@consultant.com`)**: Cross-tenant consultant holding memberships in both Workspace 1 and Workspace 2.

We then simulate cross-tenant queries, mutations, and unauthorized header claims to prove the security boundary holds.

---

## Commands / Steps Used

```bash
uv run alembic upgrade head
uv run python scripts/seed_data.py --workspaces 2 --users 5 --projects 4 --tasks 20 --reset
uv run pytest tests/auth/test_workspace_isolation.py -v
```

### API Test Sequence

| # | Action | Request Context | Target | Expected Result | Verified Behavior |
|---|---|---|---|---|---|
| 1 | Query projects | Alice (`X-Workspace-ID: 1`) | `GET /api/v1/projects` | `200 OK` (Only Acme projects) | Only Acme Portal returned; Globex Engine hidden |
| 2 | Direct project access | Alice (`X-Workspace-ID: 1`) | `GET /api/v1/projects/20` | `404 NOT_FOUND` | Returned 404; existence of Globex Project not leaked |
| 3 | Query tasks | Alice (`X-Workspace-ID: 1`) | `GET /api/v1/tasks` | `200 OK` (Only Acme tasks) | Only Acme tasks returned |
| 4 | Direct task access | Alice (`X-Workspace-ID: 1`) | `GET /api/v1/tasks/201` | `404 NOT_FOUND` | Returned 404; Globex Task hidden |
| 5 | Cross-tenant task creation | Alice (`X-Workspace-ID: 1`) | `POST /api/v1/tasks` (with `project_id: 20`) | `404 NOT_FOUND` | Rejected; cannot attach task to foreign workspace project |
| 6 | Cross-tenant status update | Alice (`X-Workspace-ID: 1`) | `PATCH /api/v1/tasks/201/status` | `404 NOT_FOUND` | Rejected; cannot mutate foreign workspace task |
| 7 | Cross-tenant task assign | Alice (`X-Workspace-ID: 1`) | `POST /api/v1/tasks/201/assign` | `404 NOT_FOUND` | Rejected; cannot reassign foreign workspace task |
| 8 | Unauthorized tenant switch | Alice (`X-Workspace-ID: 2`) | `GET /api/v1/projects` | `403 FORBIDDEN` | Blocked; Alice lacks membership in Workspace 2 |
| 9 | Multi-tenant user switch | Charlie (`X-Workspace-ID: 1`) | `GET /api/v1/projects` | `200 OK` (Acme projects) | Returns Acme Portal |
| 10 | Multi-tenant user switch | Charlie (`X-Workspace-ID: 2`) | `GET /api/v1/projects` | `200 OK` (Globex projects) | Returns Globex Engine |
| 11 | Malformed header | Alice (`X-Workspace-ID: invalid`) | `GET /api/v1/projects` | `400 INVALID_WORKSPACE_ID` | Consistent validation error envelope |
| 12 | Non-existent workspace | Alice (`X-Workspace-ID: 99999`) | `GET /api/v1/projects` | `404 NOT_FOUND` | Workspace 99999 does not exist |
| 13 | Legacy / Missing header | Alice (No `X-Workspace-ID`) | `GET /api/v1/projects` | `200 OK` (Defaults to WS 1) | Backward compatibility holds |

---

## Actual Request / Response Samples

### 1. Cross-Workspace Project Access Blocked (Anti-Leak)
**Request**:
```http
GET /api/v1/projects/20 HTTP/1.1
Host: api.taskflow.local
Authorization: Bearer <token_for_alice>
X-Workspace-ID: 1
```

**Response**:
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Project not found",
    "details": [
      {
        "field": "project_id",
        "message": "Project does not exist"
      }
    ]
  }
}
```

### 2. Unauthorized Tenant Header Claim Blocked
**Request**:
```http
GET /api/v1/projects HTTP/1.1
Host: api.taskflow.local
Authorization: Bearer <token_for_alice>
X-Workspace-ID: 2
```

**Response**:
```json
{
  "error": {
    "code": "FORBIDDEN",
    "message": "You do not have permission to access this workspace",
    "details": null
  }
}
```

### 3. Cross-Workspace Task Creation Blocked
**Request**:
```http
POST /api/v1/tasks HTTP/1.1
Host: api.taskflow.local
Authorization: Bearer <token_for_alice>
X-Workspace-ID: 1
Content-Type: application/json

{
  "title": "Unauthorized cross-tenant task",
  "project_id": 20
}
```

**Response**:
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Project not found",
    "details": [
      {
        "field": "project_id",
        "message": "Project does not exist"
      }
    ]
  }
}
```

---

## Test Verification Output

```
============================= test session starts ==============================
rootdir: /Users/dev/Projects/engineering-excellence-group-b/session-04-shared-backend-domain-rbac
configfile: pyproject.toml
testpaths: tests, packages/taskflow_shared/tests
plugins: cov-7.1.0, anyio-4.14.1, asyncio-1.4.0
collected 180 items

tests/api/test_error_handling.py ...                                     [  1%]
tests/api/test_projects.py .......                                       [  5%]
tests/api/test_task_imports.py .......                                   [  9%]
tests/api/test_task_workflow.py ........                                 [ 13%]
tests/api/test_tasks.py ........                                         [ 18%]
tests/api/test_tasks_assignment_api.py .....                             [ 21%]
tests/api/test_users.py .......                                          [ 25%]
tests/auth/test_auth_api.py ..........                                   [ 30%]
tests/auth/test_rbac_api.py ..................                           [ 40%]
tests/auth/test_workspace_isolation.py ............                      [ 47%]
tests/schemas/test_project_schema.py .....                               [ 50%]
tests/schemas/test_task_import_schema.py .......                         [ 53%]
tests/schemas/test_task_schema.py .....                                  [ 56%]
tests/schemas/test_user_schema.py ....                                   [ 58%]
tests/services/test_project_service.py ......                            [ 62%]
tests/services/test_task_assignment_transaction.py ........              [ 66%]
tests/services/test_task_import_service.py ................              [ 75%]
tests/services/test_task_service.py .......                              [ 79%]
tests/services/test_task_status_concurrency.py .                         [ 80%]
tests/services/test_user_service.py ........                             [ 84%]
tests/test_seed.py .                                                     [ 85%]
tests/unit/test_task_workflow_rules.py .............                     [ 92%]
packages/taskflow_shared/tests/test_contracts.py ....                    [ 94%]
packages/taskflow_shared/tests/test_errors.py ..                         [ 95%]
packages/taskflow_shared/tests/test_logging.py .....                     [ 98%]
packages/taskflow_shared/tests/test_pagination.py ...                    [100%]

======================= 180 passed, 1 warning in 58.65s ========================
```
