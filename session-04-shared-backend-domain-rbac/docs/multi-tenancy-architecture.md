# Multi-Tenancy Architecture (Workspaces)

## 1. Overview and Problem Statement

TaskFlow is designed to support multiple organizations and teams concurrently from a single deployment. In a multi-tenant SaaS application, **cross-tenant data leakage is a critical security vulnerability**.

Issue **#72** establishes tenant boundaries using **Workspaces**:
- Every project and task belongs strictly to a workspace.
- Users only have access to resources in workspaces where they hold active membership.
- Requests across workspace boundaries are strictly blocked.
- Query isolation guarantees that an entity belonging to another workspace returns `404 Not Found`, completely concealing the existence of data belonging to other tenants.
- Existing data, legacy clients, and test fixtures continue to operate without breaking (backward compatibility).

---

## 2. Chosen Approach: Shared Database, Shared Schema with Tenant Discriminator

TaskFlow adopts a **Shared Database, Shared Schema with Discriminator Column (`workspace_id`)** pattern:

```
+-----------------------------------------------------------------------------------------+
|                                    PostgreSQL Database                                  |
|                                                                                         |
|  +--------------------+       +---------------------+       +-----------------------+   |
|  |     workspace      |       |   workspace_user    |       |         user          |   |
|  +--------------------+       +---------------------+       +-----------------------+   |
|  | id: 1 (Acme)       |<----->| ws_id: 1, user_id: A|<----->| id: A (Alice)         |   |
|  | id: 2 (Globex)     |<----->| ws_id: 2, user_id: B|<----->| id: B (Bob)           |   |
|  +--------------------+       +---------------------+       +-----------------------+   |
|            |                                                                            |
|            | 1:N                                                                        |
|            v                                                                            |
|  +-------------------------------------+      +--------------------------------------+  |
|  |               project               |      |                 task                 |  |
|  +-------------------------------------+      +--------------------------------------+  |
|  | id: 10, ws_id: 1 ("Acme Portal")    |<---->| id: 101, ws_id: 1 ("Acme Task 1")    |  |
|  | id: 20, ws_id: 2 ("Globex Engine")  |<---->| id: 201, ws_id: 2 ("Globex Task 2")  |  |
|  +-------------------------------------+      +--------------------------------------+  |
+-----------------------------------------------------------------------------------------+
```

### Architectural Decisions:
1. **Tenant Anchor (`workspace`)**:
   - `id` (Integer Primary Key), `name` (String), `slug` (Unique indexed String), `created_at`, `updated_at`.
2. **Membership Link (`workspace_user`)**:
   - Composite primary key `(workspace_id, user_id)` with cascading foreign keys.
   - Allows users to belong to multiple workspaces (e.g. consultants or contractors) while enforcing tenant boundaries during each request.
3. **Foreign Keys on Domain Tables**:
   - Both `project.workspace_id` and `task.workspace_id` reference `workspace.id` with `ON DELETE CASCADE`.
   - Dedicated indexes `ix_project_workspace_id` and `ix_task_workspace_id` optimize all tenant-scoped queries.
4. **Header-Based Context (`X-Workspace-ID`)**:
   - Clients identify their active tenant context using the HTTP header `X-Workspace-ID` (defined in `taskflow_shared.contracts.constants.HEADER_WORKSPACE_ID`).
   - If omitted, the system defaults to `1` (`Default Workspace`) ensuring 100% backward compatibility for existing scripts, test suites, and endpoints.

---

## 3. Comparative Architecture Trade-offs

| Criterion | 1. Shared Database, Shared Schema (Chosen) | 2. Separate Schemas (PostgreSQL Schemas) | 3. Separate Databases (Database-per-tenant) |
| :--- | :--- | :--- | :--- |
| **Data Isolation** | Logical (enforced via queries, FKs, and application logic) | Medium (PostgreSQL schema separation) | Strongest (Physical OS/database process separation) |
| **Operational Overhead** | **Lowest**: Single migration, unified connection pool, simple backups | Medium: Migrations must run on every schema; schema proliferation | Highest: N databases to provision, patch, monitor, and back up |
| **Resource Efficiency** | **Highest**: Maximizes pooling, shared memory, and buffer caches | Medium: Schema metadata increases catalog memory footprint | Lowest: High idle overhead and fragmentation |
| **Query Performance** | **High**: Indexed on `workspace_id`, easy cross-tenant aggregation for platform admins | Good: Requires dynamic `search_path` per tenant connection | Good: High tenant isolation, no noisy-neighbor within memory |
| **Implementation Complexity** | **Low to Moderate**: Clear tenant discriminator parameter in repos/services | High: Dynamic connection routing and schema management | Very High: Dynamic database routing and multi-pool orchestration |
| **Cost** | **Most Cost-Effective**: Scales easily to thousands of workspaces on one cluster | Moderate: Struggles beyond hundreds of schemas | Expensive: High minimum infrastructure cost |

