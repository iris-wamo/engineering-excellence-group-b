# Single Sign-On (OIDC): How It Works and What It Would Change in TaskFlow

## 1. Purpose
This document explains single sign-on (SSO) with OpenID Connect (OIDC) in plain terms and
describes what supporting it would change in TaskFlow. It covers:
- What problem SSO solves and why larger customers ask for it
- What an identity provider (IdP) does
- How an OIDC login works, step by step
- How TaskFlow must validate what the identity provider sends back
- What would change in TaskFlow's data model, login, workspaces, and roles
- Risks, trade-offs, and a recommendation

The goal is shared background and engineering judgment, not a production integration. It is
meant to inform the design of signup and login (#70) and roles and permissions (#71) so that
SSO can be added later without a rewrite.

## 2. The Problem SSO Solves
Without SSO, every tool a company uses has its own username and password. For a company with
hundreds of employees this causes real problems:

- **Too many passwords.** Employees reuse weak passwords across tools.
- **Offboarding is slow and error-prone.** When someone leaves, IT must remember to remove them
  from every tool individually. A forgotten account is a security hole.
- **Security policy is inconsistent.** IT cannot enforce MFA, password rules, or login from
  managed devices in tools it does not control.

With SSO, the company keeps **one account per employee** in a central system (the identity
provider). Every tool, including TaskFlow, asks that system "who is this?" instead of
checking a password itself.

- Employees log in once with their company account.
- IT disables one account and the person loses access to every connected tool.
- MFA and other policies are enforced in one place.

For this reason, enterprise customers commonly treat SSO as a **purchase requirement**, not a
nice-to-have.

## 3. Key Terms

| Term | Plain meaning |
|------|---------------|
| **Identity Provider (IdP)** | The system that owns user accounts and checks who someone is. Examples: Google Workspace, Microsoft Entra ID (Azure AD), Okta, Keycloak. |
| **Relying Party (RP) / Client** | The application that trusts the IdP to log users in. Here: TaskFlow. |
| **OAuth 2.0** | A standard for granting an app *access* to something (authorization). It does not by itself say *who* the user is. |
| **OpenID Connect (OIDC)** | A thin identity layer on top of OAuth 2.0 that adds *authentication*: a standard way to learn who the user is. |
| **ID token** | A signed JSON Web Token (JWT) from the IdP that says who logged in. This is what TaskFlow uses for login. |
| **Access token** | A token for calling APIs (e.g. the IdP's user-info endpoint). Not proof of identity for TaskFlow's purposes. |
| **Claims** | Fields inside the ID token, e.g. `sub` (stable user ID at the IdP), `iss` (issuer), `aud` (audience = our client ID), `exp` (expiry), `email`, `email_verified`, `name`, `nonce`. |
| **Discovery document** | A JSON file at `<issuer>/.well-known/openid-configuration` listing the IdP's endpoints and supported features. |
| **JWKS** | "JSON Web Key Set": the IdP's public keys, used to verify the ID token's signature. |
| **Client ID / Client secret** | Credentials TaskFlow receives when it is registered as an application in the customer's IdP. |
| **SAML 2.0** | An older, XML-based SSO standard. Still widely used in enterprises; many customers ask for "SAML or OIDC". OIDC is simpler and JSON-based, so it is the better starting point. |

The single most important claim is **`sub`** (subject). It is the IdP's permanent ID for the
user. Emails can change; `sub` does not. TaskFlow should link accounts by
`(issuer, sub)`, not by email.

## 4. What an Identity Provider Does
The IdP is the **source of truth for identity**. Its responsibilities:

1. **Stores accounts.** The company's employees, their names, emails, and status.
2. **Authenticates users.** Checks passwords, MFA codes, security keys, device posture.
   TaskFlow never sees the user's password.
3. **Issues signed tokens.** After login, it gives the application a signed ID token stating
   who the user is. The signature lets the application trust it without calling back.
4. **Holds groups and attributes.** E.g. `Engineering`, `Engineering-Managers`. These can be
   sent as claims and optionally used for authorization.
5. **Enforces policy.** MFA requirements, session length, allowed locations or devices.
6. **Controls access centrally.** IT assigns which users may use TaskFlow and disables users
   when they leave. Optionally pushes these changes to apps automatically (SCIM, see §7.6).

TaskFlow's job shrinks to: **redirect to the IdP, verify what comes back, and map that
identity to a TaskFlow user.**

## 5. How an OIDC Login Works
The recommended flow for web applications is the **Authorization Code flow with PKCE**.

```
 Browser                      TaskFlow API                         Identity Provider
    |                              |                                       |
    | 1. Click "Log in with SSO"   |                                       |
    |----------------------------->|                                       |
    |                              | 2. Generate state, nonce,             |
    |                              |    PKCE code_verifier; store them     |
    | 3. 302 redirect to IdP /authorize?client_id&redirect_uri&scope=openid email profile
    |    &state&nonce&code_challenge                                       |
    |<-----------------------------|                                       |
    |------------------------------------------------------------------->|
    |                              |        4. User logs in at the IdP     |
    |                              |           (password, MFA, ...)        |
    | 5. 302 redirect to TaskFlow /callback?code=...&state=...             |
    |<-------------------------------------------------------------------|
    |----------------------------->|                                       |
    |                              | 6. Check state matches                |
    |                              | 7. POST /token (code, code_verifier,  |
    |                              |    client_id, client_secret)          |
    |                              |-------------------------------------->|
    |                              | 8. { id_token, access_token }         |
    |                              |<--------------------------------------|
    |                              | 9. Validate ID token (see §6)         |
    |                              | 10. Find or create TaskFlow user      |
    |                              |     by (issuer, sub)                  |
    | 11. TaskFlow session / JWT   |                                       |
    |<-----------------------------|                                       |
```

Step by step, in plain terms:

1. The user clicks **"Log in with SSO"** (or enters their work email, and TaskFlow detects
   that their company uses SSO).
2. TaskFlow creates three random values and remembers them for this login attempt:
   - `state`: protects against cross-site request forgery on the callback.
   - `nonce`: ties the ID token to this specific login, preventing replay.
   - PKCE `code_verifier` (and its hash, `code_challenge`): ensures only TaskFlow can redeem
     the code.
3. TaskFlow redirects the browser to the IdP's authorization endpoint.
4. The user logs in **at the IdP**, which applies MFA and company policy.
5. The IdP redirects back to TaskFlow's callback URL with a short-lived, one-time `code`.
6. TaskFlow checks that `state` matches what it stored.
7. TaskFlow's backend (not the browser) exchanges the `code` at the IdP's token endpoint,
   sending the `code_verifier` and its client credentials.
8. The IdP returns an ID token (and an access token).
9. TaskFlow validates the ID token.
10. TaskFlow finds the user linked to `(issuer, sub)`, or creates or links one according to
    its provisioning rules.
11. TaskFlow issues **its own** session or JWT, exactly as it would after a password login.
    From here on, the rest of the API does not care how the user logged in.

## 6. Validating the ID Token (Checklist)
Most real-world OIDC vulnerabilities come from skipping one of these checks. A vetted library
(e.g. Authlib for Python) should do this, not hand-written code.

- [ ] **Signature** is valid, using a key from the IdP's JWKS, with an expected algorithm
      (e.g. `RS256`); never accept `alg: none`.
- [ ] **`iss`** exactly matches the issuer configured for this workspace.
- [ ] **`aud`** contains TaskFlow's client ID.
- [ ] **`exp`** is in the future and **`iat`** is recent (allow small clock skew).
- [ ] **`nonce`** matches the value stored at step 2.
- [ ] **`state`** on the callback matched (checked before the token exchange).
- [ ] **`email`** is used only if **`email_verified`** is `true`, and its domain is allowed
      for this workspace.
- [ ] The `code` is single-use and the stored `state`/`nonce`/`code_verifier` are deleted
      after use.

## 7. What Would Change in TaskFlow
Current state (session-04 baseline): `app/models/user.py` defines `User` with only `id`,
`name`, `email` (unique), and `is_active`. There are no passwords, workspaces, or login yet,
and `app/auth/` is empty. Signup and login arrive with #70; roles with #71.

### 7.1 Data model
- **Keep `User` as TaskFlow's own user.** Do not put IdP details directly on it.
- **Add a linked-identity table**, e.g. `user_identity`:

  | Column | Notes |
  |--------|-------|
  | `id` | PK |
  | `user_id` | FK → `user.id` |
  | `provider_id` | FK → the workspace's SSO configuration (or the issuer string) |
  | `subject` | The IdP's `sub` claim |
  | `email_at_link` | For audit/debugging |
  | `created_at`, `last_login_at` | |

  Unique constraint on `(provider_id, subject)`. One user can have several identities
  (e.g. password and SSO during a migration).
- **Passwords must be optional.** When #70 adds `password_hash`, it should be nullable so
  SSO-only users can exist.

### 7.2 Login (#70)
- Keep email/password login. Add two endpoints alongside it:
  - `GET /api/v1/auth/sso/{workspace_slug}/login` → builds the authorize URL, redirects.
  - `GET /api/v1/auth/sso/{workspace_slug}/callback` → validates and issues a TaskFlow session.
- After SSO succeeds, TaskFlow issues the **same session/JWT format** as password login, so
  every other endpoint and the RBAC checks stay unchanged.
- Optional "home realm discovery": the user types their email, TaskFlow looks up the domain,
  and redirects to the right IdP.

### 7.3 Signup and provisioning
Two common models; workspaces should be able to choose:
- **Just-in-time (JIT) provisioning:** the first successful SSO login creates the TaskFlow
  user automatically, limited to verified emails on the workspace's allowed domains.
- **Invite-only:** an admin invites the user first; SSO login only links to an existing
  invited user.

### 7.4 Workspaces
SSO is configured **per customer workspace**, since each company has its own IdP. A
workspace SSO configuration would hold:
- Issuer URL (the discovery document is fetched from it)
- Client ID and client secret (secret encrypted at rest, never logged or returned by the API)
- Allowed email domains (e.g. `acme.com`)
- "Enforce SSO" flag: when on, password login is disabled for that workspace's members,
  except a break-glass admin
- Provisioning mode (JIT or invite-only) and default role for new users

### 7.5 Roles and permissions (#71)
`docs/rbac-authorization-matrix.md` defines `admin`, `manager`, and `member`. Two options:
- **Roles managed in TaskFlow (recommended to start):** the IdP only proves identity;
  TaskFlow admins assign roles as today. Simple and predictable.
- **Group-to-role mapping (later):** the workspace maps IdP groups to TaskFlow roles, e.g.
  `Engineering-Managers` → `manager`. Roles then update on each login. Powerful, but
  misconfigured mappings can grant too much access, so it needs audit logging.

Either way, #71 should store roles in TaskFlow so authorization does not depend on how the
user logged in.

### 7.6 Offboarding and sessions
- Disabling a user in the IdP **only blocks new logins**. Existing TaskFlow sessions stay
  valid until they expire. Keep TaskFlow access tokens short-lived (e.g. 15–60 minutes)
  and refresh through the IdP or require re-login.
- **SCIM** (System for Cross-domain Identity Management) is the standard that lets the IdP
  push user creation, updates, and deactivation to TaskFlow automatically. It is a natural
  follow-up for enterprise customers, not part of a first SSO version.

### 7.7 Code layout
`app/auth/` (currently empty) is the natural home: e.g. `app/auth/sso/` for the OIDC client,
token validation, and callback handling, keeping it separate from password login.

## 8. Risks and Trade-offs

| Risk | Why it matters | Mitigation |
|------|----------------|------------|
| **Account-linking takeover** | If TaskFlow links an SSO login to an existing user purely by email, anyone who controls that email at *any* IdP could take over the account. | Link by `(issuer, sub)`; only link by email when `email_verified` is true **and** the domain belongs to that workspace; require the user to confirm linking. |
| **Weak token validation** | Skipping `aud`, `iss`, `nonce`, or signature checks lets attackers forge or replay logins. | Use a vetted library; test each check in §6 with negative tests. |
| **Client secret exposure** | A leaked secret lets someone impersonate TaskFlow to the IdP. | Encrypt at rest, never return via API, rotate on request. |
| **IdP outage = no logins** | If a customer's IdP is down, their users cannot log in. | Break-glass admin account with password + MFA. |
| **Testing complexity** | Real IdPs are hard to use in CI. | Run a mock IdP in Docker (Keycloak or `mock-oauth2-server`) for integration tests. |
| **Per-customer support load** | Each customer's IdP setup is slightly different. | Clear setup docs; a "test connection" button; good error messages on the callback. |
| **Build vs buy** | Building SSO, SAML, and SCIM in-house is significant ongoing work. | Consider a broker (Auth0, WorkOS, Keycloak) that speaks every IdP and gives TaskFlow one integration. |

## 9. Recommendation
- **Design #70 and #71 so SSO fits in later:**
  - Make `password_hash` nullable.
  - Keep external identities in a separate table keyed by `(issuer, sub)`, not on `User`.
  - Have every login method end in the same TaskFlow session/JWT.
  - Keep roles owned by TaskFlow, so the authorization layer is independent of login method.
  - Keep access tokens short-lived.
- **When a customer asks for SSO:** start with OIDC Authorization Code + PKCE via a library
  (Authlib), per-workspace configuration, invite-only provisioning, and a mock IdP in tests.
  Re-evaluate a broker if SAML or SCIM becomes a requirement.

## 10. References
- OpenID Foundation, *How OpenID Connect Works*: https://openid.net/developers/how-connect-works/
- *OpenID Connect Core 1.0*: https://openid.net/specs/openid-connect-core-1_0.html
- *OpenID Connect Discovery 1.0*: https://openid.net/specs/openid-connect-discovery-1_0.html
- RFC 6749, *The OAuth 2.0 Authorization Framework*: https://www.rfc-editor.org/rfc/rfc6749
- RFC 7636, *Proof Key for Code Exchange (PKCE)*: https://www.rfc-editor.org/rfc/rfc7636
- RFC 7519, *JSON Web Token (JWT)*: https://www.rfc-editor.org/rfc/rfc7519
- RFC 7644, *SCIM Protocol*: https://www.rfc-editor.org/rfc/rfc7644
- OWASP, *OAuth 2.0 Cheat Sheet*: https://cheatsheetseries.owasp.org/cheatsheets/OAuth2_Cheat_Sheet.html
- Auth0, *Authorization Code Flow with PKCE*: https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce
- Authlib (Python OIDC client library): https://docs.authlib.org/
