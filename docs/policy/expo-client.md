---
title: Expo Web Client Boundary
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-03
---

# Expo Web Client Boundary

The first Expo client supports the DigitVA collection workflow in a browser
and on native devices. The browser client is an online client. It uses the
ordinary Flask login session and server-side web-intake drafts; it does not
persist questionnaire answers, identifiers or attachments in browser storage.
This follows the browser path in the [Field Data Collection
Policy](field-data-collection.md).

The native collection app remains the offline path. It uses the existing
encrypted device store and bearer device-session API. A device token is
accepted only under `/api/v1/device/`; it cannot authenticate the browser
client or any other API.

## Browser bootstrap

After the existing email, CAPTCHA, password or passkey and factor flow has
completed, the browser calls `GET /api/v1/client/bootstrap`. The endpoint
uses the same-origin session cookie and returns:

```json
{
  "user": {"id": "<uuid>", "name": "<display name>"},
  "csrf": {"header": "X-CSRFToken", "token": "<signed token>"},
  "capabilities": {
    "intake": true,
    "coding": false,
    "reviewing": false
  },
  "links": {
    "login": "/vaauth/valogin?next=/app/",
    "logout": "/vaauth/valogout",
    "intakeBootstrap": "/intake/api/bootstrap",
    "intakeCases": "/intake/api/cases",
    "intakeDrafts": "/intake/api/drafts",
    "coding": "/coding/",
    "reviewing": "/reviewing/"
  }
}
```

The capability values are navigation hints. They are derived from the
authoritative authorization role resolution, including the policy's demo
project coding and reviewing roles. Every workflow API performs its own
project, site and unit scope check. A client must never treat a capability or
link as permission to read or change a record.

An anonymous request receives JSON `401` with
`{"code":"authentication_required","login_url":"/vaauth/valogin?next=/app/"}`.
The response, including errors, is `Cache-Control: no-store`. No sign-in
bypass, device-token fallback, or new authentication factor is introduced.

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
