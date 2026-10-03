# DigitVA Expo client design

Owner-authorized 2026-10-03; epic `digitva-p6fs`. Astra advised the UI decisions below. This is a design record; durable implementation status lives in Beads.

## Architecture

Extend `mobile/digitva-collect` rather than create another app. Expo Router and TypeScript serve Android and the browser; retain Flask services and the existing WHO VA native/web package. Native collection keeps device enrollment, opaque bearer sessions and encrypted drafts. Browser uses same-origin Flask cookies, CSRF and server-side drafts. No personal data, questionnaire answers, session credentials or draft identifiers in browser storage or a service-worker cache. Only appearance and UI language preferences may persist in the browser.

## First workflow

Login, worklist, death registration, start/resume questionnaire, section saves and submission confirmation. Respect configured direct/death-register/both modes and allowed project/site/unit pairs. The questionnaire uses configured optional modules and approved available form languages. Authoritative scope and state checks remain server-side.

## Login

Compact single-column surface, readable maximum width around 440 px, persistent labels and clear loading/error states. Language and appearance controls are accessible before sign-in. Browser initially hands off to the established CAPTCHA -> password/passkey -> second-factor flow and returns to `/app/`. Native retains enrollment -> sign-in -> unlock. No parallel authentication implementation or bypass of required factors.

## Navigation

A prominent New death action on the collection worklist. Phone layouts use compact navigation; wide layouts show a side panel. Show collection/coding/review links from server capabilities, never from guessed role strings. Coding/review initially link to existing authenticated browser workspaces until their complete Expo case/assessment contracts are implemented. This is not native coding/review support: current device authentication only admits interviewers.

## Theme and fonts

One semantic DigitVA theme extending the existing blue accent. Background/surface/text/muted/border/accent/error/warning/success/focus tokens; 4-point spacing, 16-17 body text and approximately 48 px controls. System/light/dark selection; platform-native conventions retained. Start with platform system fonts and script-aware web fallbacks for English and Hindi, rather than forcing a Latin-only font. Test Devanagari shaping, wrapping, enlarged text and keyboard focus. Do not introduce a second styling framework.

## Internationalization

Owner chose English and Hindi UI first, further UI languages later. Reuse and extend existing dictionaries; all app chrome, errors, accessibility labels and status strings use translation keys. Owner superseded the independent-language choice on 2026-10-03: app UI follows the selected/restored questionnaire locale. Save and load translations successfully before applying a switch to both. Signed-in settings have no competing UI language selector; the top-right interview language icon controls the choice. Unsupported UI locales fall back to English. Before an interview, saved preference overrides supported device/browser language, then English; normalize locale tags and fall back exact -> base -> English per key. Changing UI language must not remount or clear an interview. Hindi requires a fluent-speaker review before field rollout. Add later scripts and RTL deliberately rather than presenting unimplemented language choices.

## Form safety

Reuse the package and server envelope protocol. Load a confirmed baseline before saving; write changed sections only. Serialize pending writes, expose failures, and await successful saves before submit, deliberate navigation or questionnaire language change. Never claim Saved after a rejected request. Preserve unsaved answers in memory while explaining connection failure. Browser offline capture remains unavailable by policy.

## Delivery boundary

No schema changes required for the initial browser collection slice. Preserve concurrent authorization stage 5 changes and do not stage, commit or push other sessions' files. Native shared-scope key/PIN changes already tracked in `digitva-kfi` are a distinct approved security implementation and remain a production readiness dependency. Native coding/review authentication needs a policy-backed design; do not widen interviewer device tokens.

## Verification

Focused locale/theme and draft-store tests, frontend TypeScript/Jest, Expo browser export and native bundle export. Flask client bootstrap/hosting tests on a dedicated test database; a single runner. Browser checks at phone and desktop widths in both languages/themes with role visibility, section saves, resume and submit. Security review and independent code-quality gate on only this work's diff. A browser build does not verify device biometrics, Android signing or field readiness.
