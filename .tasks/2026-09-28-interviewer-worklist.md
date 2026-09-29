# Interviewer worklist and interview state machine

- Status: Policy baseline written in docs/policy/web-intake.md (2026-09-29); phases 2 and 3 built (2026-09-30, `digitva-vzk.4`, migration `c4e8a2f6b9d3`); phase 4 worklist page built (2026-09-30, `digitva-vzk.6`, no migration)
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
   existing role; data managers already hold project/site/unit grants; settled by decision 15: a new
   `interview_supervisor` role).
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
   design: (a) device drafts follow Path B of
   `docs/policy/field-data-collection.md`: offline capture runs in the native
   app only (owner, 2026-09-30), encrypted, hardware-backed keys, one store per
   interviewer, purged after upload, no retention ceiling (decision C3), wiped
   on logout; the browser page stays online-only and Path A is unchanged;
   offline capture is in no phase of this plan and belongs to the native-app
   work; (b) the server decides "first" by acceptance time, not
   device time; (c) the list shows "Submitted by <name>" on a case another
   team member finished while you were offline, and your copy's submit tells
   you so; (d) a case registered offline needs a client-generated id that the
   server reconciles (and duplicate checks run on upload).

Decided 2026-09-30 (owner):

7a. **Offline runs in the native app only**, under Path B as written. This
    answers open items 2 (keys), 3 (storage bounds: no ceiling, C3, "bounded"
    dropped), 4 (no expiry), 5 (wipe on logout and revocation, own store only)
    and 7 (where offline runs). Also decided (2026-09-30): 6 (a device draft
    that arrives after a teammate's complete submission won is uploaded
    automatically as a superseded copy, and the interviewer is told) and 18
    (the device copy is the interviewer's own attempt, submitted as its own
    submission, never merged into the shared draft). No design question is
    open.

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
   Decision 5 is superseded. Decided (2026-09-30): nothing extra on restart
   (no notice, no reason; audit only).
10. **Duplicate on a submitted case: coding follows state.** A supervisor may
    confirm it against a kept case they choose (UI warns if the duplicate is
    the one already coded). Mechanism superseded by decision 14: case-level
    exclusion, not `not_codeable_by_data_manager`. Being coded: allocation
    revoked (`docs/policy/coding-allocation-timeouts.md`). Finalized: coding
    stays intact, case excluded from reporting counts, only a supervisor holding
    a data-manager grant may confirm. Audited, reversible by a supervisor.
11. **Supervisor model: derive from cadre.** (Owner, 2026-09-30; the "derive
    from cadre, no new role" part is **superseded by decision 15**, kept as
    history.) Supervisor powers (view all cases in scope, confirm/reject
    duplicate and cancel flags, never assign) were to come from the cadre on a
    unit-scoped grant. Data managers keep them through their grant. Still
    bounded by grant scope, status and closed-project dormancy. Supersedes the
    "design to settle" in decision 3. The four follow-ups (marking, carrying
    grant, subtree, identity visibility and audit) are settled by decisions 12,
    13 and 15.
12. **Supervising cadre is an admin-set flag on the level x cadre grid**
    (owner, 2026-09-30). A third permission `can_supervise_interviews` on the
    `map_org_level_cadre` row, next to `can_fill_va_form` and
    `can_code_va_form`; not on the cadre itself, so an MO can supervise at a
    PHC or CHC but not at a sub-centre. Set by an admin or project PI in the
    same grid editor and `level_cadres` workbook sheet (import and export) as
    the existing flags. No cadre names in code.
13. **Which grants carry the power** (owner, 2026-09-30). **The carrying-grants
    part is superseded by decision 15** (a new `interview_supervisor` grant
    role; `coder` and `interviewer` grants no longer confer supervision). Kept
    as history; the subtree, identifier-visibility, audit and bounds parts
    stand. Original text: A `coder` or
    `interviewer` grant on a unit whose level x cadre row is flagged
    `can_supervise_interviews`, using that grant's cadre, confers supervisor
    power over that unit's subtree (a unit grant covers its unit and everything
    beneath it; resolves policy item 10). `data_manager` grants supervise
    through the grant. Deliberately not reviewer, collaborator,
    collaborator_pii, coding_tester, site_pi or project_pi: no silent widening.
    Bounded by grant scope, status and closed-project dormancy
    (shared predicate). Identifier visibility (deceased name, informant name
    and phones, address) applies only in the worklist and case-administration
    views; coding screens keep `should_redact_pii` unchanged. Every supervisor
    action's audit row names the grant and the cadre relied on.
