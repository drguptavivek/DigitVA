# Per-project OAuth2 / OIDC SSO with claim-to-role mapping

Status: planned (no code written)
Priority: P1
Created: 2026-09-26
Owner decision recorded: 2026-09-26

## Goal

Let any project authenticate its people through its own identity provider, and let
an administrator decide — per project — which token claim value grants which
DigitVA role on which project site or organization unit. Different projects may
point at different providers.

## Decisions taken with the owner (2026-09-26)

1. **User linking** — configurable per connection: `existing_only` (default) or
   `link_or_create_by_email`. With `existing_only`, an SSO login for an unknown
   user is refused rather than creating a row.
2. **Grant ownership** — SSO owns the grants it creates. On every SSO login the
   desired grant set is recomputed from the claims: grants tagged to this
   connection that no longer match are deactivated, matching ones are created or
   reactivated. Grants created by an admin are never touched.
3. **Scope** — a mapping row may target a project, a project site, or an
   organization unit. The target is either pinned on the row or resolved at
   login from a second claim whose values are looked up against the external
   (SSO) ids we hold for project sites and org units.
4. **Global admin** — a claim mapping can never grant the `admin` role. The
   column check and the service both refuse it at save time. Only the existing
   admin endpoints create an admin grant.
5. **Federation, not replacement** — SSO is *federation*: a person signs in with
   whichever credential their project offers, a DigitVA password or the
   project's own IdP. `/vaauth/valogin` keeps the password form and additionally
   lists the active connections as "Sign in with …" buttons. Nothing is disabled
   for SSO users and nothing is required of them; no login-time enforcement of
   SSO-only projects is in this scope. The consequence to be aware of is that a
   person can hold both a password and a linked SSO identity for the same
   `va_users` row, and revoking one does not revoke the other — the IdP stops
   granting, the password still works. Deliberately linking an existing account
   to an IdP from the profile page is a follow-up (see Deferred), because it is
   a support workflow rather than a login path.
6. **Dependencies** — `jmespath` and `pyjwt` are added through the normal
   `uv add` workflow inside `minerva_app_service`. A previously recorded
   "standard library only, do not `uv add`" constraint was confirmed on
   2026-09-26 to have applied to a different area, not DigitVA application
   code, and is cleared. `cryptography` is already declared, so neither library
   introduces a crypto backend and neither has transitive dependencies.
   `Authlib` was considered and rejected: it is a full framework carrying a
   *server* implementation (JWE, JWKS and introspection endpoints) whose recent
   advisories all sit in that server-side JWE surface, none of which DigitVA
   would use as a client — not disqualifying, but it means importing a large
   body of unused code into the authentication path, plus a session model and a
   configurable-and-therefore-easily-permissive `claims_options` check set.

## Context

Verified against the tree on 2026-09-26:

- Authentication is Flask-Login over a server-side Flask-Session store
  (`va_sessions`, `SESSION_USE_SIGNER`), `PERMANENT_SESSION_LIFETIME` 30 min,
  login at `app/routes/va_auth.py:19-66`, logout POST at `:68-75`. CSRF is
  global Flask-WTF with `X-CSRFToken` accepted (`app/__init__.py:15-51`).
- `va_users` (`app/models/va_users.py:13-57`) has **no** external-identity
  column. `email` is unique and is the only login key today. There is no
  `last_login`.
- Authorization is **not** a column on the user. It is rows in
  `va_user_access_grants` (`app/models/va_user_access_grants.py:103-165`):
  `role` (`VaAccessRoles`), `scope_type` (`VaAccessScopeTypes` =
  `global|project|project_site|org_unit`), and exactly one of `project_id`,
  `project_site_id`, `org_unit_id`. Lifecycle is `grant_status`
  `active`/`deactive`; there is **no** expiry column. Partial unique indexes
  make (user, role, scope-id) unique per scope.
- `mas_org_unit` is project-scoped with `unit_code`, `parent_org_unit_id` and a
  materialized `LTREE` `path` (`app/models/mas_organization.py:90-146`);
  `(project_id, unit_code)` is unique. Subtree access already works: an org-unit
  grant covers the node's descendants through `path <@`
  (`app/services/org_grant_service.py:179-208`), so **one grant covers a whole
  subtree** and we never need to write N grants.
- Sites: `va_site_master` (shared catalog) plus `va_project_sites` (project
  join, unique `(project_id, site_id)`, `coding_enabled`, start/end dates).
  `va_sites` is legacy and out of scope.
- Per-external-system configuration precedent: `mas_odk_connections` holds typed
  columns, encrypts credentials with `app/utils/credential_crypto.py`
  (Fernet, PBKDF2-HMAC-SHA256 260 000 iterations, per-value random salt, pepper
  from config) and keeps shared health/cooldown state on the row.
- HTTP convention on request paths (`app/services/attachment_source_central.py:219-360`):
  `requests` session, `HTTPAdapter(max_retries=0)`, explicit
  `timeout=(connect, read)`, `allow_redirects=False`, capped response size, no
  secrets or bodies in logs. The SSO client copies this.
- Dependencies already available: `requests`, `cryptography>=42.0.0`,
  `Flask-Limiter`, `flask-caching`, `itsdangerous`, `flask-talisman`. Two are
  added by this work, `jmespath` and `pyjwt` (decision 6): `jmespath` for claim
  extraction and `PyJWT` for signature verification, backed by the
  already-present `cryptography`, so neither adds a crypto backend and neither
  has transitive dependencies.
- Reverse proxy: `ProxyFix(x_for=1, x_proto=1, x_host=1)` at
  `app/__init__.py:172-175`, nginx forwards `Host`/`X-Forwarded-*` in
  `deploy/doris-public-nginx.conf`.

## Scope

In scope: OAuth2 Authorization Code + PKCE against a per-project provider;
OpenID Connect ID-token verification and OAuth2 userinfo; per-project claim-to-
role-and-scope mappings; SSO ids on project sites and org units; grant
reconciliation; admin configuration UI; login page entry points; documentation.

