---
title: Expo Web Client Boundary
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-23
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

Owner decision, 2026-10-22 (supersedes 2026-10-11, -12 and -19; design:
`.tasks/2026-10-11-home-jump-page.md`, bead `digitva-dsj2`). The Expo home at
`/app/` is the default home for every signed-in user — admin, `project_pi`,
collaborators, viewers, `site_pi`, field, coding and data manager roles, and
users with no role grants yet — whenever the Expo export is present
(`export_ready()`, an `index.html` in the export directory).

- After login (every sign-in path), after accepting terms on
  `/profile/force-password-change`, and on `/` for a signed-in user, the
  browser goes to `/app/`. The Flask "Return to Dashboard" and logo links
  follow the same rule. `/admin/`, `/data-management/`, `/area/`, `/sitepi/`
  and the other Flask pages stay reachable by URL and from the Expo home.
- The stored `landing_page` column is kept but no longer chooses the
  post-login page while the export is present. Only when the export is
  missing (no `index.html`) does `VaUsers.landing_url()` fall back to the old
  rule: `landing_page` where the user still holds the matching role, then the
  first role dashboard, then `/`.
- `/app/` renders the user's Home / Dashboard directly on login:
  - When the user holds roles or project grants, it shows overall personal
    activity totals (forms filled, drafts in progress, deaths reported, forms
    coded, forms reviewed from `GET /api/v1/me/activity`), role-appropriate
    quick action buttons, and a card per project listing the user's assigned
    roles and scopes in that project, per-project personal activity counts, and
    per-project action buttons.
  - Quick actions reach the Flask pages a role has no Expo screen for: the
    admin console (`/admin/`) for an admin, Data management (`/data-management/`)
    for `project_pi`, collaborator and viewer (`collaborator_pii`) users, and
    the VA dashboard (`/sitepi/`) for `site_pi`.
  - When a user holds no roles in any project yet, `/app/` shows a Welcome
    home state explaining that no project roles have been assigned yet, with
    links to Settings / Profile, Help, and Demo Coding when available.

Effective roles come from the authz helper, so a `site_pi` held at an org
unit (the In-charge) counts as `data_manager` and `interview_supervisor`.
`VaUsers.landing_url()` implements the rule.

## Error messages and the support reference

Field users report problems by screenshot, not by log. So an error the app
cannot name precisely must still identify itself on screen (owner,
2026-10-23, `digitva-l3r8`):

- A generic error (native "Something went wrong", web "server could not
  complete", "Check the highlighted fields", "Server unavailable") carries a
  second line, `Ref: <what> · <HH:MM>Z · v<app version>`, built by
  `errorReference` in `mobile/digitva-collect/src/ui.tsx`. `<what>` is the
  HTTP status, the error code, the method and the route with every id
  segment masked as `:id`, or for a failure on the device, the error class
  and at most 60 characters of its message with quoted text and digit runs
  of 4+ masked.
- The Ref line never carries tokens, query strings, full URLs, names,
  answers or server-provided free text.
- Messages that already say what to do (offline, rate limited, sign in
  again, CSRF refreshed, forbidden) carry no Ref line.
- An interview submit refused with 422 shows the server's own message
  (fixed rule text such as consent, Id10013 or the deceased's identity, no
  answers) with the Ref line, because the page cannot highlight the question
  the rule names. `draft_stale` likewise shows the server's message. All other
  server text stays hidden.
- Support matches a Ref to the server's access log by route, status and UTC
  minute.

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
