---
title: Standalone Consent Notice Settings
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-28
---

# Standalone Consent Notice Settings

Only the Collect Plus standalone account may use locally edited consent
notices. English and Hindi start from the generated standalone notice in the
app bundle; the generated asset and its purpose codes are not edited by Settings.

Notice edits are stored as app-local settings and never sent to a server or
applied to enrolled or Demo projects. Saving requires nonblank English and
Hindi text of no more than 20,000 characters each and gives explicit success
or error feedback.
Bundled placeholders continue to be filled from the standalone profile at
display time; the editor changes the template text, not the purpose list.

Each new standalone consent decision uses the currently saved notice for its
language. The phone records the exact rendered text, language, content hash,
and hash-derived notice identifier with that decision. Editing a notice affects
future decisions only; an existing consent record and the text/hash/version it
names remain immutable. Server push validation continues to check the text hash,
the bundled notice identity, language, and bundled purposes.
