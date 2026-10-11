# Demo 05 — SSO (OIDC) Research

## Loom Video
Loom: <add link after recording>

## Objective
Explain, in plain terms, how single sign-on with OpenID Connect (OIDC) works, what an
identity provider does, and what supporting SSO would change in TaskFlow. This is research
only; no production integration is built.

Full notes: [`docs/sso-oidc-research.md`](../../../docs/sso-oidc-research.md)

## Scenario
A larger customer ("Acme Corp") wants to evaluate TaskFlow. Their IT team requires that
employees log in with their existing company account (e.g. Microsoft Entra ID or Okta),
with MFA enforced by IT, and that disabling an employee in one place removes their access
to TaskFlow. TaskFlow today has no login at all (`app/auth/` is empty; signup and login
arrive with #70, roles with #71). What would we need?

## Commands / Steps Used
1. Read the OIDC specs and provider docs listed in the References section of the notes.
2. Inspected a real identity provider's discovery document to see what TaskFlow would
   configure against:
   ```bash
   curl -s https://accounts.google.com/.well-known/openid-configuration | python3 -m json.tool
   ```
3. Inspected the current TaskFlow user model to see what would need to change:
   `app/models/user.py` (fields: `id`, `name`, `email`, `is_active`).
4. Mapped the findings onto the planned work in #70 (signup/login) and #71 (roles), and
   onto `docs/rbac-authorization-matrix.md`.

## Expected Behavior
In a future SSO login, TaskFlow would:
1. Redirect the user to the customer's identity provider.
2. Never see the user's password; the IdP handles password + MFA.
3. Receive a one-time code, exchange it server-side for a signed ID token.
4. Validate the token (signature, `iss`, `aud`, `exp`, `nonce`, `state`).
5. Find or create the TaskFlow user by `(issuer, sub)` and issue its own session/JWT, so
   all existing endpoints and RBAC checks work unchanged.

## Actual Findings
- **OIDC = OAuth 2.0 + identity.** OAuth 2.0 grants access; OIDC adds a signed **ID token**
  saying *who* logged in. The recommended web flow is **Authorization Code + PKCE**.
- **The IdP is the source of truth** for accounts, authentication, MFA, groups, and
  deactivation. TaskFlow's job is to redirect, validate, and map identities.
- **Discovery makes configuration small.** Given only an issuer URL, TaskFlow can fetch all
  endpoints and signing keys. Each customer workspace would store: issuer URL, client ID,
  client secret, allowed email domains, provisioning mode, and an "enforce SSO" flag.
- **Link by `(issuer, sub)`, not by email.** Emails change and can be claimed at other IdPs;
  linking by email alone enables account takeover.
- **Changes in TaskFlow** (details in §7 of the notes):
  - New `user_identity` table (`user_id`, provider, `subject`), unique on provider + subject.
  - `password_hash` (from #70) must be nullable for SSO-only users.
  - New `/api/v1/auth/sso/{workspace_slug}/login` and `/callback` endpoints.
  - Per-workspace SSO configuration (requires workspaces).
  - Roles stay owned by TaskFlow (#71); optional IdP-group → role mapping later.
  - Short-lived TaskFlow sessions, since disabling a user at the IdP only blocks *new* logins.

## Evidence
Google's public discovery document (trimmed), fetched with the command above:

```json
{
  "issuer": "https://accounts.google.com",
  "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
  "token_endpoint": "https://oauth2.googleapis.com/token",
  "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
  "id_token_signing_alg_values_supported": ["RS256"],
  "code_challenge_methods_supported": ["plain", "S256"]
}
```

This shows the pieces TaskFlow relies on: where to send the user (`authorization_endpoint`),
where to redeem the code (`token_endpoint`), where to get keys to verify the ID token
(`jwks_uri`), and PKCE support (`S256`).

Example decoded ID token payload (illustrative values):

```json
{
  "iss": "https://login.acme-idp.example.com",
  "sub": "00u1a2b3c4D5e6F7g8h9",
  "aud": "taskflow-client-id",
  "exp": 1791300000,
  "iat": 1791296400,
  "nonce": "n-0S6_WzA2Mj",
  "email": "jane.doe@acme.com",
  "email_verified": true,
  "name": "Jane Doe"
}
```

## What We Learned
- SSO is mainly a **login front door**: after it, TaskFlow should issue the same session as
  password login, so the rest of the system does not change.
- Most of the work, and the risk, is in **token validation** and **account linking**, both of
  which should rely on a vetted library (e.g. Authlib) rather than custom code.
- Small design choices in #70 and #71 now (nullable password, separate identity table,
  TaskFlow-owned roles, short-lived tokens) make SSO cheap to add later.
- Enterprise requirements often grow from OIDC to **SAML** and **SCIM**; at that point an
  identity broker (Auth0, WorkOS, Keycloak) may be cheaper than building everything.

## Open Questions
- Provisioning: just-in-time on first login, invite-only, or configurable per workspace?
- Roles: TaskFlow-managed only, or support IdP group → role mapping?
- Do we expect customers to require SAML, not just OIDC?
- Build in-house with Authlib, or use a broker?
- When SSO is enforced for a workspace, who is the break-glass admin if the IdP is down?
