---
title: ICD-11 Client API
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-11-27
---

# ICD-11 Client API

Approved applications, such as DeathNote, call DigitVA's local WHO ICD-11 MMS
container through this API. Policy: [icd11-client-api.md](../policy/icd11-client-api.md)
(bead digitva-ddpf).

Code: `app/routes/icd11_client_api.py` (routes),
`app/services/icd11_client_auth.py` (tokens), `app/services/icd11_client_api.py`
(terminology), `app/routes/admin_icd11_clients.py` and
`app/templates/admin/panels/icd11_api_clients.html` (admin portal), and
`app/models/auth_icd11_api_clients.py` (table `auth_icd11_api_clients`).

## Basics

- Base URL: `https://<digitva-host>/api/icd11-client/v1`.
- Every operation is `POST` with a JSON body `{"schema_version": 1, ...}` and
  `Content-Type: application/json`. Bodies are at most 8 KiB, and unknown keys
  are refused. Query text and codes are never put in a URL, because URLs are
  logged.
- Authentication: `Authorization: Bearer <token>` (the scheme is case-insensitive).
- Release: every response carries `"release": "2026-01"`. This is
  `DEFAULT_ICD11_RELEASE` in `app/services/who_icd_api.py`, a code constant,
  not configuration.
- Every response, errors included, carries `Cache-Control: no-store`.
- Production forces HTTPS. A plain-HTTP request is redirected, and a token sent
  over plain HTTP must be treated as exposed and rotated.

## Token format

`dvicd_<key_id>_<secret>`. `key_id` is 12 lowercase hex characters, the
public identifier shown in the admin panel. `secret` is 43 URL-safe base64
characters (256 random bits). Only the SHA-256 digest of the whole token is
stored. A header that does not have this exact shape is refused before any
database read.

All token values in this document are placeholders.

## Endpoints

| Path | Scope | Body (besides `schema_version`) |
| --- | --- | --- |
| `/client` | any valid token | none |
| `/search` | `icd11:search` | `query` (2-80 characters), `limit` (1-20, default 20), `subtree_uris` (optional, 1-40 WHO URIs) |
| `/words` | `icd11:search` | `query` (2-80 characters) |
| `/codes/lookup` | `icd11:lookup` | `code` (at most 128 characters, WHO code alphabet) |
| `/codes/details` | `icd11:lookup` | `code` |
| `/postcoordination/axes` | `icd11:postcoordination` | `code` (a stem code) |
| `/postcoordination/values` | `icd11:postcoordination` | `stem_code`, `axis_id`, `parent_uri` |
| `/expressions/validate` | `icd11:validate` | `code` (a stem or expression) |

`browser_url` is the WHO ICD-11 browser page
(`https://icd.who.int/browse/2026-01/mms/en#<id>`) for a plain MMS URI. It is
`null` for anything else.

### POST /client

Use it for smoke checks. Response:

```json
{"schema_version": 1, "release": "2026-01",
 "client": {"name": "DeathNote", "key_id": "0123456789ab",
            "scopes": ["icd11:search", "icd11:lookup"], "expires_at": "2027-02-25T10:00:00+00:00"}}
```

### POST /search

Response: `{schema_version, release, items, truncated}`. Each item has `code`,
`title`, `uri`, `release`, `matching_text`, `postcoordination`,
`postcoordination_availability` (0, 1, 2 or null), `related_maternal`,
`related_perinatal`, `has_coding_note`, `extension`, `leaf` (present only when
WHO says) and `browser_url`. `truncated` is true when WHO cut the result or
more matched than `limit`.

### POST /words

WHO's keyword suggestions for a query (`includeKeywordResult`): words that
appear in the titles and index terms WHO matched, for narrowing the search.
They are not completions of the query text. Response:
`{schema_version, release, words: ["sclerosis", ...], truncated}`, with at most
20 words in plain text.

### POST /codes/lookup

