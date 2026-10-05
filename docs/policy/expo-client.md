---
title: Expo Web Client Boundary
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-05
---

# Expo Web Client Boundary

The first Expo client supports the DigitVA collection workflow in a browser
and on native devices. The browser client is an online client. It uses the
ordinary Flask login session and server-side web-intake drafts; it does not
persist questionnaire answers, identifiers or attachments in browser storage.
This follows the browser path in the [Field Data Collection
Policy](field-data-collection.md).

The native collection app remains the offline path. It uses the existing
encrypted device store and bearer device sessions (`/api/v1/auth`). A device token is
accepted on every `/api/v1/` route, same route and body as the browser
session cookie; it cannot authenticate anything outside `/api/v1/` (the
browser pages, `/admin/api`, `/intake`). A request carrying a bearer is
authenticated by it alone: a cookie on the same request is ignored, a bad
token is a 401 (never a fallback), it needs no `X-CSRFToken` and it never
sets a cookie. Terms, maintenance and forced-password-change gates apply to
both credentials.

A device session opens, and refreshes, for a worker with an active grant that
opens its gate for interviewer, coder, coding_tester or reviewer in at least
one project (owner, 2026-10-05; [Field Data
Collection](field-data-collection.md), "Who may sign in on a device"). The
session grants nothing by itself: each route keeps its own role and scope
check.

## Browser access

After the existing email, CAPTCHA, password or passkey and factor flow has
completed, the browser calls `GET /api/v1/me/access` (there is no separate
bootstrap route). It uses the same-origin session cookie and returns the
user's whole access summary (`docs/policy/api-v1.md`; shape in
`docs/current-state/api-v1.md`) and, for a cookie request only, the CSRF
token in the `X-CSRFToken` response header, which the client sends back on
every state change. The body is identical for the device bearer credential.

The summary is a set of navigation hints, derived from the authoritative
authorization role resolution. Every workflow API performs its own project,
site and unit scope check. A client must never treat a grant, capability or
link as permission to read or change a record.

An anonymous request receives JSON `401`
`{"error": "Authentication required.", "code": "unauthorized"}`: the cue to
send the browser to `/vaauth/valogin?next=/app/` (sign out:
`/vaauth/valogout`). The response, including errors, is `Cache-Control:
no-store`. No sign-in bypass, device-token fallback, or new authentication
factor is introduced.

## Hosting and languages

The built Expo export is mounted at `/app/`. The default directory is
`mobile/digitva-collect/dist`; deployments may set `EXPO_CLIENT_DIST` to a
dedicated export directory. Only files inside that directory are served.
Known Expo route paths fall back to `index.html` for client-side navigation;
missing assets and unknown paths return `404`. The source tree is never a
fallback document root.

The initial UI locales are English and Hindi. The app UI follows the selected
questionnaire language when starting, resuming or switching an interview.
Questionnaire choices remain controlled by project configuration. A language
without an available UI dictionary uses English app text until that dictionary
is added. Before opening an interview, the login page may select its UI language.
Every browser screen has a compact language icon at the top right. Outside
an interview it switches the English/Hindi app UI. During an interview the
project-configured questionnaire selector occupies that slot and changes
questionnaire and app UI language together.

The shared theme uses platform system fonts with Latin and Devanagari support,
semantic light and dark colors, and touch controls at least 48 pixels high.
UI language and theme preferences may persist locally. Questionnaire language
and translation version are saved with the server draft and restored on resume.

The main menu sits on the left on wider browser screens. Phones retain a slim
left rail with an expanded drawer overlay, preserving vertical form space.
Menu destinations remain role-dependent navigation hints;
leaving an interview through the menu waits for draft saving to succeed.
Each visible section dot navigates directly to that section. A separate
section-list button opens the fly-out, which follows the active form theme.
New draft answers use the authorized server prefill, including the logged-in
interviewer name; existing saved answers take precedence over prefill defaults.

Coding and reviewing destinations stay hidden in the Expo navigation and
workspace until those workflows are implemented inside Expo. Their server
authorization and capability contracts remain unchanged.
