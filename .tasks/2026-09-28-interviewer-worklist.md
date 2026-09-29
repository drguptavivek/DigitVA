# Interviewer worklist and interview state machine

- Status: Policy baseline written in docs/policy/web-intake.md (2026-09-29); implementation not started
- Priority: P2
- Created: 2026-09-28
- Bead: `digitva-vzk` (epic)
- Related: `docs/policy/web-intake.md`, `app/services/web_intake_service.py`,
  `app/models/va_web_intake.py`, `digitva-dyk` (prefill bug), `digitva-nrq`
  (death list 400), `digitva-wdj` (header summary), `digitva-ej1` (attachments)

## Goal

One list per interviewer of the deaths they are working on, whichever way the
interview started, with a clear state for each case:

1. **Register first.** Capture name of deceased, date of death, sex, address
   and contact details; the case joins the list; a **Start interview** button
   opens the WHO form with those details prefilled.
2. **Start directly.** **Start new interview** on the same page opens the WHO
   form at once; the case joins the list as soon as the form has captured
   enough identity (name, date of death, sex), so capture order is flexible.

## Where we start (mapped 2026-09-28)

- Project modes `off / direct / death_register / both` already gate the two
  routes (`_mode_allows`).
- `VaDeathRegister` holds the case details (name, sex, DOB/age, date of death,
  place of death, free-text address, informant name and one phone, ABHA,
  site/org unit) with statuses `registered, va_in_progress, va_submitted,
  cancelled` (`cancelled` never set; no edit or cancel endpoint).
- `VaWebIntakeDraft` holds answers per section with statuses `draft,
  submitted, discarded`; one active draft per death; owner-only.