Out of scope (deliberately):

- SAML 2.0.
- Access/refresh token storage, token refresh, and API calls to the provider.
- Front-channel or back-channel logout, and RP-initiated `id_token_hint`
  logout. Local logout is unchanged.
- Rate-limited or policy-driven "SSO only" enforcement of the password form
  (decision 5).
- Any change to how authorization is *evaluated* at request time. Grants remain
  the single source of truth, so exports, dashboards and audit keep working.

## Data model

Six new tables (all additive, all empty on deploy) and one added column pair.
Naming follows the repository rule: `mas_*` master, `map_*` mapping, `auth_*`
authorization.

### `auth_sso_connections` — one row per project provider

| Column | Type | Notes |
|---|---|---|
| `sso_connection_id` | UUID | PK, ORM default |
| `project_id` | String(6) | FK `va_project_master.project_id`, NOT NULL |
| `connection_code` | Text | URL slug, unique, e.g. `ka-gsuit` |
| `connection_name` | Text | shown on the login page |
| `provider_kind` | Text | check in (`oidc`, `oauth2`) |
| `issuer_url` | Text | required when `provider_kind='oidc'` |
| `discovery_url` | Text | nullable; defaults to `<issuer>/.well-known/openid-configuration` |
| `discovery_issuer` | Text | the `issuer` value pinned from the first successful discovery |
| `authorization_endpoint` | Text | nullable; NULL means "take it from discovery" |
| `token_endpoint` | Text | nullable; same |
| `userinfo_endpoint` | Text | nullable; same |
| `jwks_uri` | Text | nullable; same |
| `end_session_endpoint` | Text | nullable; stored for the future logout work, unused in this scope |
| `client_id` | Text | NOT NULL |
| `client_secret_enc` / `client_secret_salt` | Text | Fernet-encrypted; both NULL for a public client |
| `token_endpoint_auth_method` | Text | check in (`client_secret_basic`, `client_secret_post`, `none`); default `client_secret_basic` |
| `id_token_signing_algs` | Text[] | allowlist, default `{RS256}`; symmetric algorithms are rejected on save |
| `scopes` | Text[] | default `{openid, profile, email}` |
| `api_audience` | Text | nullable; the API/resource audience, sent as `audience=` for Auth0-style providers and as `resource=` (RFC 8707) for Keycloak/Okta/Entra. A typed column rather than a free-form parameter bag: it is the only non-standard authorize parameter any of the target providers actually requires, and a JSONB passthrough would reintroduce an opaque settings blob in a table whose convention is typed columns |
| `pkce_required` | Boolean | default true; false is rejected (see Risks) |
| `identity_source` | Text | check in (`id_token`, `userinfo`); default `id_token` |
| `subject_claim` | Text | default `sub` |
| `email_claim` | Text | default `email` |
| `name_claim` | Text | default `name` |
| `email_verified_claim` | Text | default `email_verified`; required to be truthy before an email-based link |
| `user_provisioning_mode` | Text | check in (`existing_only`, `link_or_create_by_email`); default `existing_only` |
| `unmapped_scope_policy` | Text | check in (`skip`, `deny_login`); default `skip` |
| `discovery_checked_at` | DateTime | last successful discovery |
| `discovery_last_error` | Text | never contains the discovery response body |
| `connection_status` | status_enum | default `active` |
| `notes`, `created_by_user_id`, `created_at`, `updated_at` | | audit |

Constraint: a pinned `discovery_issuer` that disagrees with a later discovery
document is a hard error and the connection is marked with
`discovery_last_error` — this is the mix-up defence, and it is enforced on every
refresh, not only on save.

### `auth_sso_claim_mappings` — the rules

| Column | Type | Notes |
|---|---|---|
| `mapping_id` | UUID | PK |
| `sso_connection_id` | UUID | FK `auth_sso_connections`, NOT NULL |
| `mapping_name` | Text | unique with `sso_connection_id` |
| `claim_source` | Text | check in (`id_token`, `userinfo`, `any`) |
| `claim_name` | Text | JMESPath expression over the claims object, e.g. `groups`, `realm_access.roles`, `resource_access.*.roles`, `groups[*].name`, `"https://tenant/roles"`. Compiled and syntax-checked at save time |
  There is deliberately **no** separate "value path" column. A claim that is a
  list of objects is addressed by the same expression as everything else
  (`groups[*].name`), so there is one mechanism to document, one to validate and
  one to test, instead of two that overlap. The expression only *selects values*;
  the authorization decision stays in the typed columns of this table.
| `claim_matcher` | Text | check in (`equals`, `in_list`, `prefix`, `regex`) |
| `expected_audience` | Text | nullable; the rule only applies when the token audience contains this value (the AUD axis) |
| `grant_role` | access_role_enum | **check `grant_role <> 'admin'`** (decision 4) |
| `grant_scope_type` | access_scope_enum | check in (`project`, `project_site`, `org_unit`) |
| `fixed_project_site_id` | UUID | FK `va_project_sites`, nullable |
| `fixed_org_unit_id` | UUID | FK `mas_org_unit`, nullable |
| `scope_claim_source` | Text | nullable; same domain as `claim_source` |
| `scope_claim_name` | Text | nullable; the same JMESPath expression |
| `scope_match_mode` | Text | nullable; same domain as `claim_matcher` |
| `scope_include_subtree` | Boolean | default false; `org_unit` only (an org-unit grant already covers the subtree) |
| `mapping_status` | status_enum | default `active` |
| `notes`, `created_by_user_id`, `created_at`, `updated_at` | | audit |

Table check: exactly one target axis is chosen — either a fixed
(`fixed_project_site_id` xor `fixed_org_unit_id`) or a dynamic
`scope_claim_name` (with `scope_match_mode` and `scope_claim_source` set). A
`project`-scope row carries neither. A `project_site` row may not set
`scope_include_subtree`.

### `map_user_sso_identities` — the external subject link

