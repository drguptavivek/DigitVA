---
title: Site Maintenance Mode Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-29
---

# Site Maintenance Mode Policy

## Summary

DigitVA supports a global admin-controlled site maintenance mode.

The maintenance mode is intended for short operational windows where admins
must keep access while non-admin users are drained from the site safely.

## Rules

1. Only admins may start or end site maintenance.
2. Starting maintenance opens a fixed 15-minute grace window.
3. During that grace window, non-admin authenticated users may continue
   working normally.
4. During maintenance, all authenticated users must see the active
   maintenance message in a fixed bottom-centered banner.
5. During that grace window, non-admin authenticated pages must also show a
   countdown in that banner.
6. The countdown banner must appear for already-open non-admin pages without
   requiring a manual page refresh after an admin starts maintenance.
7. Admin users are always exempt from maintenance-mode login blocks and forced
   logout behavior.
8. When the maintenance cutoff is reached, non-admin authenticated users must
   be logged out on their next request.
9. When the maintenance cutoff is reached, the normal login page must remain
   available, but non-admin login must be rejected.
10. When non-admin login is rejected due to maintenance, the login page must
   clearly state that the site is under maintenance and only admin login is
   allowed.
11. The system may show an optional admin-supplied maintenance message to
   non-admin users both during the countdown window and on the login page after
   cutoff.
12. Maintenance state must be persisted in the database so the behavior
    survives process restarts.
13. Maintenance state changes must record actor and timestamp fields for
    auditability.

## Non-Goals

- per-project maintenance windows
- read-only mode during the grace period
- separate maintenance-only login page
- bulk invalidation of every cookie session outside normal request handling