- The dashboard shows two separate lists: "My drafts" (own drafts, all
  projects) and "Registered deaths" (everyone's in scope, full PII in JSON).
- Direct starts never create a death entry; nothing links them to the list.
- No assignment, appointment, contact-attempt or duplicate handling exists.

## Proposal

### One case record

Make the death register entry **the case**, for both routes. A direct start
creates a case immediately with `source = direct` and identity fields empty;
the draft's answers fill them in (Id10017/Id10018 name, Id10019 sex, Id10023
date of death, the form's calculated age) as they are saved. The list is then
one query over cases, not a union of two tables, and there is one state
machine. This needs `deceased_name` and `date_of_death` to become nullable
(additive, reversible migration) with a check that a case can only leave
`draft_identity` once they are set.

Until identity is captured the row shows as "New interview · details pending"
to its interviewer only.

### States

| State | Meaning | Entered by |
|---|---|---|
| `registered` | Basics captured, no interview yet | Register form |
| `scheduled` | Appointment date set | Interviewer sets date |
| `in_progress` | WHO form started, answers being saved | Start / resume interview |
| `paused` | Interviewer stopped mid-interview (outcome partially completed, or a pause) with a reason and optionally a revisit date | "Pause" / "Stop interview" action |
| `not_reachable` | Contact attempt failed, or outcome respondent unavailable; follow-up or revisit date | Log contact attempt / "Stop interview" |
| `refused` | Respondent declined (outcome refused). Soft: any team member may restart it | `interview_outcome` or action |
| `submitted` | WHO form submitted; case enters coding | Submit (existing) |
| `duplicate` | Same death as another case; points at it | Supervisor (or interviewer, see decisions) |
| `cancelled` | Registered in error | Supervisor (or registrant, see decisions) |

Transitions: registered ⇄ scheduled → in_progress ⇄ paused → submitted;
in_progress → not_reachable (decision 8);
registered/scheduled/paused/in_progress → not_reachable → scheduled/in_progress;
registered/scheduled/in_progress/paused → refused | duplicate | cancelled;
refused → in_progress (restart, audited; decision 9).
`submitted`, `duplicate` and `cancelled` are terminal except a supervisor
reopen (audited). `refused` is not terminal. Every transition writes an audit row (actor, from, to,
reason, time; no PII in the reason field by UI guidance).

### Supporting data

- `started_by_user_id` on the case (set when the interview starts; the
  registrant is already `registered_by`). No assignment field.
- `next_visit_at` (appointment or follow-up date) and `last_contact_at`.
- `map_case_contact_attempts` (case, time, outcome: reached / no answer /
  wrong number / moved / refused, next date, by user). Outcome only; no notes
  with PII.
- Contact details: keep the existing informant name and phone; add an
  optional second phone and structured address (house/street, village/ward,
  landmark) alongside the org unit. Phone validated (Indian mobile format),
  shown masked in lists, full only on the case page.

### Duplicate check

When a case gains name + date of death (either route), look for other open or
submitted cases in the same project with the same date of death (±3 days),
same sex, and a similar name (normalised, fuzzy) in the same or a
neighbouring unit. Show "Possible duplicate of <ID>" to the interviewer before
submit; a supervisor resolves (`duplicate` → links to the kept case).
Never auto-merge.

### The list

- Default view: **Team cases** in my scope with a "Mine" filter (registered
  or worked on by me), filtered by state,
  sorted by next visit date then last activity. Tabs: To visit (registered,
  scheduled, not reachable, paused), In progress, Done (submitted, refused).
- Row: ID, name (or "details pending"), sex, age, date of death, unit,
  state badge, next visit date, primary action (Start / Resume / Log attempt).
- Page top: **Register death** and **Start new interview** buttons (as the
  project mode allows).
- Supervisors (see decisions) get an **All in my scope** view showing who
  registered and who started each case (read-only; no reassignment).
- The WHO form page's pinned summary (`digitva-wdj`) reads from the case.

### Prefill and locking

Fix `digitva-dyk` first. Register-first cases prefill name, sex, date of death,
age/DOB, ABHA and the district presets (`digitva-dhc`); name/sex/date of death
are editable in the form (the form is the record of the interview), and edits
flow back to the case.

### Prefill map (owner, 2026-09-29: prefill name, age, sex, HIV/malaria, state, district, names)

| WHO question | Source | Locked |
|---|---|---|
| Id10010 interviewer name, Id10010c interviewer id | signed-in user (fix `digitva-dyk`) | yes |
| Id10002 / Id10003 HIV / malaria mortality | district presets (`digitva-dhc`, done) | yes |
| Id10017 / Id10018 given name, surname; Id10019 sex | case (death register) | no — the form is the record of the interview; edits flow back to the case |
| Id10021 date of birth, or age_group + age fields | case | no |
| Id10022 = yes, Id10023_a date of death | case | no |
| Id10058 where did the deceased die | case `place_of_death`, mapped to WHO choices | no |
| Id10057 where the death occurred (country, state, district, village) | org tree path names of the case's unit (e.g. India › Himachal Pradesh › Solan › Kandaghat › village) plus the case address | no |
| Id10055 usual residence | case address, else the same org path | no |
| Id10007 respondent name | case informant name | no |
| Id10061 / Id10062 father's / mother's name | new optional fields on the registration form (owner, 2026-09-29) | no |
| Id10010a / Id10010b interviewer age / sex | new user-profile fields (owner, 2026-09-29): year of birth (age computed at interview time, so it never goes stale) and sex | yes |

Rules: prefill applies once, when a draft is created and has no saved answers;
unlocked prefills are ordinary answers the interviewer can change; the org
codes (`org_<level>_code`) stay server-injected at submission as today.

## Owner decisions (2026-09-29)

1. **No assignment** (owner, 2026-09-29, superseding an earlier "self +
   supervisor" answer). A case belongs to whoever registered it until an
   interview starts, then to the interviewer who started it; there is no
   assign or reassign action and no `assigned_to_user_id`.
2. **Team cases** (owner, 2026-09-29): once a death is registered, anyone in
   the team — any interviewer whose scope covers the case — can start,
   continue or finish its interview; a case is not tied to one interviewer.
   So every interviewer sees all cases in their scope, and the one active
   draft per death becomes a shared team draft (today another interviewer
   gets a 409). Each save records who saved it; the audit trail keeps every
   interviewer who worked on the case. Concurrency rule still to settle (see
   open item 7). Supervisors see every case in their scope.
3. **Supervisors:** medical officers and similar staff at higher-level
   facilities (e.g. PHC, CHC, district hospital) overseeing the interviewers
   in the units below them, and data managers in scope. They view, resolve
   duplicates, cancel and reopen; they do not assign. Implication: a
   supervisory grant at an org unit covering its subtree (design to settle:
   a new `interview_supervisor` role at org-unit scope vs deriving it from an
   existing role; data managers already hold project/site/unit grants).
4. **Minimum identity from a direct start:** name + date of death + sex;
   until then the case shows only to its interviewer as "details pending".

Decided later the same day:

5. **Refused** (owner, 2026-09-29): a supervisor may reopen a refused case;
   the reopen is audited (who, when, reason). **Superseded 2026-09-30 by
   decision 9** (refused is soft; no reopen needed). Kept as history.
6. **Duplicate and cancel** (owner, 2026-09-29): both interviewers and
   supervisors can flag a case as a possible duplicate (naming the case it
   duplicates) or for cancellation (with a reason). An interviewer's flag
   waits for a supervisor to confirm or reject it; supervisors confirm (owner,
   2026-09-29), so a supervisor may confirm their own flag at once. Every flag, confirmation
   and rejection is audited; confirmed duplicates link to the kept case and
   are never merged automatically.
7. **Two interviewers on one case at once** (owner, 2026-09-29): **first
   submission wins, and offline capture is in scope.** No lock: team members
   may fill the same case independently, including offline on their own
   devices. The first **complete** submission accepted by the server becomes
   the case's submission. A submission that is **incomplete** (interview not
   finished) or a **refusal** (consent Id10013 = no) does not close the case:
   a later complete submission from any team member wins and becomes the
   case's submission, and the earlier one is kept as a superseded copy
   (owner, 2026-09-29). Once a complete submission has won, any later one is
   not merged and not silently dropped — it is stored as a superseded copy
   linked to the case, its interviewer is told, and a supervisor can view it.
   (Superseded in part by decision 8, 2026-09-30: the valid-form rule applies
   only to outcome `completed`.) Owner (2026-09-29): status comes from the WHO form's completion outcome.
   Finding: the WHO 2022 core has no outcome question — only consent Id10013
   (yes / no) and the closing `noteend` note; the form's own `completion.valid`
   says whether every required question is answered. Proposed mapping:
   Id10013 = no -> refused; submitted with `completion.valid` false (a new
   "Stop interview" action with a reason: respondent unavailable, needs to
   continue later, refused mid-way) -> incomplete; `completion.valid` true ->
   complete. If a recorded outcome question is wanted, add one DigitVA
   extension question at the end (`interview_outcome`: completed / partially
   completed / refused / respondent unavailable) rather than changing WHO's
   structure. **Decided (owner, 2026-09-29): add that one DigitVA question at
   the end, auto-filled** — `refused` when Id10013 (consent) = no, and
   `completed` when the form reports every required question answered
   (`completion.valid`); otherwise the interviewer picks partially completed
   or respondent unavailable. The case status follows this answer
   (refused / incomplete / complete) for the first-complete-submission rule.
   It lives in `digitva-extension.ts` under `digitva_core` (always on), after
   WHO's closing note, so WHO's own structure is untouched. **Incomplete** (owner, 2026-09-29) is defined by that
   DigitVA question: partially completed or respondent unavailable. **An
   incomplete or refused submission does not enter coding** (owner,
   2026-09-29): it stays with the case until a complete submission
   supersedes it or a supervisor closes the case. Implications to
   design: (a) drafts must be storable on the device for offline work, which
   reverses today's rule that answers are never kept in the browser
   (docs/policy/web-intake.md, field-data-collection.md) — so encrypted on
   device, deleted after upload, bounded, matching the attachment decision in
   `digitva-ej1`; (b) the server decides "first" by acceptance time, not
   device time; (c) the list shows "Submitted by <name>" on a case another
   team member finished while you were offline, and your copy's submit tells
   you so; (d) a case registered offline needs a client-generated id that the
   server reconciles (and duplicate checks run on upload).

Decided 2026-09-30 (owner):

8. **Incomplete submissions: no new state.** `interview_outcome` sets the case
   state: partially completed -> `paused`; respondent unavailable ->
   `not_reachable` with optional revisit date; refused -> `refused`; completed
   and first -> `submitted`. Transition `in_progress -> not_reachable` added.
   A valid form (`completion.valid`) is required only for `completed`; the
   other outcomes need `interview_outcome` and the minimum identity (name, date
   of death, sex), not the consent answer (Id10013). "Stop interview" stays,
   with optional revisit date. Replaces the "Submission" rule in
   `docs/policy/web-intake.md` when the worklist phases land.
9. **Refused is fully soft.** It blocks nothing: any team member may start or
   resume it, and a complete submission wins (`submitted`, refusal kept as a
   superseded copy). Restart moves it to `in_progress`, audited (who, when).
   Decision 5 is superseded. Open: whether to show "previously refused on
   <date>" and whether a restart needs a reason.
10. **Duplicate on a submitted case: coding follows state.** A supervisor may
    confirm it against a kept case they choose (UI warns if the duplicate is
    the one already coded). Not yet coded or waiting: excluded as
    `not_codeable_by_data_manager`, reason "duplicate of <kept case id>". Being
    coded: allocation revoked (`docs/policy/coding-allocation-timeouts.md`),
    then excluded. Finalized: coding stays intact, case marked duplicate and
    excluded from reporting counts, only a supervisor holding a data-manager
    grant may confirm. Audited, reversible by a supervisor. Open: today
    `not_codeable_by_data_manager` is legal only from `screening_pending`,
    `smartva_pending`, `ready_for_coding`, and no reporting-count exclusion
    mechanism exists.
11. **Supervisor model: derive from cadre.** Supervisor powers (view all cases
    in scope, confirm/reject duplicate and cancel flags, never assign) come
    from the cadre on a unit-scoped grant; no new role or grant. Data managers
    keep them through their grant. This makes cadre authoritative rather than
    descriptive, so `docs/policy/access-control-model.md` and
    `docs/policy/organization-model.md` must be amended in the same change that
    builds it. Still bounded by grant scope, status and closed-project
    dormancy. Supersedes the "design to settle" in decision 3. Open (see
    policy items 8 to 10, 14): how a cadre is marked supervising, which role's
    grant carries it, subtree reach, supervisor visibility of identity, audit
    of grant and cadre relied on.

## Phases (after decisions; each with tests and a migration where noted)

1. Fix `digitva-dyk` (prefill) and `digitva-nrq` (death list 400).
2. Case model: nullable identity, `source`, `started_by_user_id`, new states,
   transition service with audit; migration.
3. Direct start creates the case; draft saves fill identity; one worklist API.
4. Worklist UI (my cases, tabs, actions); register form gains structured
   address and validated phone.
5. Appointments, contact attempts, pause with reason; migration.
6. Duplicate check and supervisor resolution.
7. Supervisor view (read-only across scope).

Policy baseline in `docs/policy/web-intake.md` before phase 2.