| Column | Type | Notes |
|---|---|---|
| `identity_id` | UUID | PK |
| `sso_connection_id` | UUID | FK, NOT NULL |
| `issuer` | Text | the pinned issuer, stored per identity so a re-pointed connection cannot inherit old links |
| `subject` | Text | the `sub`/subject claim value |
| `user_id` | UUID | FK `va_users.user_id`, NOT NULL |
| `email_hash` | Text | `sha256(lower(email_claim))`; lets us detect an email change without storing the address |
| `linked_by` | Text | check in (`existing_only`, `email_match`, `admin`, `jit_create`) |
| `last_login_at` | DateTime | |
| `identity_status` | status_enum | default `active` |

Unique on `(sso_connection_id, issuer, subject)` and on
`(user_id, sso_connection_id)`. The email address itself is never copied into
this table.

### `map_project_site_sso_ids` and `map_org_unit_sso_ids` — the SSO id on each unit and site

Identical shape, differing only in the target FK:

| Column | Type | Notes |
|---|---|---|
| `project_site_sso_id_id` / `org_unit_sso_id_id` | UUID | PK |
| `sso_connection_id` | UUID | FK, NOT NULL |
| `project_site_id` / `org_unit_id` | UUID | FK, NOT NULL |
| `sso_external_id` | Text | NOT NULL |
| `mapping_status` | status_enum | default `active` |

Unique on `(sso_connection_id, sso_external_id)` and on
`(sso_connection_id, target_id)`.

Why a table and not a column: `va_site_master` is a catalog shared across
projects, and `mas_org_unit` is project-scoped, but an SSO id is only
meaningful against one connection. One connection per project is the common
case, yet a second provider for the same project must not overwrite the first
provider's ids. Unique constraints also make a duplicate external id impossible
at the database level rather than at resolution time.

### `va_user_access_grants` — two added columns

| Column | Type | Notes |
|---|---|---|
| `sso_connection_id` | UUID | FK `auth_sso_connections`, nullable |
| `sso_mapping_id` | UUID | FK `auth_sso_claim_mappings`, nullable |

Table check: both NULL (an admin grant) or both set (an SSO grant). This is what
makes reconciliation safe — `WHERE sso_connection_id = :id` is the whole
ownership boundary. Partial index on `(sso_connection_id)` where
`grant_status = 'active'`.

## Claim to grant resolution

`app/services/sso/sso_claim_resolver.py` turns a verified claim set into
`DesiredGrant(role, scope_type, scope_id, mapping_id)`; nothing else in the app
reads the token.

```
resolve(connection, id_token_claims, userinfo_claims):
    for rule in active rules of connection (ordered by mapping_name for determinism):
        if rule.expected_audience and not audience_contains(aud, rule.expected_audience):
            continue
        values = claim_values(rule.claim_source, rule.claim_name, merged_claims)
        if not matcher_matches(rule.claim_matcher, rule.claim_values, values):
            continue
        for (scope_type, scope_id) in targets(rule, merged_claims):
            yield DesiredGrant(rule.grant_role, scope_type, scope_id, rule.mapping_id)

targets(rule, claims):
    if rule.grant_scope_type == 'project':        -> [(project, connection.project_id)]
    if rule.fixed_project_site_id / fixed_org_unit_id -> that one
    else:                                         -> external_id_lookup(
                                                      rule.scope_claim_name values,
                                                      map_project_site_sso_ids / map_org_unit_sso_ids,
                                                      match mode)
```

`external_id_lookup` is one batched query per table with `= ANY(:ids)`, plus a
`LIKE 'value%'` query when the match mode is `prefix`. An external id that
matches more than one row is **skipped and audited**, never guessed. An
external id that matches nothing is skipped and audited; if the connection's
`unmapped_scope_policy` is `deny_login` the whole login is refused instead.

## Claim extraction with JMESPath

Nested claims are the normal case, and **no OIDC or OAuth RFC defines a syntax
for addressing them**: RFC 7519 §4 permits any JSON value as a claim value but
specifies no path syntax; OIDC Core §5.1.1 standardises a flat set of string
claims and the one standard object-valued claim is `address`; there is no
`groups` or `roles` claim in OIDC at all; RFC 9068 is flat too. The dot
convention (`realm_access.roles`) seen across the ecosystem is de-facto
practice, not a specification. RFC 6901 JSON Pointer was considered as the
"real" standard and rejected: it is a location syntax only, so the common
shapes still need an invented wildcard, a client-id substitution and a
literal-name escape hatch — i.e. a private grammar bolted onto a standard.

**`jmespath` is the right tool and is a permitted dependency (decision 6).**
It is a spec'd expression language, pure Python, with no transitive
dependencies, and it already implements every shape the target providers emit.
It is the same expression language AWS uses for this class of problem, so it is
battle-tested on nested, untrusted JSON rather than novel.

`claim_name` and `scope_claim_name` hold a **JMESPath expression**. The
expression is compiled and syntax-checked at save time, so a malformed
expression is rejected by the API, not discovered during someone's login.

| Provider claim shape | Expression |
|---|---|
| flat `groups: ["a","b"]` | `groups` |
| Keycloak realm roles | `realm_access.roles` |
| Keycloak client roles | `resource_access.*.roles` |
| Okta `groups: [{"id","name"}]` | `groups[*].name` |
| Okta group ids | `groups[*].id` |
| Auth0 namespaced claim | `"https://tenant.example/roles"` |
| one value from a list | `groups[0]` |

Three things this buys that the hand-rolled design could not:

- `resource_access.*.roles` is a **projection over every client**, so the
  `<client_id>` substitution, its save-time staleness problem and its
  "visible failure" mitigation all disappear — there is nothing to substitute.
- `"https://tenant.example/roles"` is a quoted JMESPath identifier, so a claim
  name containing dots and slashes needs no escaping scheme, no
  exact-key-before-traversal precedence rule, and no argument about which one
  wins. RFC 9068 §2.2.1 also recommends exactly this URI-namespaced shape for
  custom claims, so it is the direction the ecosystem is already moving.
