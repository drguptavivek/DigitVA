---
title: Project Clock and Collection and Coding Gates
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-08
---

# Project Clock and Collection and Coding Gates

Owner decisions, 2026-11-06 (beads `digitva-fkec`, `digitva-g7xq` and the
beads named below). The project clock (stage 1), the coding gate on the project
clock, the data-collection gate (server and the Collect app's start check,
`digitva-dj29`) and dashboard bucketing (stage 2) are built. Payload and error
shapes: `docs/current-state/device-collection-api.md`, "Collection gate".

## Project clock

- Each project has a timezone, `va_project_master.timezone` (IANA name,
  default `Asia/Kolkata`, so existing projects keep today's behaviour),
  edited by an admin on the project form (Project Setup, Basics).
- Every "today" and calendar date that belongs to the project is taken on the
  project clock, not UTC and not the viewer's timezone:
  - the coding gate and collection gate start and end dates and their daily
    limits (below);
  - the coder daily allocation cap
    ([Coding Workflow State Machine](coding-workflow-state-machine.md),
    "Coder daily allocation limit");
  - date bucketing in the project's dashboards, KPIs, AI-question results
    and reports, including relative windows such as "today" and "the last 7
    days" (stage 2; rules in [KPIs](kpis.md), "Days follow the project
    clock"). A view spanning projects buckets each project on its own clock.
- Instants stay instants. A deadline such as the recode `recode_until`, or a
  sync time, is stored in UTC and shown in the viewer's own timezone
  (`{{ dt | user_timezone }}`); the project clock does not change it.
- A user's own timezone (`va_users.timezone`) still governs how times are
  displayed to that user.

## Coding gate

Unchanged in shape: per project-site (`va_project_sites`: `coding_enabled`,
`coding_start_date`, `coding_end_date`, `daily_coder_limit`), optionally
narrowed per organisation unit (`map_org_unit_coding_gate`), stricter wins,
waived for `coding_tester`, project PI and site PI
([Organization Model](organization-model.md), "Per-unit coding gates").
Change: its "today" is the project clock instead of UTC.

## Data-collection gate

A second gate, built the same way as the coding gate.

- **Where:** per project-site (`va_project_sites`: `collection_enabled`,
  `collection_start_date`, `collection_end_date`,
  `daily_interviewer_limit`), optionally narrowed per organisation unit
  (a `map_org_unit_collection_gate` row, at most one per unit; no row means no
  gate). Nearest gated ancestor wins; unit and site gates both apply and the
  stricter wins, as for coding.
- **Defaults:** enabled, no dates, no daily limit (`daily_interviewer_limit`
  nullable), so existing projects collect exactly as today.
- **What it stops:** starting a new registration, or a new interview with no
  registration, (web intake, the Collect app) for a site or unit whose gate
  is closed: switched off, before its start date, after its end date (start
  and end dates are inclusive), or the interviewer's daily limit reached.
  Starting the interview for a death already registered is continuing work
  and is not gated (owner 2026-11-06). The refusal names the site or unit and the reason
  ("Data collection for <unit> ended on <date>.").
- **What it never stops:** finishing and uploading an interview or
  registration already started, including work done offline on a phone.
  The server accepts it whatever the gate says, so no work is lost. Editing
  and revisions of existing interviews are not gated.
- **Daily limit:** new interviews started by that interviewer for that site
  (or unit) since midnight on the project clock. The limit is 1 to 100000, and is
  soft: two starts arriving at the same moment can pass it by one. A recorded refusal (the family
  declined the interview) does not count and is never refused (owner
  2026-11-06). The server does not refuse an upload that went over
  it (see "The phone applies the gate only online").
- **Waivers:** none by role; a data manager or admin opens the gate.
- **The app's copy (shape agreed with the app work, 2026-11-06):** the gate travels in
  `GET /api/v1/me/access`, additive fields only. A closed gate never removes
  the project's `interview` or `register_death` actions: the app (and older
  APKs) treat a project without them as unauthorised and purge its local
  data. Per project: the IANA timezone, `project_today` and `server_time`.
  Per site and per organisation unit (the ids the app sends when it
  registers a death or starts an interview), resolved on the server
  (nearest gated ancestor, stricter of site and unit): enabled, start and
  end date, daily limit, the caller's `today_count` at response time, a
  reason code with the unit's display name and the relevant date, and an
  English message for older clients. The app localises from the reason
  code and adds its own starts since the response to `today_count`.
- **Server refusals of a new start** use one error code with structured
  fields, HTTP 403 and the existing error body shape, and never apply to
  uploads of work already started.
- **ODK Collect:** interviews collected in ODK Collect and synced from ODK
  Central are outside DigitVA's control and are not gated; ODK stays the
  source of truth for that content.
- **Who edits:** the same people and panels that edit the coding gate
  (Project Sites panel; organisation units panel for unit gates).

## Governing rule (owner 2026-11-08)

"We don't want to lose any data but still apply gates on best effort
basis." No path may refuse, drop, overwrite or orphan an interview,
registration, refusal, draft or attachment because of the gate, on the
phone or the server, including old APKs, retries, duplicates, offline
queues and gate changes mid-upload. Gates only refuse new starts when the
phone is online with a fresh answer, and otherwise only hold or mark.
Holds apply to completed interviews with valid consent; refused and
incomplete uploads are kept and are already outside coding.

## The phone applies the gate only online (owner 2026-11-08, `digitva-nuy9`)

Replaces the earlier "a downloaded pause holds only on its own project day"
rule.

- The Collect app checks the gate (switch, dates, daily limit) before a new
  start **only when it is online and its gate answer is fresh**. Fresh means
  the answer came from a `GET /api/v1/me/access` call that succeeded within
  the last 15 minutes. Online with a fresh closed gate: the start is refused
  with the gate's message.
- Offline, or online with no fresh answer (the refresh failed), the app
  never blocks a new start. The server decides at upload (below).

## Uploads outside the collection period are accepted and held (owner 2026-11-08)

- The server accepts every upload of a DigitVA interview (Collect app, web
  intake), from any app version. No upload is refused for the gate, and no
  response shape changes.
- **Rule, decided once at the first upload of the interview:** take the
  interview's start date on the project clock (its recorded start time,
  else the time the server first received it). The interview is **held,
  outside collection period** when, for its site (and organisation unit,
  stricter wins, as for new starts), the gate at upload time is switched
  off, or that start date is before the start date or after the end date.
  The daily limit and a pause in the past are not knowable afterwards and
  never hold an interview.
- **While held** the interview is kept out of coding allocation, the coding
  and review queues, and reports, analytics, dashboards and exports. Its
  data is kept unchanged.
- **Clears by itself:** when the site or unit gate is saved and the
  interview's start date is now covered (dates widened, site switched back
  on), the hold clears without anyone acting, and the interview enters
  coding as any other.
- **Data manager action:** a data manager for that project or site (or an
  admin) sees the held list and can **release** (enter coding now) or
  **reject** (stays out of coding and reports; the data is never deleted;
  a reject can be undone by a release). Each action records who, when and
  an optional note in the audit log.
- **ODK Collect** submissions synced from ODK Central are not held (ODK is
  the source of truth; the gate never applied to them).

## Rollout

Additive migration: the project timezone column with its default, the four
site columns with their defaults, and the new unit table. Old phone app
versions do not know the gate; the server still accepts their uploads, and
they can start interviews offline as today until updated.