Response: `{schema_version, release, item}`. `item` has `code`, `title`
(an expression's title covers every part), `uri` (the expression URI, whose
parts are joined by ` & ` or ` / `), `release`, `postcoordination`, `leaf`
(of the first stem), `extension`, `browser_url` (of the first stem's page)
and, for a plain stem, the search flags above. An unknown code gives 404
`CODE_NOT_FOUND`.

### POST /codes/details

Response: `{schema_version, release, selected: {code, title, uri}, definition,
coding_note, fully_specified_name, inclusions, exclusions: [{code, title}],
truncated, browser_url}`. An expression is answered for its stem. An unknown
code gives 404 `CODE_NOT_FOUND`.

### POST /postcoordination/axes

Response: `{schema_version, release, stem: {code, title, uri, browser_url},
axes, other_postcoordination, truncated}`. Each axis has `id`, `label`,
`required`, `instruction`, `allow_multiple`, `allow_multiple_values`,
`options: [{code, title, uri, has_children, block_uri}]`, `subtree_uris` and
`truncated`. `other_postcoordination` is `{subtree_uris: [chapter X root]}`
for a category outside chapter X, else `null`. To search an axis, pass its
`subtree_uris` to `/search`.

### POST /postcoordination/values

The children of one option on one axis. `parent_uri` must be under one of the
axis roots. Response: `{schema_version, release, stem, axis_id, parent_uri,
items: [{code, title, uri, has_children, block_uri}], truncated}`. Its own
errors: `INVALID_AXIS` 422 and `INVALID_PARENT` 422 (and `INVALID_URI` 422).

### POST /expressions/validate

Answers 200 whenever the request itself is valid:

- `{valid: false, refusal: {code: "REPEATED_PART" | "CODE_NOT_FOUND", message}}`
- `{valid: true, item, certificate_refusal: null}`
- `{valid: true, item, certificate_refusal: {code: "NOT_CERTIFIABLE", message}}`:
  WHO accepts the expression, but a death certificate needs a final code. The
  expression is a category, or it starts with an extension code.

A `code` outside the WHO code alphabet gives 422 `INVALID_INPUT`.

## Errors

Envelope: `{"schema_version": 1, "error": {"code": "...", "message": "..."}}`.

| Code | Status | When |
| --- | --- | --- |
| `INVALID_TOKEN` | 401 | missing, malformed or unknown token |
| `TOKEN_EXPIRED` | 401 | past `expires_at` |
| `TOKEN_REVOKED` | 401 | revoked in the admin portal |
| `INSUFFICIENT_SCOPE` | 403 | the token lacks the operation's scope |
| `MALFORMED_JSON` | 400 | not a JSON object body |
| `INVALID_INPUT` | 422 | wrong `schema_version`, unknown or missing key, value out of bounds |
| `CODE_NOT_FOUND` | 404 | lookup or details of a code WHO does not know |
| `INVALID_AXIS`, `INVALID_PARENT`, `INVALID_URI` | 422 | postcoordination input not valid for the stem |
| `PAYLOAD_TOO_LARGE` | 413 | body over 8 KiB |
| `RATE_LIMITED` | 429 | a rate limit (with `Retry-After`, in seconds) |
| `GUIDANCE_BUSY` | 429 | all 4 client WHO slots are busy; retry shortly |
| `WHO_UNAVAILABLE` | 503 | the WHO container failed, timed out or answered badly |
| `GUIDANCE_LIMIT` | 503 | one operation needed too many WHO calls |
| `NOT_FOUND` | 404 | no such path |
| `METHOD_NOT_ALLOWED` | 405 | not POST |
| `INTERNAL_ERROR` | 500 | unexpected; details only in the server log |

Every 401 carries `WWW-Authenticate: Bearer error="invalid_token"`.

## Isolation

- The namespace sits outside `/api/v1/`. The device bearer hook never reads
  it, and a client token sent to `/api/v1/` is refused 401 as a bad device
  token.
- `BearerBlindSessionInterface` never reads or writes the session cookie
  under `/api/icd11-client/`. `authenticate_bearer` pins the user to
  anonymous there, so a browser cookie or device token grants nothing, and no
  response sets a cookie.
- The views are CSRF-exempt one by one, through the `client_scope`
  decorator that also authenticates them. This is safe because no ambient
  credential is read.
- The views are listed in `PUBLIC_ENDPOINTS` (`app/services/authz/consulted.py`):
  they are authenticated by the token, not by a user session.

## Rate limits and capacity

Both limits are shared across every operation and replace the app's default
limits for this namespace:

- per client IP (`ICD11_CLIENT_IP_RATE_LIMIT`, default `300 per minute`),
  counted before the token is checked;
- per token (`ICD11_CLIENT_RATE_LIMIT`, default `120 per minute`), keyed on the
  whole token's SHA-256 verifier, never the public `key_id`, so a forged
  secret behind a real `key_id` cannot spend that client's budget; a
  malformed token counts against its IP instead.

Production stores the counters in Redis (`RATELIMIT_STORAGE_URI`). Client
operations hold one of 4 WHO slots of their own while they run, separate from
the coders' 2 guidance slots.

## Admin portal: issue, rotate, revoke

Admin > **ICD-11 API clients** (admins only).

- **Issue**: enter the application name, tick the scopes it needs, set the
  expiry (1-365 days, default 90) and choose **Issue**. A dialog shows the
  token once, with **Copy**. Store the token in the application's server-side
  secret store before closing the dialog; it cannot be shown again.
- **Rotate**: choose **Issue replacement** on the row. This prefills the name
  and scopes; issue the token, deploy it, confirm the application works,
  then choose **Revoke** on the old row.
- **Revoke**: choose **Revoke** and confirm. The next request with that token
  is refused on every worker.

The table shows each token's key id, scopes, status (`active`, `expired`,
`revoked`), who created it and when, its expiry, when it was last used
(updated at most once a minute) and its revocation. Admin JSON API:
`GET /admin/api/icd11-api-clients` (newest first, at most 200 rows, with
`truncated`), `POST /admin/api/icd11-api-clients` with `{name, scopes,
expires_in_days}` (201 `{client, token}`; 400 `{error, field}`), and `POST
/admin/api/icd11-api-clients/<id>/revoke` (200 `{client}`, idempotent; 404
for an unknown id). All of them need `X-CSRFToken`.

