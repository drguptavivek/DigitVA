---
title: Expo Web Client Boundary
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-19
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

## Role home and login landing

Owner decision, 2026-10-11, 2026-10-12 and 2026-10-19 (design: `.tasks/2026-10-11-home-jump-page.md`, bead `digitva-dsj2`).
After login (and after accepting terms on `/profile/force-password-change`),
a user holding one of the field, coding or data manager roles — or a new user
with no role grants yet — lands on the Expo role home dashboard at `/app/`:

- `admin` or `project_pi`: unchanged (today's landing).
- Any of `interviewer`, `death_reporter`, `interview_supervisor`, `coder`,
  `coding_tester`, `reviewer`, `data_manager`, in the user's effective roles,
  or a user with no effective roles yet: `/app/`.
- Anything else (collaborators, viewers, `site_pi` at a project site alone):
  today's landing, unchanged. If the Expo export is missing (no `index.html`),
  every user keeps today's landing.
- `/app/` renders the user's Home / Dashboard directly on login:
  - When the user holds roles or project grants, it shows overall personal
    activity totals (forms filled, drafts in progress, deaths reported, forms
    coded, forms reviewed from `GET /api/v1/me/activity`), role-appropriate
    quick action buttons, and a card per project listing the user's assigned
    roles and scopes in that project, per-project personal activity counts, and
    per-project action buttons.
  - When a user holds no roles in any project yet, `/app/` shows a Welcome
    home state explaining that no project roles have been assigned yet, with
    links to Settings / Profile, Help, and Demo Coding when available.

Effective roles come from the authz helper, so a `site_pi` held at an org
unit (the In-charge) counts as `data_manager` and `interview_supervisor`.
`VaUsers.landing_url()` implements the rule, and `/profile/force-password-change`
redirects to `current_user.landing_url()`.

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