---

## 4. Two-Layer Tenant Isolation Security Model

Isolation is enforced in two complementary layers:

### Layer 1: Context Authorization (`CurrentWorkspaceId`)
Implemented in `app/auth/workspace_context.py`:
1. When `X-Workspace-ID` is passed:
   - Validates that the header value is a positive integer (rejects malformed inputs with `400 INVALID_WORKSPACE_ID`).
   - Verifies the workspace exists (rejects non-existent IDs with `404 NOT_FOUND`).
   - Ensures the caller is authenticated and checks membership in `workspace_user`.
   - **Rejection**: If the caller is not a member of the requested workspace, access is denied with `403 FORBIDDEN` (`"You do not have permission to access this workspace"`).
2. When `X-Workspace-ID` is omitted:
   - Defaults to Workspace `1` (`Default Workspace`).
   - Automatically ensures that newly registered users have access to their default workspace.

### Layer 2: Scoped Query Filtering (Anti-Leak Layer)
Implemented in repository and service methods:
1. **Reads**: All `SELECT` queries on `project` and `task` apply `where(Model.workspace_id == current_workspace_id)`.
2. **Entity Lookups**: `ProjectRepository.get_by_id(..., workspace_id)` and `TaskRepository.get_by_id(..., workspace_id)` filter by `workspace_id`.
   - If a caller in Workspace 1 attempts to load an ID that exists in Workspace 2, the query yields `None`.
   - The API answers `404 Not Found` (`"Project not found"` or `"Task not found"`), **preventing attackers from discovering whether an ID exists in other tenants**.
3. **Writes & Transitions**:
   - `TaskService.create_task` ensures the parent project belongs to the caller's active workspace.
   - `TaskService.update_task_status` and `TaskService.assign_task` lock and validate the task only within the caller's workspace.

---

## 5. Database-Level Protection Options

While application-level filtering is active, modern systems can add database-level guarantees to safeguard against programming omissions:

### Option A: PostgreSQL Row-Level Security (RLS) *(Recommended for Defense-in-Depth)*
PostgreSQL supports native Row-Level Security:
```sql
-- Enable RLS on multi-tenant tables
ALTER TABLE project ENABLE ROW LEVEL SECURITY;
ALTER TABLE task ENABLE ROW LEVEL SECURITY;

-- Create policy based on session variable
CREATE POLICY tenant_isolation_project ON project
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::integer);

CREATE POLICY tenant_isolation_task ON task
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::integer);
```

**Application Integration**:
Upon acquiring an async connection from the connection pool, the application executes:
```python
await connection.execute(text("SET LOCAL app.current_workspace_id = :ws_id"), {"ws_id": workspace_id})
```
- **Benefit**: Any query executed during that transaction automatically cannot see rows outside the current workspace, even in the event of an accidental omission of `workspace_id == ...` in Python code.
- **Trade-off**: Requires careful transaction lifecycle management (`SET LOCAL` scopes strictly to the transaction).

### Option B: PostgreSQL Schema Search Path
Each tenant receives a dedicated schema (`tenant_acme`, `tenant_globex`). When executing requests:
```sql
SET search_path TO tenant_acme, public;
```
- **Benefit**: Zero tenant column needed in individual tables.
- **Trade-off**: Schema migration complexity scales linearly with the number of tenants.

### Option C: Tenant Connection Pool Partitioning
Clients connect via dedicated database user roles or connection pools per tenant (common in high-compliance healthcare/fintech setups).

---

## 6. Backward Compatibility & Data Migration Strategy

To fulfill the requirement that **"Existing data must continue to work"**:
1. **Alembic Migration (`d4e5f6a7b8c9`)**:
   - Creates `workspace` and `workspace_user` tables.
   - Inserts `Default Workspace` (`id = 1`, `slug = default-workspace`).
   - Adds `workspace_id` column with `server_default = '1'` to `project` and `task`.
   - Backfills existing `project.workspace_id = 1` and `task.workspace_id = project.workspace_id`.
   - Associates all existing users in the `user` table with `workspace_id = 1`.
   - Enforces `NOT NULL` with Foreign Key constraints on `project.workspace_id` and `task.workspace_id`.
2. **API Defaults**:
   - All endpoints default `workspace_id = 1` when the `X-Workspace-ID` header is not present.
   - Existing integration tests and external clients continue to function with zero changes.