- Filters (`groups[?@ == 'coder']`, `length(...)`) are available, which is what
  makes the missing-claim detector and the claims inspector straightforward.

`app/services/sso/claim_reader.py` compiles each active rule's expression once
per login, evaluates it against the chosen source's claims object, and
normalises the result to a flat list of strings: a scalar becomes one element, a
list becomes its string elements, a list of objects is only ever produced by an
explicit `[*]` so a stray `groups` never yields `[object Object]`. Anything that
does not evaluate to a string or list of strings — a number, a nested object, a
`null` — is a rule configuration error and is reported as such, not coerced.

**The architectural line: expressions read claims, declarative rows decide
access.** JMESPath is used to *select values*; the authorization decision stays
in typed `auth_sso_claim_mappings` rows — role, scope type, matcher, fixed
target, expected audience. An administrator auditing "who can be a coder on
site ICMR01NC0201" must be able to read rows, not an expression that also
decides the role. This also keeps the `admin` prohibition enforceable: the role
is a column with a check constraint, not something buried in a string.

**Untrusted input is still bounded**, even though the parsing is now someone
else's: the token response is size-capped by `sso_http.py` before it reaches
this code, every expression is compiled rather than interpreted from an
unbounded string at request time, and `SSO_MAX_GRANTS_PER_LOGIN` caps what a
single login can produce.

**Flat claims are supported too and need nothing special.** Where a provider
will emit a flat `groups` or `roles` string array the expression is just
`groups`. But that is a convenience, not a requirement: every nested shape in
the provider matrix below is a first-class supported input, not a fallback we
tolerate. For Keycloak, `realm_access.roles` and `resource_access.*.roles` are
in practice *the* way roles are configured, so nested access is the normal
path, not an edge case.

## Provider compatibility

This table is **normative**: every row is a shape DigitVA commits to
supporting, and each one has a matching fixture in
`tests/fixtures/sso_claims/` that must resolve to the expected grants. A shape
that is not in this table and not expressible as a JMESPath expression is not
supported, and adding it is a matter of a fixture plus, at most, a doc change —
not new code.

Supported by configuration, with **no provider-specific code**. Everything is
read from `/.well-known/openid-configuration`; the rows below are the
configurations an administrator picks, not branches in our code.

| Provider | Issuer | Where roles/groups land | Configure |
|---|---|---|---|
| Keycloak | `https://host/realms/<realm>` | `realm_access.roles`, or `resource_access.<client_id>.roles` for client roles — nested objects | `claim_name=realm_access.roles` or `resource_access.*.roles`; `api_audience` for a resource server |
| Auth0 | `https://<tenant>/` | URI-namespaced top-level claims, e.g. `https://<tenant>/roles`; `https://<tenant>/groups` | `api_audience` is **required**, sent as `audience=`; `claim_name="https://<tenant>/roles"` (quoted identifier) |
| Okta | `https://<org>/oauth2/<app>` | `groups` — an array of **objects** by default (`{"id","name"}`) | `claim_name=groups[*].name` (or `groups[*].id`); `api_audience` for scopes as `resource=` |
| Entra ID | `https://login.microsoftonline.com/<tenant>/v2.0` | `roles` (app roles) or `groups` — arrays of strings or GUIDs | `claim_name=roles`; flat, nothing special needed |

The table lists the *claim location* in provider terms because that is how the
provider's own documentation describes it; the **stored** value is always the
JMESPath expression. Nothing in the code branches on provider name — the whole
table is configuration.

Per-provider facts that are **not** code but must be handled:

- **Keycloak issuers contain a path**, and the two well-known forms disagree.
  RFC 8414 puts the well-known segment *before* the path
  (`https://host/.well-known/openid-configuration/realms/x`); Keycloak serves
  the simpler trailing form (`https://host/realms/x/.well-known/...`). The
  discovery helper tries the RFC form first for a path-bearing issuer, falls
  back to the trailing form, and then requires the document's `issuer` to equal
  the configured issuer exactly. An administrator can also pin `discovery_url`.
- **Keycloak `sub` is an opaque UUID**, not the email — which is precisely why
  identity is keyed on `sub` and never on email. `email` appears only if the
  `email` scope is requested (a default in our scope list).
- **Group overage.** Entra and Okta replace an oversized group list with
  `_claim_names` / `_claim_sources` pointing at a Graph lookup. We do not call
  Graph. If either companion claim is present the login is refused with reason
  `CLAIM_OVERAGE` and the connection is flagged in the admin UI, rather than
  silently granting a truncated set.
- **`azp`.** Auth0 sets `azp` whenever `aud` is an array, so the multi-valued
  audience rule in the verifier fires for ordinary Auth0 logins and must be
  implemented, not treated as an edge case.
- **Logout** is out of scope for every provider; `end_session_endpoint` is
  stored so the later work does not need a migration.

`app/services/sso/sso_grant_sync.py` applies the result:

```
sync(user, connection, desired):
    owned = grants where sso_connection_id = connection and grant_status = 'active'
    deactivate(owned - desired)   # by (role, scope_type, scope_id, mapping_id)
    create_or_reactivate(desired - owned)
    all in one transaction; rollback and refuse the login on any error
```

- `SSO_MAX_GRANTS_PER_LOGIN` (default 50) refuses the login if exceeded, so a
  wildcard claim cannot write thousands of rows.
- Every create, reactivation and deactivation is logged through the existing
  audit logger (`app/logging/va_logger.py`) with the connection and mapping as
  the actor, and the target role/scope in the detail. No claim values, tokens
  or email addresses in the log record.
- Re-activation reuses the same lookup-and-reactivate path the admin grant
  endpoint already uses (`app/routes/admin.py:2493-2500`) so the partial unique
  indexes are satisfied the same way in both paths.

## Login flow

```
GET  /vaauth/valogin                      lists the active connections for direct sign-in
POST /vaauth/sso/start/<connection_code>  CSRF-protected; builds the transaction
GET  /vaauth/sso/callback                 the single callback for every connection
```

