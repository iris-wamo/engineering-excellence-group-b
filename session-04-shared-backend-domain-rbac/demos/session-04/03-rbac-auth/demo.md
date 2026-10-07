# Demo 03 — Authentication & RBAC

> Part A covers **authentication** (who are you?). Part B covers **authorization / RBAC**
> (what are you allowed to do?).

## Loom Video
Paste Loom link here. _(Not yet recorded.)_

## Objective
Prove that the API can:

1. Register a user and store only a hash of their password.
2. Exchange valid credentials for a JWT access token.
3. Identify which user is making a request from that token.
4. Reject missing, invalid, and expired credentials with one consistent 401 error.
5. Allow or deny each write action based on the caller's **per-project role**, returning 403
   when an authenticated user lacks permission, matching
   [`docs/rbac-authorization-matrix.md`](../../../docs/rbac-authorization-matrix.md) exactly.

## Scenario
**Part A:** a new user signs up, logs in, and calls a protected endpoint. We then repeat the same
calls with bad credentials and with no credentials at all, to confirm the API fails closed and
never leaks whether an email exists or what the stored password looks like.

**Part B:** three users — `admin`, `manager`, `member` — are given those roles in one project
(`Payments`). Each then attempts all four restricted actions, so every allowed row *and* every
denied row of the matrix is exercised against a real server.

## Commands / Steps Used

```bash
make install          # installs bcrypt + pyjwt
make migrate          # adds user.password_hash
```

API calls (base `http://127.0.0.1:8000/api/v1`):

| # | Call | Expected |
|---|------|----------|
| 1 | `POST /auth/signup` | 201, user without any password field |
| 2 | `POST /auth/signup` (same email) | 409 `CONFLICT` |
| 3 | `POST /auth/login` (correct password) | 200 + access token |
| 4 | `POST /auth/login` (wrong password) | 401 `UNAUTHENTICATED` |
| 5 | `POST /auth/login` (unknown email) | 401 `UNAUTHENTICATED`, same message as #4 |
| 6 | `GET /auth/me` with token | 200, the token's user |
| 7 | `GET /auth/me` with no token | 401 `UNAUTHENTICATED` |
| 8 | `GET /auth/me` with a junk token | 401 `UNAUTHENTICATED` |
| 9 | `GET /auth/me` with an expired token | 401 `UNAUTHENTICATED` |

## Expected Behavior
- The plain-text password never reaches the database and never appears in a response.
- Wrong password and unknown email return the **same** error, so the endpoint cannot be used to
  enumerate accounts.
- Every authentication failure uses the project's standard error envelope with code
  `UNAUTHENTICATED` and HTTP 401.

## Actual Findings
All nine calls behaved as expected (raw output below). The stored value is a bcrypt hash
(`$2b$12$...`), and no response body contained `password` or `password_hash`.

## Evidence

### 1. Signup — request / response

```http
POST /api/v1/auth/signup
Content-Type: application/json

{"name":"Ada Lovelace","email":"ada@example.com","password":"sup3r-secret"}
```

```http
HTTP/1.1 201 Created
content-type: application/json

{"id":1,"name":"Ada Lovelace","email":"ada@example.com","is_active":true}
```

No `password` or `password_hash` key is present in the response.

### 2. Duplicate signup

```http
POST /api/v1/auth/signup   (same email again)
```

```http
HTTP/1.1 409 Conflict

{"error":{"code":"CONFLICT","message":"Email already exists",
          "details":[{"field":"email","message":"Email already exists"}]}}
```

### 3. Successful login — request / response

```http
POST /api/v1/auth/login
Content-Type: application/json

{"email":"ada@example.com","password":"sup3r-secret"}
```

```http
HTTP/1.1 200 OK
content-type: application/json

{"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiaWF0IjoxNzkxMjI4MzE2
LCJleHAiOjE3OTEyMzE5MTZ9.2wJXnP9wKEktS-GQLDrlvN-Qx5KI1dUTv1KoDjRuKKo","token_type":"bearer"}
```

The JWT payload is `{"sub": "1", "iat": ..., "exp": ...}` — only the user id, no credentials.

### 4. Failed login — wrong password

```http
POST /api/v1/auth/login

{"email":"ada@example.com","password":"wrong-password"}
```