14. **Confirmed duplicate: case-level exclusion** (owner, 2026-09-30). Confirming
    marks the case (pointing at the kept case); the submission's coding
    workflow state is untouched, with no new state or transition and no reuse of
    `not_codeable_by_data_manager`. Every reader of coding state (allocation,
    pick-and-choose, queue and dashboard counts, SmartVA generation,
    reviewer and secondary queues, exports, analytics and materialized views)
    excludes such submissions through ONE shared predicate, the pattern of
    `active_project_condition`. An active allocation is revoked on
    confirmation. Undo clears the mark and coding resumes from the state it was
    in. A finalized duplicate keeps its coding, is excluded from reporting
    counts, and only a supervisor with a data-manager grant may confirm it.
    Build requirement: a test that enumerates every allocation, list, count,
    export and view path and fails when one ignores the predicate.
15. **Supervisor is a new explicit grant role, `interview_supervisor`, with a
    cadre check** (owner, 2026-09-30). Supersedes the carrying-grants part of
    decision 13 and the "derive from cadre, no new role" part of decision 11;
    decisions 12 and 14 stand.
    - `interview_supervisor` is the permission. Scope: **org_unit only**
      (owner, 2026-09-30, item 16), so every supervisor grant gets the cadre
      check; broad supervision is a grant on a top unit. A unit grant covers its
      unit and everything beneath it.
    - **Write-time check:** an `interview_supervisor` unit grant requires a
      cadre, and that cadre must be flagged `can_supervise_interviews` on the
      level x cadre row for the unit's level (decision 12), the way a `coder`
      grant requires a cadre with `can_code_va_form`. The cadre is checked when
      the grant is written, not itself a permission; the runtime then reads the
      grant's role. Cadre stays descriptive, consistent with the existing
      organization-model rule, so cadre does **not** become authoritative.
    - `coder` and `interviewer` grants no longer confer supervision. A medical
      officer who supervises gets an additional `interview_supervisor` grant
      (one grant per user x role x unit already allows it). `data_manager`
      grants keep supervising through the grant. All other roles confer nothing.
    - Unchanged: powers (view all cases in scope, confirm/reject duplicate and
      cancel flags, reopen where still applicable, never assign; only a
      supervisor holding a data_manager grant may confirm a finalized
      duplicate), the privacy rule (identifiers only in worklist and
      case-administration views; coding screens keep `should_redact_pii`),
      audit rows naming the grant and cadre relied on, bounds (grant scope,
      status, closed-project dormancy via the shared predicate).
    - **Docs to amend when built:** access-control-model.md Role To Scope Rules
      and the `role_scope` check constraint (a migration); the grants panel and
      grant import options; one sentence in organization-model.md that
      `interview_supervisor` joins `coder` as a role whose grant needs a cadre
      check; coding-workflow-state-machine.md (decision 14).
    - **Decided (owner, 2026-09-30):** (16) supervisor grants are unit-scoped
      only. (17) The supervisor grant alone gives the
      supervisor views of its reach (no interviewer grant needed).
    - **Decided (owner, 2026-09-30):** (11) "details pending" is visible to its
      starter and to supervisors, not to teammates; (12) a registrant may edit
      and cancel their own registration until an interview starts, audited.

## Phases (after decisions; each with tests and a migration where noted)

1. Fix `digitva-dyk` (prefill) and `digitva-nrq` (death list 400).
2. Case model: nullable identity, `source`, `started_by_user_id`, new states,
   transition service with audit; migration. **Built 2026-09-30**
   (`digitva-vzk.4`): `app/services/case_transition_service.py`,
   `map_case_transitions`; pre-identity state `draft_identity`; supervisor
   moves fail closed until `digitva-vzk.5`. Details in docs/policy/web-intake.md,
   "Built in phases 2 and 3".
3. Direct start creates the case; draft saves fill identity; one worklist API.
   **Built 2026-09-30** (`digitva-vzk.4`): `GET /intake/api/cases`, flags at
   `POST /intake/api/cases/<death_id>/flags`. Drafts stay owner-only (team
   drafts not yet built). Open: a death whose date is unknown (year only)
   cannot reach the minimum identity.
4. Worklist UI (my cases, tabs, actions). **Built 2026-09-30**
   (`digitva-vzk.6`): one list on `/intake/` over `GET /intake/api/cases`,
   `app/static/js/intake/intake_worklist.js`; flag duplicate / cancel from the
   row. No schema change. The register form's structured address and
   validated phone moved to phase 5 (they need a migration).
5. Appointments, contact attempts, pause with reason; register form gains
   structured address and validated phone; migration.
6. Duplicate check and supervisor resolution.
7. Supervisor view (read-only across scope).

Policy baseline in `docs/policy/web-intake.md` before phase 2.