A **single** callback path is used, not one per connection, so an administrator
registers one redirect URI with every provider. The connection is carried inside
the signed transaction, never in a query parameter that could be tampered with.

**Start** (`POST`, requires the session CSRF token, rate limited 20/hour per IP
and connection):

1. Load the connection; 404 if unknown or inactive.
2. Generate `state` (32 bytes, `secrets.token_urlsafe`) and `nonce`, and a PKCE
   `code_verifier` (RFC 7636, 43–128 chars) with `code_challenge =
   BASE64URL(SHA256(verifier))`, method `S256`.
3. Build the transaction `{connection_id, state, nonce, code_verifier,
   redirect_uri, return_to}` and sign it with
   `itsdangerous.URLSafeTimedSerializer(SECRET_KEY, salt='digitva-sso-txn')`,
   `max_age = SSO_TRANSACTION_MAX_AGE_SECONDS` (600). The same blob is stored in
   the session under `sso_txn` (a single outstanding login per browser) so a
   cookie copy is required as well as the signed value.
4. `redirect_uri` is built from `SSO_PUBLIC_BASE_URL` via `url_for`, never from
   the request `Host` header — `ProxyFix(x_host=1)` trusts one proxy hop, so the
   request host is not a trustworthy source for a registered redirect URI.
5. `return_to` is the same `next` value, accepted only when
   `urlparse(next).netloc == ''`, matching `app/routes/va_auth.py:62-66`.
6. 302 to the authorization endpoint with `response_type=code`,
   `client_id`, `redirect_uri`, `scope`, `state`, `nonce`, `code_challenge`,
   `code_challenge_method=S256`, plus `api_audience` when set: as `audience=`
   for an Auth0-style provider, as `resource=` (RFC 8707) for Keycloak, Okta and
   Entra. Nothing else is appended — there is no free-form parameter bag.

**Callback** (`GET`, rate limited 30/minute per IP):

1. Load and verify the transaction from the session; delete it immediately so a
   replayed callback fails. Missing or expired → re-render the login page with a
   plain error and no provider detail.
2. `state` compared with `hmac.compare_digest`.
3. Confirm the callback `redirect_uri` equals the pinned one in the transaction.
4. Load the connection; 404 if inactive.
5. Token exchange: POST to `token_endpoint` with `grant_type=authorization_code`,
   `code`, `redirect_uri`, `code_verifier`, plus client authentication per
   `token_endpoint_auth_method`. The client secret is decrypted just before this
   call and never stored in a session, a log or an exception message.
6. Verify the ID token when `identity_source='id_token'` (below). Fetch
   `userinfo` with the access token when `identity_source='userinfo'`, or when
   the mapping rules need a claim the ID token does not carry. In that case the
   `userinfo` `sub` must equal the ID token `sub`.
7. Resolve the user: match on `(sso_connection_id, issuer, subject)`. On a miss,
   apply `user_provisioning_mode` — `existing_only` refuses the login with a
   message that does not disclose whether the account exists; the other mode
   requires a verified email claim matching exactly one `va_users` row, or
   creates a user with `user_status='active'`, `email_verified=True`, a random
   unusable password hash, and `pw_reset_t_and_c=False` (no password journey is
   started, because there is no password).
8. Reject if `va_users.user_status != 'active'`, matching the existing
   behaviour in `app/decorators/role_required.py:134-145`.
9. **Missing-claim detector.** Before any grant is written, check every active
   mapping rule on this connection: does its JMESPath expression evaluate in the
   merged ID-token and userinfo claims? If any active rule's expression matches
   nothing, refuse the login with reason `CLAIMS_MISSING`, name only the failing
   expressions in the audit event, and write no grant rows. This turns the most
   common provider misconfiguration — a provider emitting no custom claims at
   all, typically a missing `api_audience` — from a silent zero-access login
   into a visible failure. It also fires when a rule points at a shape the
   provider does not use, such as `realm_access.roles` configured on an Auth0
   tenant where roles arrive under `"https://tenant/roles"`.
10. `sync` the grants.
11. `session.clear()` then `login_user(user, remember=False)` and
    `session.permanent = True` — the clear is the session-fixation defence, and
    it also drops the CSRF token and the transaction. Record
    `sso_connection_id`, `sso_authenticated_at` and `sso_auth_method='sso'`
    after login.
12. Redirect to the validated `return_to`, else `user.landing_url()`.

## ID token verification

`app/services/sso/oidc_verify.py`, using **PyJWT** over the already-declared
`cryptography` (decision 6). Verification is the one place where hand-rolling
is genuinely dangerous — PSS salt length, the ES256 fixed-width `r || s` to DER
conversion, and the leading-zero case in an RSA modulus are all easy to get
subtly wrong, and a mistake is an authentication bypass rather than a test
failure. PyJWT has none of that code, so we do not write it.

- `algorithms=` is **always** the connection's explicit `id_token_signing_algs`
  allowlist and nothing else. This single argument is what closes `alg: none`
  and the RS256/HS256 key-confusion attack, so it is never derived from the
  token's own header. Symmetric algorithms are rejected when a connection is
  saved, not at login.
- `options={"require_exp": True, "require_aud": True, "require_iat": True,
  "verify_signature": True, "verify_exp": True, "verify_aud": True,
  "verify_iss": True}` — explicitly stated rather than relying on defaults, so
  a future PyJWT default change cannot quietly relax a check.
- `audience=client_id`, `issuer=pinned discovery_issuer`, and
  `leeway=SSO_CLOCK_SKEW_SECONDS` (60). When `aud` is an array of more than one
  value, `azp` must equal the `client_id` as well (OIDC Core 3.1.3.7) — this is
  checked by us, not by PyJWT, and it is a routine case for Auth0 rather than an
  edge case.