## Configuration

| Key | Default | Meaning |
| --- | --- | --- |
| `ICD11_CLIENT_RATE_LIMIT` | `120 per minute` | per-token limit |
| `ICD11_CLIENT_IP_RATE_LIMIT` | `300 per minute` | per-IP limit |
| `ICD11_API_BASE_URL` | `http://icd_api_service` | the WHO container (existing) |
| `ICD11_API_TIMEOUT_SECONDS` | `5` | per WHO call (existing) |

## Migration and rollout

Revision `a4d7e2c9b1f6` (`add_icd11_api_clients`), on top of `a40477e55b72`.
It is additive: it creates `auth_icd11_api_clients` and one index, with no
data backfill.

1. Take a verified database backup (`scripts/deploy-staging.sh` does this on
   staging).
2. Deploy the image.
3. Run `flask db upgrade` (the deploy script does this).
4. Issue a token in the admin portal and run the smoke checks below.

The downgrade drops only the new table. Every issued token stops working;
the audit rows in `auth_security_events` stay.

## Staging smoke checks

Use a token with every scope. The input is synthetic: no case data.

```bash
TOKEN='dvicd_000000000000_PLACEHOLDERplaceholderPLACEHOLDERplaceho'  # placeholder
BASE='https://<staging-host>/api/icd11-client/v1'
post() { curl -sS -X POST "$BASE$1" -H "Authorization: Bearer $TOKEN" \
              -H 'Content-Type: application/json' --data "$2"; echo; }

post /client '{"schema_version":1}'
post /search '{"schema_version":1,"query":"tuberculosis","limit":5}'
post /words '{"schema_version":1,"query":"tuber"}'
post /codes/lookup '{"schema_version":1,"code":"1B10.Z"}'
# NE84 (failure or rejection of transplanted organs or tissues) has a
# specificAnatomy axis; 519578830 is its "Nerve" option, which has children.
post /postcoordination/axes '{"schema_version":1,"code":"NE84"}'
post /postcoordination/values '{"schema_version":1,"stem_code":"NE84","axis_id":"specificAnatomy","parent_uri":"http://id.who.int/icd/release/11/2026-01/mms/519578830"}'
post /expressions/validate '{"schema_version":1,"code":"NE84&XA45E6"}'
```

Expect 200 with `"release":"2026-01"` on each call, and `"valid":true` on the
last one. Then check two refusals: the same `/client` call with the token
changed by one character answers 401 `INVALID_TOKEN`, and after revoking a
spare token, its call answers 401 `TOKEN_REVOKED`.

## DeathNote server-to-server

DeathNote's GitHub Pages build is static: it cannot hold a secret. It calls a
small backend that DeathNote owns, a serverless function. Only that function
calls DigitVA:

- the DigitVA token lives in the function's runtime secret storage (a
  Cloudflare Worker secret, or an environment variable on a server), never in
  React code, browser storage, the repository or a build artifact;
- the function forwards only the operations DeathNote uses, over HTTPS,
  with `Authorization: Bearer`;
- it answers CORS for the DeathNote origin only;
- it never echoes the token, and it does not log request bodies.

A minimal Cloudflare Worker (`wrangler secret put DIGITVA_ICD11_TOKEN`; the
values below are placeholders):

```js
// DeathNote's ICD-11 relay: the browser calls this; this calls DigitVA.
const DIGITVA = "https://digitva.example.org/api/icd11-client/v1";
const ALLOWED_ORIGIN = "https://deathnote.example.github.io";
const OPERATIONS = new Set([
  "search", "words", "codes/lookup", "codes/details",
  "postcoordination/axes", "postcoordination/values", "expressions/validate",
]);

function cors(origin) {
  return origin === ALLOWED_ORIGIN
    ? { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST",
        "Access-Control-Allow-Headers": "Content-Type", "Vary": "Origin" }
    : {};
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const headers = cors(origin);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    const operation = new URL(request.url).pathname.replace(/^\/icd11\//, "");
    if (origin !== ALLOWED_ORIGIN || request.method !== "POST" || !OPERATIONS.has(operation)) {
      return new Response("Not allowed", { status: 403, headers });
    }
    const body = await request.text();
    if (body.length > 8192) return new Response("Too large", { status: 413, headers });
    const upstream = await fetch(`${DIGITVA}/${operation}`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${env.DIGITVA_ICD11_TOKEN}`,
                 "Content-Type": "application/json" },
      body,
    });
    // Pass DigitVA's JSON (and error envelope) through; never the token.
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { ...headers, "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  },
};
```

The React app then calls `https://<worker-host>/icd11/search` with
`{"schema_version":1,"query":"..."}` and no credential. Add the Worker's own
rate limit if DeathNote is public, because every visitor shares the one
DigitVA token's 120 calls a minute. Rotate the token as the policy describes:
put the replacement secret in the Worker, deploy, then revoke the old token.
