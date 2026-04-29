---
title: Site Maintenance Mode Design
doc_type: spec
status: proposed
owner: engineering
last_updated: 2026-04-29
---

# Site Maintenance Mode Design

## Summary

This design adds an admin-controlled site maintenance mode that:

- gives non-admin users a fixed 15-minute grace period after activation
- keeps admins fully exempt and able to log in throughout
- shows non-admin users a bottom-centered live countdown during the grace period
- logs out non-admin users when the timer reaches zero
- blocks non-admin login after cutoff
- keeps the normal login page available, but shows a maintenance message stating
  that only admin login is allowed

The feature is global to the application and enforced centrally through request
hooks and login checks.

## Goals

- provide a single admin action to start and stop site maintenance
- allow non-admin users to continue working during a 15-minute warning window
- ensure admins can still log in and administer the site during maintenance
- force non-admin access to end at a deterministic cutoff time
- make the user-facing countdown and maintenance message consistent across pages
- keep the state restart-safe and auditable

## Non-Goals

- introducing per-project or per-site maintenance scopes
- making the application read-only during the grace period
- force-killing browser sessions out of band before the next request
- adding a separate maintenance-only login page
- changing role semantics beyond the admin maintenance exemption

## Current State

The application already has:

- central `before_request` logic in `app/__init__.py`
- centralized role enforcement in `app/decorators/role_required.py`
- shared login and session handling through Flask-Login
- admin-only operational surfaces in `app/routes/admin.py`

There is no current global maintenance-state model or request-level maintenance
enforcement.

## Proposed Design

### Maintenance State Storage

Add a persisted maintenance-state table with a single current row semantics.

Fields:

- `maintenance_id`
- `enabled`
- `starts_at`
- `cutoff_at`
- `message`
- `enabled_by_user_id`
- `disabled_at`
- `disabled_by_user_id`
- `created_at`
- `updated_at`

Behavior:

- `enabled = true` means maintenance mode is active
- `cutoff_at` is always `starts_at + 15 minutes`
- `message` is optional admin-supplied text shown to non-admin users
- only one active maintenance window should exist at a time

This should be a normal additive migration. Do not rely on Redis-only state for
this feature.

### Admin Actions

Add admin controls under Admin Actions:

- `Start Maintenance`
- `End Maintenance`

Start behavior:

- available to admins only
- creates or updates the current maintenance state
- sets `starts_at = now`
- sets `cutoff_at = now + 15 minutes`
- stores the optional message
- stores the acting admin

End behavior:

- available to admins only
- clears the active maintenance state by disabling it
- stores the disabling admin and timestamp

If maintenance is already active and an admin starts it again, the application
should refresh the window from the new current time rather than creating a
second overlapping active record.

### Request Enforcement

Enforce maintenance centrally in a shared request hook.

Admin behavior:

- admins are always exempt
- admins can log in before and after cutoff
- admins do not see forced logout behavior

Non-admin authenticated behavior before cutoff:

- requests continue normally
- shared template context includes countdown metadata
- no write restrictions are added

Non-admin authenticated behavior after cutoff:

- session is cleared on request
- user is logged out
- user is redirected to the normal login page
- login page shows maintenance messaging

Non-admin unauthenticated behavior after cutoff:

- login page remains accessible
- login attempts are blocked unless the user is an admin

This avoids fragile bulk session invalidation logic and matches the current
cookie-backed session model.

### Login Behavior

Keep the normal login page publicly reachable.

When maintenance is active after cutoff:

- admin login is allowed
- non-admin login is rejected
- login page displays:
  - `Site is under maintenance.`
  - `Only admin login is allowed right now.`
  - optional admin-supplied maintenance message if present

If maintenance is active but still inside the 15-minute grace window, normal
login remains allowed for non-admin users unless the product owner later asks
for a stricter policy. This matches the requested grace-period semantics.

### Non-Admin Countdown UI

During the grace period, all non-admin authenticated pages should show a fixed
bottom-center countdown element.

Requirements:

- fixed positioning at bottom center of viewport
- always visible above normal page content
- countdown decreases live in the browser
- includes a clear maintenance message
- includes the remaining time in minutes/seconds
- disappears for admins
- disappears when maintenance ends early

Suggested text:

- `Site is under maintenance`
- optional admin message below it
- `You will be logged out in 14:59`

When the countdown reaches zero on the client:

- redirect the browser to the login page
- server-side enforcement still remains authoritative on the next request

### Logged-Out Maintenance Message

After cutoff, logged-out or redirected non-admin users should see maintenance
messaging on the existing login page rather than a separate standalone page.

This preserves admin access without introducing a parallel authentication entry
point.

## Data Flow

### Start Maintenance

1. Admin triggers `Start Maintenance`.
2. Server writes active maintenance state with `cutoff_at = now + 15 minutes`.
3. Subsequent non-admin requests receive countdown context.
4. Existing non-admin sessions continue to function until cutoff.

### During Grace Period

1. Non-admin user loads any page.
2. Request hook allows the request.
3. Template context includes maintenance metadata.
4. Shared JS renders the bottom-centered countdown.

### At Cutoff

1. Browser timer reaches zero and redirects to login.
2. Any subsequent non-admin request also hits server-side enforcement.
3. Server clears session and logs out user.
4. Login page shows maintenance notice and blocks non-admin login.

### End Maintenance

1. Admin triggers `End Maintenance`.
2. Server disables maintenance state.
3. Countdown no longer renders.
4. Non-admin login becomes available again immediately.

## Components

Expected areas of change:

- model and migration for persisted maintenance state
- admin route(s) for start/stop maintenance
- request-hook enforcement in app initialization or a shared auth layer
- login submission path to block non-admin login after cutoff
- shared template context processor or helper for maintenance payload
- shared frontend asset for countdown banner
- login template messaging

## Error Handling

- starting maintenance when already active should refresh the active window
  cleanly rather than erroring
- ending maintenance when already inactive should be idempotent
- malformed or missing state should fail closed for non-admin enforcement only
  when an active row is clearly present
- admin routes must remain CSRF-protected and admin-only

## Security And Auditability

- only admins can start or end maintenance
- all state changes must record acting user and timestamp
- maintenance messages must not expose sensitive internal details
- server-side cutoff enforcement is authoritative; client timer is convenience
  only

## Backward Compatibility

This is additive:

- existing login page remains the login entry point
- existing session behavior is unchanged when maintenance is inactive
- admin access semantics remain unchanged except for the explicit maintenance
  exemption

## Testing Strategy

Add focused tests for:

- starting maintenance creates active state with 15-minute cutoff
- ending maintenance disables active state
- non-admin authenticated requests are allowed before cutoff
- non-admin authenticated requests are logged out after cutoff
- admin authenticated requests remain allowed after cutoff
- non-admin login is blocked after cutoff
- admin login remains allowed after cutoff
- login page shows maintenance message when active after cutoff
- non-admin pages receive countdown payload during grace period

If frontend tests are limited, at minimum verify the rendered HTML contains the
maintenance payload and banner container.

## Risks

- enforcing login blocking in the wrong layer could accidentally block admins
- client-only countdown logic would be insufficient without server enforcement
- injecting the banner in only one dashboard template would miss other pages,
  so the context should be wired through shared layout paths

## Recommendation

Implement this as a database-backed global maintenance window enforced through
central request and login checks, with a shared bottom-centered countdown
component for non-admin users during the grace period.