- The signing key comes from the connection's JWKS. `PyJWKSet` parses the
  document and selects by `kid`; **the cache is ours**, in Redis through the
  existing `flask-caching` setup (`SSO_JWKS_CACHE_SECONDS`, default 3600),
  because PyJWKClient's own `lru_cache` is per-process and this deployment runs
  more than one worker. An unknown `kid` triggers at most one refetch, itself
  rate limited, so a forged token cannot be used to hammer the provider.
- `nonce` is compared with `hmac.compare_digest` against the transaction nonce;
  PyJWT does not know about it, so it is our check.
- Discovery is cached for `SSO_DISCOVERY_CACHE_SECONDS` (default 86400) and
  re-fetched by a Celery beat job daily, writing `discovery_checked_at` and, on
  issuer mismatch, `discovery_last_error` with the connection disabled.
- Any verification failure is a refusal, logged with the reason code only.

## HTTP client

`app/services/sso/sso_http.py` follows the existing request-path discipline from
`app/services/attachment_source_central.py`: `requests.Session`,
`HTTPAdapter(max_retries=0)`, `timeout=(SSO_CONNECT_TIMEOUT_SECONDS=5,
SSO_READ_TIMEOUT_SECONDS=10)`, `allow_redirects=False`, a
`SSO_MAX_RESPONSE_BYTES` (256 KiB) cap enforced against both `Content-Length`
and the bytes actually read, `stream=True` for the token and userinfo POSTs
where relevant, and no URLs with query strings, codes, tokens, secrets or claim
values in any log line. The session is created per request and closed in a
`finally` block, matching the "release external clients promptly" rule.

## Secret storage

`client_secret_enc` uses `app/utils/credential_crypto.py`. That module is
currently ODK-named and reads `ODK_CREDENTIAL_PEPPER`. The change is a shared
`encrypt_secret(value, *, purpose)` / `decrypt_secret(...)` pair with an explicit
purpose, a new `SSO_CREDENTIAL_PEPPER` environment variable, and the existing
ODK call sites updated to pass `purpose='odk'`. There is no shim: the ODK caller
is migrated in the same change. The encrypted value is write-only over the API —
the admin UI shows "configured" and a *Test connection* action, never the value.

## Configuration

Added to `config.py` and `.env.example`:
`SSO_ENABLED` (default false — the whole feature is inert until a deployment
opts in), `SSO_PUBLIC_BASE_URL` (required when any connection is enabled;
startup validation refuses to serve with connections configured and no base
URL), `SSO_CREDENTIAL_PEPPER`, `SSO_CLOCK_SKEW_SECONDS=60`,
`SSO_JWKS_CACHE_SECONDS=3600`, `SSO_DISCOVERY_CACHE_SECONDS=86400`,
`SSO_CONNECT_TIMEOUT_SECONDS=5`, `SSO_READ_TIMEOUT_SECONDS=10`,
`SSO_MAX_RESPONSE_BYTES=262144`, `SSO_TRANSACTION_MAX_AGE_SECONDS=600`,
`SSO_MAX_GRANTS_PER_LOGIN=50`.

## Admin UI

- New section **Sign-in (SSO)** in the project setup shell
  (`app/templates/admin/panels/project_setup.html:30-43`), which is the same
  shell issue `digitva-r1p` is building out. Panel template
  `app/templates/admin/panels/project_sso.html`; route
  `GET /admin/panels/project-setup/<project_id>/sso`.
- JSON API beside the project ODK connection endpoints
  (`app/routes/admin.py:4618-4760`), all `@role_required('admin', 'project_pi')`
  where the caller already holds that project's PI grant:
  `GET/POST /admin/api/projects/<project_id>/sso/connections`,
  `PUT/DELETE /admin/api/projects/<project_id>/sso/connections/<uuid>`,
  `POST .../connections/<uuid>/test`,
  `GET/POST .../mappings`, `PUT/DELETE .../mappings/<uuid>`,
  `GET/POST/PUT .../external-ids` for the site and org-unit id tables.
  `POST .../connections/<uuid>/claims` returns the **claims inspector** payload.
  It performs the full flow once against the provider and returns, per source
  (`id_token`, `userinfo`), the expressions that actually resolve: their
  expression text, value count and value type. **Counts and types only, never
  values, and never a token** — a claim value can be a name, an email or a
  group path, and this response is not the place to disclose it. The mapping
  editor's claim field is a picker over that list plus a free-text box, so an
  administrator works from what the provider really sends rather than from
  memory. The inspector is the first thing an administrator is told to do.
- Mapping editor rows: claim expression, source, matcher, values, expected
  audience, role, scope type, and either a fixed site/unit picker or a scope
  expression and match mode. The role picker omits `admin`, and the server
  refuses it too. Each rule row shows a live check against the last inspected
  claim set — "resolves, 0 values in the current token" versus "expression does
  not resolve", which is the difference between a user who is not in the group
  and a misconfiguration. Because the expressions come from a real token, the
  common failure — `realm_access.roles` configured on an Auth0 tenant where
  roles arrive under `"https://tenant/roles"`, or `groups` configured on an
  Okta tenant where they are objects — is visible while configuring, not at that
  user's first login.
- External id editor: one row per project site and per org unit of the project,
  with the existing site id / unit code shown beside the free-text field, and a
  bulk "seed from local code" action for the common case where the IdP uses the
  same identifiers.
- `app/templates/admin/panels/access_grants.html` gains a "via SSO" badge and a
  source filter for SSO-owned grants, and the revoke control is disabled for
  them (they are revoked by removing the group at the provider, not by hand).
- The login page lists the active connections as "Sign in with <name>" buttons
  driven by a small public endpoint returning only `connection_code`,
  `connection_name` and `project_nickname` — no provider URLs, client ids or
  anything else.

## Migration

One additive revision with `down_revision = "c7a4e2d9f1b6"` (the current head per
the checked-in chain, to be confirmed with `flask db heads` before authoring):

1. `auth_sso_connections`
2. `auth_sso_claim_mappings`
3. `map_user_sso_identities`
4. `map_project_site_sso_ids`
5. `map_org_unit_sso_ids`
6. `va_user_access_grants.sso_connection_id` + `.sso_mapping_id` + check + index

