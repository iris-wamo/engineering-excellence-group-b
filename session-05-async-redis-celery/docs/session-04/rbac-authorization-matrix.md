# RBAC Authorization Matrix

## Overview
This document defines the Role-Based Access Control (RBAC) rules for TaskFlow and is kept in
step with the code. The matrix below is implemented as the `ROLE_PERMISSIONS` dictionary in
[`app/auth/permissions.py`](../app/auth/permissions.py); if the two ever disagree, the code is
the bug.

Anything not granted below is denied.

## Roles
Roles are assigned **per project** via the `project_user` table (`user_id + project_id + role`),
using the `ProjectRole` enum.

- `admin`: Administrator. Creates projects and manages users.
- `manager`: Project manager. Assigns work within their project.
- `owner`: The project's owner. Predates RBAC and marks ownership; may assign work within the
  project, but may not create projects or manage users.
- `member`: Individual contributor. No role-based permissions; acts on their own tasks only.

---

## Authorization Matrix

| Role | Resource | Action | Allowed? | Scope / Condition |
|------|----------|--------|----------|-------------------|
| admin | Project | create | **Yes** | Holds `admin` in any project |
| admin | User | manage (create) | **Yes** | Holds `admin` in any project |
| admin | Task | assign | **Yes** | Within the task's project |
| manager | Task | assign | **Yes** | Within the task's project |
| owner | Task | assign | **Yes** | Within the task's project |
| any role | Task | update status | **Yes** | Only if the task is assigned to them |

### Denied cases

| Role | Resource | Action | Allowed? | Why |
|------|----------|--------|----------|-----|
| manager | Project | create | No | Not granted to `manager` |
| member | Project | create | No | Not granted to `member` |
| owner | Project | create | No | Not granted to `owner` |
| manager | User | manage | No | Not granted to `manager` |
| member | User | manage | No | Not granted to `member` |
| member | Task | assign | No | Not granted to `member` |
| manager | Task | assign | No | When their `manager` role is in a *different* project |
| member | Task | update status | No | When the task is assigned to someone else |
| admin | Task | update status | No | Status is an ownership check; even an admin must be the assignee |
| no role | any protected action | — | No | Authenticated but holds no granting role |
| unauthenticated | any protected endpoint | — | No | Returns 401 before any role check |

---

## Enforced endpoints

| Endpoint | Requirement | Enforced by |
|---|---|---|
| `POST /api/v1/projects` | `project_create` | `require_permission(Permission.project_create)` |
| `POST /api/v1/users` | `user_manage` | `require_permission(Permission.user_manage)` |
| `POST /api/v1/tasks/{id}/assign` | `task_assign` in the task's project | `require_task_permission(Permission.task_assign)` |
| `PATCH /api/v1/tasks/{id}/status` | caller is the assignee | `require_task_assignee` |

## Responses

| Situation | Status | Error code |
|---|---|---|
| No / invalid / expired token | 401 | `UNAUTHENTICATED` |
| Authenticated, role not allowed | 403 | `FORBIDDEN` |
| Authorization target does not exist | 404 | `NOT_FOUND` |

Both use the project's standard error envelope:

```json
{"error": {"code": "FORBIDDEN", "message": "You do not have permission to perform this action", "details": []}}
```

## Known gap: assigning the first role

Roles live in `project_user`, so granting the first `admin` needs a project, and creating a project
needs an `admin`. There is no role-management endpoint in this scope, so the first role must be
inserted directly:

```sql
INSERT INTO project_user (project_id, user_id, role) VALUES (1, 1, 'admin');
```
