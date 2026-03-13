---
title: UI Notification Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-13
---

# UI Notification Policy

## Purpose

This document defines the baseline policy for transient user notifications across the
DigitVA web application.

## Core Rule

Transient success, warning, and error messages should use the shared bottom-right
floating toast pattern instead of fixed inline message blocks embedded in page flow.

## Shared Helper

The shared notification helper is:

- `window.showAppToast(message, type, options)`

Current availability:

- loaded from [`app/static/js/base.js`](../../app/static/js/base.js)
- available on pages that extend
  [`app/templates/va_frontpages/va_base.html`](../../app/templates/va_frontpages/va_base.html)
- this includes:
  - coder, reviewer, and site-PI screens
  - admin screens, because [`app/templates/admin/admin_index.html`](../../app/templates/admin/admin_index.html)
    extends `va_base.html`

## Helper Contract

Arguments:

- `message`: required string shown to the user
- `type`: Bootstrap-style level such as `success`, `warning`, `danger`, `info`,
  `primary`, `secondary`
- `options`: optional object

Current supported options:

- `timeoutMs`: auto-dismiss delay in milliseconds

## Rendering Rules

Current baseline:

- toasts appear in the bottom-right corner
- toasts auto-dismiss by default
- users may dismiss them manually
- transient workflow feedback should prefer toasts over inline alerts

Examples of toast-suitable messages:

- save succeeded
- validation blocked next step
- network error on async action
- workflow prerequisite missing

## Exceptions

Inline alerts are still acceptable when the message is part of the content itself,
not just transient feedback.

Examples:

- empty-state notices inside category panels
- explanatory instructional cards
- persistent warnings that must remain visible while the user is editing a form

## Change Control

Any future notification pattern change should document:

- whether `window.showAppToast` remains the shared contract
- whether admin and VA screens still share the same notification shell
- which message classes are transient toast messages versus persistent inline content