No data backfill: the new tables are empty and the new grant columns are NULL on
every existing row, so every current admin-created grant stays admin-owned and no
existing access changes. A complete `downgrade` drops the columns, the check, the
index and the tables in reverse order. `c7a4e2d9f1b6` and
`d9e0f1a2b3c4` are the style references. `flask db heads` is run before and
after and must report exactly one head.

## Phases

0. **Policy baseline.** `docs/policy/project-sso-oauth2.md` written and reviewed
   before any code, per the repository rule that behaviour and policy changes get
   a baseline first.
1. **Schema.** Migration and the six models, following the naming and audit
   conventions of `mas_odk_connections` and `va_user_access_grants`.
2. **Protocol core.** `sso_http.py` and `oidc_verify.py` on PyJWT, plus
   `claim_reader.py` on JMESPath, with unit tests using a locally generated RSA
   key pair and hand-built JWKS documents. Depends on the `uv add jmespath
   pyjwt` step.
3. **Endpoints.** `sso/start` and `sso/callback`, the signed transaction, and a
   test-only fake IdP Flask app that serves discovery, JWKS, token and userinfo.
4. **Authorization mapping.** `sso_claim_resolver.py` and `sso_grant_sync.py`
   with the admin check on `admin` and the missing-claim detector.
5. **External ids.** `map_*_sso_ids` CRUD and the resolution lookup.
6. **UI.** Project setup section, mapping editor, external id editor, grants
   badge, login page buttons.
7. **Docs and handoff.** `docs/current-state/authentication.md` (new),
   `docs/current-state/data-model.md` and
   `docs/current-state/workflow-and-permissions.md` updates, `.env.example`,
   `handoff.md`, and close the bead.
8. **Provider shape corpus.** `tests/fixtures/sso_claims/*.json` — one
   realistic ID-token payload and matching userinfo body per supported shape,
   each traceable to that provider's published claim layout:
   `keycloak_realm_roles`, `keycloak_client_roles`, `keycloak_groups_path`,
   `auth0_namespaced_roles`, `okta_group_objects`, `okta_group_strings`,
   `entra_app_roles`, `entra_group_overage`, plus `claims_oversized` and
   `claims_malformed`. Each fixture carries the mapping rows it must resolve
   against and the grant rows it must produce, so the assertion is "this
   provider's real shape yields exactly these grants", not "the parser returned
   a dict".

## Test plan

`tests/test_sso_*.py` on a dedicated `minerva_test_sso` database, one runner.
Assertions are about observable access, not about the plumbing:

- `test_sso_oidc_verify.py` — a valid RS256 token passes; expired `exp`, future
  `nbf`, wrong `iss`, `aud` without our client id, multi-valued `aud` without a
  correct `azp`, wrong `nonce`, `alg=none`, an HS256 token signed with the RSA
  public key, an unknown `kid`, a tampered payload, and a JWKS whose `n` has a
  leading zero byte all fail. An ES256 token verifies. These assert *our*
  configuration — the `algorithms=` allowlist, the `azp` rule, the `nonce`
  comparison and the JWKS cache — not PyJWT's internals, which are its own test
  suite's job; we test that we pass the right arguments.
- `test_sso_callback.py` — the full flow against the fake IdP: a good code logs
  in; a replayed callback fails; a mismatched `state` fails; an expired
  transaction fails; connection A's signed transaction presented to connection B
  fails; a token minted for provider X is refused on provider Y.
- `test_sso_grant_sync.py` — a matching claim produces an **active grant that
  actually opens the protected route** for the right role; dropping the group
  deactivates it and the route is closed again; an admin-created grant survives a
  login that changes the claims; a mapping with `role='admin'` cannot be saved;
  a claim naming two sites grants both; an external id matching nothing is
  skipped, and with `unmapped_scope_policy='deny_login'` the login is refused;
  exceeding `SSO_MAX_GRANTS_PER_LOGIN` refuses the login and writes no rows.
- `test_sso_external_ids.py` — duplicate external ids for one connection are
  rejected at the database level; the same external id for two connections is
  allowed and resolves independently.
- `test_sso_provider_shapes.py` — drives every fixture in the corpus end to end
  through claim reading, the missing-claim detector, the resolver and grant
  sync, and asserts the expected grant set. Specifically: a Keycloak token whose
  roles sit under `resource_access.<client_id>.roles` matched by the projection
  `resource_access.*.roles`, with no client id configured anywhere; an Auth0
  claim named `https://tenant.example/roles` selected by the quoted identifier
  `"https://tenant.example/roles"` and *not* mangled by the dots; an Okta
  `groups` array of objects selected by `groups[*].name`; the same tenant
  configured with string groups through a bare `groups`; an Entra token with
  `_claim_names` present, which must be refused with `CLAIM_OVERAGE` and write no
  grants; a claims object whose size exceeds the response cap, which must be
  refused before any parsing; and a `claim_name` that is not valid JMESPath,
  which must be rejected by the save API.
- `test_sso_identity.py` — `existing_only` refuses an unknown user; the email
  mode links an existing user and creates one when absent; an unverified email
  claim does not link; a deactivated user cannot log in by SSO.

## Verification gates

- `flask db heads` before and after the migration: exactly one head, and it is
  the new revision.
- `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_sso minerva_app_service uv run --no-sync python -m pytest tests/test_sso_oidc_verify.py tests/test_sso_callback.py tests/test_sso_grant_sync.py tests/test_sso_external_ids.py tests/test_sso_identity.py -q -p no:cacheprovider`
- The authentication and grant route subset, then the full suite on a dedicated
  database, reported with exact counts.
- `ruff check` clean.
- A real browser smoke run against the fake IdP: sign in, land on the dashboard,
  see the mapped grant, drop the group at the fake IdP, sign in again, and watch
  the route close. This is the proof that the reconciliation is observable and
  not just row-level.

## Rejected alternatives

