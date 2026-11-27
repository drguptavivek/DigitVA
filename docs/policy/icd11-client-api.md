---
title: ICD-11 Client API Tokens
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-27
---

# ICD-11 Client API Tokens

Bead digitva-ddpf. API reference and rollout: `docs/current-state/icd11-client-api.md`.

## 1. Purpose

DigitVA runs a local WHO ICD-11 MMS container for its coders. Approved
applications, DeathNote first, may use the same terminology through a
documented, versioned API (`/api/icd11-client/v1/`). The API serves terms
only: search, word suggestions, code lookup and details, postcoordination
axes and values, and expression validation. Every answer is pinned to one
ICD-11 release, and every answer names it.

## 2. Who may hold a token

- A token belongs to one approved application, never to a person. Only a
  DigitVA administrator issues one, from the admin portal ("ICD-11 API
  clients").
- Tokens are for server-to-server use only. The application keeps its token
  in a server-side secret store, such as a serverless function secret or a
  backend environment variable. A token must never be in browser code,
  browser storage, a mobile app bundle, a build artifact or a repository. A
  static site such as DeathNote's GitHub Pages build calls the
  application's own small backend, and only that backend calls DigitVA.

## 3. Scopes

A token carries one or more scopes. An operation outside its scopes is
refused (403 `INSUFFICIENT_SCOPE`).

| Scope | Allows |
| --- | --- |
| `icd11:search` | term search and word suggestions |
| `icd11:lookup` | code lookup and code details |
| `icd11:postcoordination` | postcoordination axes and axis values |
| `icd11:validate` | expression validation |

Issue the fewest scopes the application needs.

## 4. Lifetime

A token lives 1 to 365 days, 90 by default, set at issuance. It cannot be
extended. An expired token is refused (401 `TOKEN_EXPIRED`), and a
replacement is issued in its place.

## 5. Issuance, one-time display and storage

- The token is shown once, in the issuance response and the panel's
  one-time dialog. It cannot be retrieved later. A lost token is revoked and
  replaced.
- DigitVA stores only a verifier: the SHA-256 digest of the whole token. A
  slow hash adds nothing against a 256-bit random secret. The token itself is
  never stored, logged or returned after issuance.
- Admins identify a token by its `key_id`, a short public identifier that is
  part of the token.

## 6. Rotation

1. Issue the replacement ("Issue replacement" prefills the same name and
   scopes; it does not revoke the old token).
2. Deploy the replacement into the application's secret store and confirm
   that the application works with it.
3. Revoke the old token.

A token sent over plain HTTP, pasted into a ticket or chat, or committed
anywhere is treated as exposed: rotate it at once.

## 7. Revocation

Revocation takes effect on the next request on every worker. Each request
reads the token's row from the database. Nothing is cached, so there is
nothing to wait for or clear. Revoking twice changes nothing.

## 8. Audit

Issuance and revocation each write an `auth_security_events` row
(`icd11_client_issued`, `icd11_client_revoked`) with the acting
administrator, the time and the client's id, key id, name, scopes and expiry.
The client row keeps `created_by`, `created_at`, `revoked_by`, `revoked_at`
and a `last_used_at` that is updated at most once a minute.

## 9. What is never logged

The app's request log records the method, path, raw query string and payload
keys only. The ingress logs only the path. Therefore:

- every operation is a POST with a JSON body, so search text and codes never
  appear in a URL;
- no log line carries a token, an `Authorization` header or a verifier;
- the audit detail carries no token material.

## 10. Rate limits and capacity

- Per token: `ICD11_CLIENT_RATE_LIMIT`, default 120 a minute, shared across
  all the API's operations.
- Per client IP: `ICD11_CLIENT_IP_RATE_LIMIT`, default 300 a minute, counted
  before authentication, so bad tokens are throttled too.
- Client operations share 4 concurrent WHO guidance slots of their own. They
  never take the slots the coders' guidance uses. When all 4 are busy, the
  answer is 429 `GUIDANCE_BUSY`, distinct from `RATE_LIMITED`.

## 11. What the API will never do

- Forward arbitrary requests to WHO. Each operation calls a fixed WHO
  resource with validated, bounded input.
- Process certificates: no DORIS or CoDEdit, and no underlying-cause
  selection.
- Read or return clinical records, cases, submissions, users or any other
  DigitVA data.

## 12. Isolation

- A client token works only under `/api/icd11-client/`. Sent to
  `/api/v1/`, it is treated as a device token and refused (401).
- A device access token, a browser session or a public-demo account grants
  nothing on the client API. The namespace never reads or writes the session
  cookie, and the signed-in user is always anonymous there, so an
  administrator's browser cookie does not authenticate a request.
- The namespace is exempt from CSRF, which is safe because no ambient
  credential is ever read.

## 13. Transport

Production forces HTTPS: a plain-HTTP request is redirected, and the token in
it has already crossed the network in clear. Treat it as exposed and rotate
it (section 6).
