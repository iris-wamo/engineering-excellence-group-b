# Demo 03 — Authentication & RBAC

> Scope note: this demo covers **authentication only** (signup, login, identifying the caller).


## Objective
Prove that the API can:

1. Register a user and store only a hash of their password.
2. Exchange valid credentials for a JWT access token.
3. Identify which user is making a request from that token.
4. Reject missing, invalid, and expired credentials with one consistent 401 error.

## Scenario
A new user signs up, logs in, and calls a protected endpoint. We then repeat the same calls with
bad credentials and with no credentials at all, to confirm the API fails closed and never leaks
whether an email exists or what the stored password looks like.

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