- **Hand-rolled claim parsing and JWS verification.** This was the original
  plan, on the reading that no new dependency was permitted. It is superseded:
  decision 6 permits `jmespath` and `pyjwt`, and both remove a class of bug
  rather than a class of typing. A claim grammar, escaping rules, a
  client-id substitution and a bounded flattening walk were all hand-rolled
  work on untrusted input; PSS salt length, the ES256 `r || s` to DER
  conversion and the leading-zero RSA modulus were all hand-rolled crypto
  where a mistake is an authentication bypass. Kept as a rejected alternative
  because the constraint that produced it is real and was only lifted for this
  feature, so the reasoning is worth preserving.
- **RFC 6901 JSON Pointer as the claim path syntax.** A real standard, and a
  plausible choice — but a location syntax only, so every interesting provider
  shape still needed an invented wildcard, a client-id substitution and a
  literal-name escape hatch. That is a private grammar bolted onto a standard,
  which is worse than either the standard alone or a mature expression language.
- **JSONPath.** Its recursive descent (`$..`) is a denial-of-service and
  information-disclosure footgun applied to a token, which is untrusted input.
- **JMESPath for the authorization decision, not just claim selection.** Tempting,
  because it can filter (`groups[?@ == 'coder']`) and would collapse the
  mapping table into one expression column. Rejected: an administrator asking
  "who can be a coder on site ICMR01NC0201" must be able to read rows. The role
  is a column with a check constraint that makes `admin` impossible, not text
  buried in a string.
- **Authlib.** The reflexive choice, and a full framework: client *and* server,
  with JWE, JWKS endpoint and introspection endpoint implementations. Its recent
  advisories (JWE RSA1_5 padding oracle, unbounded `zip=DEF` decompression) sit
  entirely in that server-side surface, which DigitVA would never use as a
  client, so they are not disqualifying on their own — the objection is size
  and shape. It would pull a large body of unused code into the authentication
  path, and its `claims_options` check set is configurable and therefore easy to
  leave permissive, which is the exact failure mode this design is trying to
  avoid. Discovery, the flow, the Redis JWKS cache and the missing-claim
  detector would still be ours.
- **A separate SSO service**, following the `public_doris_app.py` isolation
  precedent. That isolation exists because the DORIS app is DB-free and public.
  SSO needs the session store, the user table and the grants, so a second app
  would need a shared session and database anyway while adding a cross-service
  hop and a second nginx location.
- **SAML 2.0.** A different protocol from the one requested, and XML signature
  verification against hostile XML is not something to hand-build.
- **A JSON settings blob on `va_project_master`.** The model comment at
  `app/models/va_project_master.py:154-161` is explicit that project
  configuration is typed columns, and a repeating list of rules is a table.
- **A `sso_id` column on `va_site_master` or `mas_org_unit`.** Wrong level: the
  catalog is shared across projects and the id is only meaningful against one
  provider. Per-connection mapping tables carry the same user-facing idea with
  correct uniqueness.
- **Resolving access live from claims on every request, with no grant rows.**
  Stronger offboarding, but it forks every authorization path, breaks the grant
  listing, the audit trail and every export, and buys little: the IdP session
  and the DigitVA session already both expire, and reconciliation at login gives
  the same offboarding within one session lifetime.
- **Storing access/refresh tokens.** No provider API calls are in scope, and
  tokens are bearer credentials; the repository rule on secrets and PII says do
  not persist them. Claims live in the signed transaction cookie and in memory
  for the length of one request.
- **Forcing SSO on a project.** Deferred deliberately (decision 5); it needs a
  project lookup inside `va_login` and a decision about break-glass local
  accounts, which deserves its own discussion.

## Deferred

Named here so they are not mistaken for oversights. Each is a deliberate
follow-up, not a gap in the plan.

- **Linking an existing DigitVA account to an IdP from the profile page.** A
  user already signed in with a password chooses "link SSO". Useful as a support
  tool when a person's provider email differs from their DigitVA email. It is a
  second flow — authenticated start, no `login_user` at the end, an explicit
  unlink — and it is a support workflow rather than a login path.
- **Provider-initiated logout** (back-channel) and **front-channel** logout.
  `end_session_endpoint` is already stored, so neither needs a migration.
- **Mandatory SSO for a project**, with break-glass local accounts.
- **Cross-IdP identity linking** — the same person recognised by two different
  providers on one project.
- **`prompt`/`max_age` policy per connection**, and step-up authentication for
  sensitive actions.

## Dependency delivery

`uv add jmespath pyjwt` inside `minerva_app_service`, then restart
`minerva_app_service`, `minerva_celery_worker` and `minerva_celery_beat`, and
rebuild those three images before the dependency change is committed, per the
`AGENTS.md` toolchain rule. `pyproject.toml` and `uv.lock` are committed
together. Neither package has a transitive dependency and neither changes the
crypto backend, since `cryptography` is already declared — so the lockfile
delta should be exactly two entries, and that is verified rather than assumed.

## Risks

- **A wildcard claim produces a large grant set.** Bounded by
  `SSO_MAX_GRANTS_PER_LOGIN`, which refuses rather than truncates, so a
  misconfiguration is loud instead of partial.
- **Provider key rotation.** A key added while a token is cached must not
  invalidate live sessions: an unknown `kid` triggers one refetch and one retry.
  Key *removal* is not handled until the next JWKS cache expiry, which is the
  accepted trade for a 1-hour cache.
- **`pkce_required` is fixed to true.** A provider that refuses PKCE blocks
  login; the flag exists so the failure is diagnosable, but turning it off is not
  supported because the code is public-client-only in that case and DigitVA is
  confidential.
- **Reconciliation and the 30-minute session.** A group removed at the provider
  keeps access until the session expires, because DigitVA has no way to learn
  about it before the next login. Back-channel logout would fix this and is
  deliberately out of scope.
- **Email as a linking key.** `link_or_create_by_email` trusts the provider's
  `email_verified` claim. For a provider that does not issue that claim, the mode
  is refused at configuration time rather than degrading to an unverified link.