```http
HTTP/1.1 401 Unauthorized

{"error":{"code":"UNAUTHENTICATED","message":"Invalid email or password","details":[]}}
```

### 5. Failed login — unknown user (identical response to #4)

```http
POST /api/v1/auth/login

{"email":"nobody@example.com","password":"sup3r-secret"}
```

```http
HTTP/1.1 401 Unauthorized

{"error":{"code":"UNAUTHENTICATED","message":"Invalid email or password","details":[]}}
```

### 6. Identifying the caller

```http
GET /api/v1/auth/me
Authorization: Bearer <token>
```

```http
HTTP/1.1 200 OK

{"id":1,"name":"Ada Lovelace","email":"ada@example.com","is_active":true}
```

### Database row — the password is stored only as a hash

```text
taskflow=# SELECT id, email, password_hash FROM "user" WHERE email='ada@example.com';
 id |      email      |                        password_hash
----+-----------------+--------------------------------------------------------------
  1 | ada@example.com | $2b$12$XSieD50j5M8PzCu.5FO69.SN.ki7CFUkARAHCrwMLlqwnReRDq9xa
(1 row)
```

`sup3r-secret` appears nowhere in the table.
---

# Part B — Authorization (RBAC)

## Commands / Steps Used

```bash
make migrate     # adds 'admin' and 'manager' to the project_role enum
make run
```

Roles must be granted directly in SQL, because granting the first `admin` needs a project and
creating a project needs an `admin` (see "Known gap" in the matrix doc):

```sql
INSERT INTO project (name, slug) VALUES ('Payments', 'payments');
INSERT INTO project_user (project_id, user_id, role) VALUES
  (1, 1, 'admin'), (1, 2, 'manager'), (1, 3, 'member');
```

| # | Caller | Call | Expected |
|---|--------|------|----------|
| A1 | admin | `POST /projects` | 201 |
| A2 | manager | `POST /projects` | 403 `FORBIDDEN` |
| A3 | member | `POST /projects` | 403 `FORBIDDEN` |
| A4 | anonymous | `POST /projects` | 401 `UNAUTHENTICATED` |
| B1 | admin | `POST /users` | 201 |
| B2 | manager | `POST /users` | 403 `FORBIDDEN` |
| C1 | manager | `POST /tasks/1/assign` | 200 |
| C2 | member | `POST /tasks/1/assign` | 403 `FORBIDDEN` |
| D1 | member (assignee) | `PATCH /tasks/1/status` | 200 |
| D2 | admin (not assignee) | `PATCH /tasks/1/status` | 403 `FORBIDDEN` |
| D3 | anonymous | `PATCH /tasks/1/status` | 401 `UNAUTHENTICATED` |

## Expected Behavior
- 401 is returned *before* any role check, so an anonymous caller never reveals whether their
  role would have been sufficient.
- 403 is returned for an authenticated caller whose role does not grant the action.
- Status updates are an **ownership** check, not a role check: even an admin is refused on a task
  that is not theirs.
- A role only applies inside the project it was granted in.

## Actual Findings
All eleven calls returned exactly what the matrix predicts. Captured from a live server:

### Evidence of allowed actions

```text
A1  admin   POST /projects          -> 201
B1  admin   POST /users             -> 201
C1  manager POST /tasks/1/assign    -> 200
D1  member  PATCH /tasks/1/status   -> 200
    {"id":1,"title":"Stripe","status":"in_progress","project_id":1,"assignee_id":3, ...}
```

### Evidence of denied actions

```text
A2  manager POST /projects          -> 403
    {"error":{"code":"FORBIDDEN",
              "message":"You do not have permission to perform this action","details":[]}}

A3  member  POST /projects          -> 403   (same body)
B2  manager POST /users             -> 403   (same body)
C2  member  POST /tasks/1/assign    -> 403   (same body)

D2  admin   PATCH /tasks/1/status   -> 403
    {"error":{"code":"FORBIDDEN",
              "message":"You can only update the status of tasks assigned to you","details":[]}}
```

### Evidence that 401 precedes 403

```text
A4  anonymous POST /projects        -> 401
    {"error":{"code":"UNAUTHENTICATED",
              "message":"Missing or invalid authentication credentials","details":[]}}

D3  anonymous PATCH /tasks/1/status -> 401   (same body)
```