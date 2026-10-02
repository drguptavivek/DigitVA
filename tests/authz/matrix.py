"""The expected access matrix, written by hand (digitva-0wc, design 8).

Never computed from ``app.services.authz.RULES``: that would make the test a
tautology. Each row is ``(user key, action, target key, expected)`` where
expected is ``True`` (allowed), ``False`` (refused, any reason) or a
``Reason`` (refused for that reason). Targets: a sid key, ``form:<key>``,
``proj:<id>``, ``pair:<project>/<site>``, ``unit:<key>``, ``pin:<key>`` (the
ROUTE_PIN target unit), ``case:<unit key>`` (an intake case routed to that
unit) or ``sitecase:<project>/<site>`` (an unrouted intake case). Rows for
``LIST_DATA`` and ``LIST_UNROUTED`` with a sid target are checked through
``scope_filter`` membership.

Fixture: tests/authz/fixture.py. Policy shorthand in the comments:
ACM = docs/policy/access-control-model.md, OM = docs/policy/organization-model.md,
CWSM = docs/policy/coding-workflow-state-machine.md, DMG =
docs/policy/dm-user-grant-management.md, D = .tasks/digitva-0wc-design.md.
"""
from app.services.authz import Action, Reason

A = Action
NO_ROLE = Reason.NO_ROLE
OUT = Reason.OUT_OF_SCOPE
VIEW_ONLY = Reason.VIEW_ONLY
UNROUTED = Reason.UNROUTED
CLOSED = Reason.PROJECT_CLOSED

MATRIX = [
    # -- admin: global, every project, closed included (ACM "Closed Projects":
    #    admin bypass unchanged); no coding/reviewing/intake bypass (D 2.2, D 9.9)
    ("admin", A.VIEW, "ta-p1", True),
    ("admin", A.VIEW, "cl-1", True),                 # ACM: admin still reaches a closed project
    ("admin", A.TRIAGE, "cl-1", True),               # D 2.2: TRIAGE bypassed today (service layer)
    ("admin", A.LIST_DATA, "sp-1", True),            # D 2.2 / bead 4in: admin sees the DM grid
    ("admin", A.SYNC_FORM, "form:ta1", True),
    ("admin", A.LIST_UNROUTED, "proj:AZTA01", True),
    ("admin", A.LIST_UNROUTED, "ta-unr", True),      # the bypass lifts the project limit...
    ("admin", A.LIST_UNROUTED, "ta-p1", False),      # ...never the queue's shape: routed is out
    ("admin", A.LIST_UNROUTED, "sp-1", False),       # owner 2026-10-03: admin's queue is tree projects only
    ("admin", A.LIST_UNROUTED, "proj:AZSP01", OUT),  # a site project has nowhere to route to
    ("admin", A.CODE, "ta-p1", NO_ROLE),             # D 2.2: admin codes demo only
    ("admin", A.REVIEW, "ta-p1", NO_ROLE),
    ("admin", A.SUPERVISE_INTAKE, "case:P1", NO_ROLE),  # D 9.9: no intake bypass
    ("admin", A.CODE, "dm-1", True),                 # CWSM: demo open to every user

    # -- no grant at all: only the demo-training project
    ("nobody", A.VIEW, "ta-p1", NO_ROLE),
    ("nobody", A.TRIAGE, "sp-1", NO_ROLE),
    ("nobody", A.LIST_DATA, "sp-1", False),
    ("nobody", A.CODE, "dm-1", True),                # CWSM: no coder grant needed on demo
    ("nobody", A.RECODE, "dm-1", True),
    ("nobody", A.REVIEW, "dm-1", True),              # owner 2026-10-02: reviewing open on demo too
    ("nobody", A.VIEW, "dm-1", True),                # coding a demo case includes viewing it
    ("nobody", A.TRIAGE, "dm-1", NO_ROLE),           # owner: never data_manager on demo
    ("nobody", A.SYNC_FORM, "form:dm1", NO_ROLE),
    ("nobody", A.LIST_UNROUTED, "proj:AZTA01", NO_ROLE),

    # -- coder @project on a tree project with scope level + view_only
    #    (OM "Coding scope": a project grant is the top of the tree; under
    #    view_only it views every submission of the project and codes nothing)
    ("coder_ta", A.VIEW, "ta-d1", True),
    ("coder_ta", A.VIEW, "ta-unr", True),            # OM: includes unrouted
    ("coder_ta", A.VIEW, "ta-s2", True),             # every site of the project
    ("coder_ta", A.VIEW, "tb-g1", OUT),
    ("coder_ta", A.VIEW, "sp-1", OUT),               # same site id, other project: pairs, never bare site
    ("coder_ta", A.CODE, "ta-p1", VIEW_ONLY),
    ("coder_ta", A.CODE, "ta-unr", VIEW_ONLY),
    ("coder_ta", A.RECODE, "ta-sc1", VIEW_ONLY),     # D 4: RECODE has CODE's scope
    ("coder_ta", A.REVIEW, "ta-p1", NO_ROLE),
    ("coder_ta", A.TRIAGE, "ta-p1", NO_ROLE),
    ("coder_ta", A.LIST_DATA, "ta-p1", False),       # ACM route wiring: coders are not on the DM grid

    # -- coder @project_site on the tree project
    ("coder_ta_s1", A.VIEW, "ta-unr", True),         # OM: a pair grant includes unrouted of the pair
    ("coder_ta_s1", A.VIEW, "ta-p1", True),
    ("coder_ta_s1", A.VIEW, "ta-s2", OUT),           # another site of the same project
    ("coder_ta_s1", A.VIEW, "sp-1", OUT),            # OM: keyed on the pair, never the bare site id
    ("coder_ta_s1", A.CODE, "ta-unr", VIEW_ONLY),

    # -- coder @unit above the scope level, view_only (OM "Viewing scope":
    #    the whole subtree is viewable; nothing codeable)
    ("coder_c1", A.VIEW, "ta-c1", True),
    ("coder_c1", A.VIEW, "ta-p1", True),
    ("coder_c1", A.VIEW, "ta-sc1", True),
    ("coder_c1", A.VIEW, "ta-p2", True),
    ("coder_c1", A.VIEW, "ta-d1", OUT),              # ACM: grants flow down, never up
    ("coder_c1", A.VIEW, "ta-unr", UNROUTED),        # OM: unrouted reached by no unit grant
    ("coder_c1", A.CODE, "ta-p1", VIEW_ONLY),
    ("coder_c1", A.CODE, "ta-c1", VIEW_ONLY),

    # -- coder @unit at the scope level: codes its own subtree
    ("coder_p1", A.CODE, "ta-p1", True),
    ("coder_p1", A.CODE, "ta-sc1", True),
    ("coder_p1", A.RECODE, "ta-p1", True),
    ("coder_p1", A.CODE, "ta-p2", OUT),              # sibling PHC
    ("coder_p1", A.CODE, "ta-c1", OUT),              # parent unit
    ("coder_p1", A.CODE, "ta-unr", UNROUTED),
    ("coder_p1", A.VIEW, "ta-p2", OUT),
    ("coder_p1", A.REVIEW, "ta-p1", NO_ROLE),        # ACM: reviewing needs a reviewer grant

    # -- coder on a tree project with scope level + code_any
    ("coder_tb", A.CODE, "tb-g1", True),             # OM: code_any lets a project grant code
    ("coder_tb", A.CODE, "tb-f1", True),
    ("coder_tb", A.CODE, "tb-unr", True),            # project grant reaches unrouted
    ("coder_tb", A.CODE, "ta-p1", OUT),
    ("coder_f1", A.CODE, "tb-f1", True),             # OM: above the level, code_any codes the subtree
    ("coder_f1", A.CODE, "tb-g1", True),
    ("coder_f1", A.CODE, "tb-unr", UNROUTED),

    # -- coder on a site project (form-and-site model; ACM example 1)
    ("coder_sp", A.CODE, "sp-1", True),
    ("coder_sp", A.CODE, "sp-3", True),
    ("coder_sp", A.CODE, "sp-4", OUT),               # inactive project-site: coder needs an active pair
    ("coder_sp", A.VIEW, "sp-4", OUT),
    ("coder_sp", A.CODE, "ta-unr", OUT),             # tree project's form on the same site id
    ("coder_sp", A.CODE, "cl-1", CLOSED),            # ACM "Closed Projects"
    ("coder_sp1", A.CODE, "sp-1", True),
    ("coder_sp1", A.CODE, "sp-3", OUT),
    ("coder_sp1", A.CODE, "ta-unr", OUT),            # same site id, other project

    # -- coding_tester: exempt from the scope level (OM "Coding scope";
    #    F15 closed: project testers get the pool on a tree project, D 2.3)
    ("tester_ta", A.CODE, "ta-p1", True),
    ("tester_ta", A.CODE, "ta-d1", True),
    ("tester_ta", A.CODE, "ta-unr", True),
    ("tester_ta", A.VIEW, "ta-d1", True),
    ("tester_ta", A.REVIEW, "ta-p1", NO_ROLE),
    ("tester_c1", A.CODE, "ta-c1", True),            # above the level, still codes (exempt)
    ("tester_c1", A.CODE, "ta-sc1", True),
    ("tester_c1", A.CODE, "ta-d1", OUT),
    ("tester_c1", A.CODE, "ta-unr", UNROUTED),
    ("tester_c1", A.VIEW, "ta-p2", True),
    ("tester_sp", A.CODE, "sp-4", True),             # active-site rule is the coder's only

    # -- reviewer: views its scope, reviews under the coding scope rule (F7 closed, D 2.3)
    ("reviewer_ta", A.VIEW, "ta-p1", True),
    ("reviewer_ta", A.VIEW, "ta-unr", True),
    ("reviewer_ta", A.REVIEW, "ta-p1", VIEW_ONLY),
    ("reviewer_ta", A.REVIEW, "ta-unr", VIEW_ONLY),
    ("reviewer_ta", A.CODE, "ta-p1", NO_ROLE),
    ("reviewer_c1", A.VIEW, "ta-sc1", True),         # OM: same rule for the reviewer track
    ("reviewer_c1", A.REVIEW, "ta-p1", VIEW_ONLY),
    ("reviewer_p1", A.REVIEW, "ta-p1", True),
    ("reviewer_p1", A.REVIEW, "ta-sc1", True),
    ("reviewer_p1", A.REVIEW, "ta-p2", OUT),
    ("reviewer_p1", A.REVIEW, "ta-unr", UNROUTED),
    ("reviewer_sp1", A.REVIEW, "sp-1", True),
    ("reviewer_sp1", A.REVIEW, "sp-3", OUT),
    ("reviewer_sp1", A.VIEW, "sp-1", True),
    ("reviewer_sp1", A.REVIEW, "ta-unr", OUT),

    # -- data_manager @project on a tree project (ACM data_manager; unrouted
    #    queue decision 2026-10-02; whole-form ops need project/site grant)
    ("dm_ta", A.VIEW, "ta-d1", True),
    ("dm_ta", A.VIEW, "ta-unr", True),
    ("dm_ta", A.TRIAGE, "ta-p1", True),
    ("dm_ta", A.SYNC_SUBMISSION, "ta-unr", True),
    ("dm_ta", A.ROUTE_PIN, "ta-unr", True),
    ("dm_ta", A.ROUTE_PIN, "ta-d2", True),
    ("dm_ta", A.ROUTE_PIN, "pin:D2", True),          # D 2.3: a wide DM pins to any unit of the project
    ("dm_ta", A.ROUTE_PIN, "pin:F1", OUT),           # another project's unit
    ("dm_ta", A.LIST_UNROUTED, "proj:AZTA01", True),
    ("dm_ta", A.LIST_UNROUTED, "proj:AZTB01", OUT),
    ("dm_ta", A.LIST_UNROUTED, "ta-unr", True),
    ("dm_ta", A.LIST_UNROUTED, "ta-p1", False),      # routed: not in the queue
    ("dm_ta", A.SYNC_FORM, "form:ta1", True),
    ("dm_ta", A.SYNC_FORM, "form:tb1", OUT),
    ("dm_ta", A.LIST_DATA, "ta-sc1", True),
    ("dm_ta", A.LIST_DATA, "tb-g1", False),
    ("dm_ta", A.TRIAGE, "tb-g1", OUT),
    ("dm_ta", A.CODE, "ta-p1", NO_ROLE),             # ACM: a data manager may not start coding
    ("dm_ta", A.TRIAGE, "dm-1", False),              # owner: demo is never data_manager
    ("dm_ta", A.SUPERVISE_INTAKE, "case:P1", True),  # web-intake: a DM supervises its own scope
    ("dm_ta", A.SUPERVISE_INTAKE, "case:G1", OUT),

    # -- data_manager @project_site on a tree project
    ("dm_ta_s1", A.TRIAGE, "ta-p1", True),
    ("dm_ta_s1", A.TRIAGE, "ta-unr", True),
    ("dm_ta_s1", A.TRIAGE, "ta-s2", OUT),            # another site of the project
    ("dm_ta_s1", A.TRIAGE, "sp-1", OUT),             # same site id, other project (lh1h)
    ("dm_ta_s1", A.ROUTE_PIN, "ta-s2", True),        # ACM: unrouted queue open to every DM of the project
    ("dm_ta_s1", A.LIST_UNROUTED, "proj:AZTA01", True),
    ("dm_ta_s1", A.SYNC_FORM, "form:ta1", True),
    ("dm_ta_s1", A.SYNC_FORM, "form:ta2", OUT),
    ("dm_ta_s1", A.SYNC_FORM, "form:sp1", OUT),

    # -- data_manager @unit (ACM: a unit grant covers its subtree on every
    #    surface; whole-form operations need a project or site grant)
    ("dm_c1", A.VIEW, "ta-p1", True),
    ("dm_c1", A.TRIAGE, "ta-c1", True),
    ("dm_c1", A.SYNC_SUBMISSION, "ta-sc1", True),
    ("dm_c1", A.TRIAGE, "ta-d1", OUT),
    ("dm_c1", A.TRIAGE, "ta-unr", UNROUTED),
    ("dm_c1", A.VIEW, "ta-unr", UNROUTED),
    ("dm_c1", A.ROUTE_PIN, "ta-unr", True),          # ACM: the queue, unit included
    ("dm_c1", A.ROUTE_PIN, "ta-p1", True),
    ("dm_c1", A.ROUTE_PIN, "ta-d1", OUT),
    ("dm_c1", A.ROUTE_PIN, "pin:P2", True),          # ACM: route into own subtree
    ("dm_c1", A.ROUTE_PIN, "pin:D1", OUT),           # ACM: never outside it
    ("dm_c1", A.LIST_UNROUTED, "proj:AZTA01", True),
    ("dm_c1", A.SYNC_FORM, "form:ta1", OUT),
    ("dm_c1", A.LIST_DATA, "ta-p2", True),
    ("dm_c1", A.LIST_DATA, "ta-d2", False),
    ("dm_c1", A.SUPERVISE_INTAKE, "case:SC1", True),
    ("dm_c1", A.SUPERVISE_INTAKE, "case:D1", OUT),

    # -- data_manager on a site project
    ("dm_sp", A.TRIAGE, "sp-1", True),
    ("dm_sp", A.TRIAGE, "sp-4", OUT),                # a site moved out of the project: DM reach stops at an inactive pair (grid, KPI cards)
    ("dm_sp", A.VIEW, "sp-4", OUT),
    ("dm_sp", A.LIST_UNROUTED, "proj:AZSP01", OUT),  # no tree, no unrouted queue
    ("dm_sp", A.LIST_UNROUTED, "sp-1", False),
    ("dm_sp", A.SYNC_FORM, "form:sp3", True),
    ("dm_sp", A.TRIAGE, "ta-unr", OUT),
    ("dm_sp1", A.TRIAGE, "sp-1", True),
    ("dm_sp1", A.TRIAGE, "sp-3", OUT),
    ("dm_sp1", A.TRIAGE, "ta-unr", OUT),             # same site id, other project (lh1h)
    ("dm_sp1", A.SYNC_FORM, "form:sp1", True),
    ("dm_sp1", A.SYNC_FORM, "form:sp3", OUT),

    # -- project_pi on a tree project (ACM project_pi, organizational project:
    #    every screen, acts as data_manager and interview_supervisor project-wide)
    ("pi_ta", A.VIEW, "ta-d2", True),
    ("pi_ta", A.VIEW, "ta-unr", True),
    ("pi_ta", A.TRIAGE, "ta-p1", True),
    ("pi_ta", A.SYNC_SUBMISSION, "ta-unr", True),
    ("pi_ta", A.ROUTE_PIN, "ta-unr", True),
    ("pi_ta", A.ROUTE_PIN, "pin:D2", True),
    ("pi_ta", A.LIST_UNROUTED, "proj:AZTA01", True),
    ("pi_ta", A.SYNC_FORM, "form:ta2", True),
    ("pi_ta", A.LIST_DATA, "ta-d1", True),
    ("pi_ta", A.SUPERVISE_INTAKE, "case:SC1", True),
    ("pi_ta", A.SITE_PI_REPORT, "pair:AZTA01/AZS1", True),  # ACM: view reporting for the project
    ("pi_ta", A.SITE_PI_REPORT, "unit:P1", True),
    ("pi_ta", A.CODE, "ta-p1", NO_ROLE),             # ACM: coding still requires a coder grant
    ("pi_ta", A.REVIEW, "ta-p1", NO_ROLE),
    ("pi_ta", A.VIEW, "tb-g1", OUT),
    ("pi_ta", A.TRIAGE, "sp-1", OUT),

    # -- project_pi on a site project: only the first list (view data and
    #    reporting; owner: no DM actions, bead note "Open questions settled" 1)
    ("pi_sp", A.VIEW, "sp-1", True),
    ("pi_sp", A.VIEW, "sp-4", True),
    ("pi_sp", A.TRIAGE, "sp-1", NO_ROLE),
    ("pi_sp", A.SYNC_FORM, "form:sp1", NO_ROLE),
    ("pi_sp", A.LIST_UNROUTED, "proj:AZSP01", NO_ROLE),
    ("pi_sp", A.LIST_DATA, "sp-1", False),           # D 2.3: LIST_DATA only as DM (tree projects)
    ("pi_sp", A.SITE_PI_REPORT, "pair:AZSP01/AZS3", True),
    ("pi_sp", A.SITE_PI_REPORT, "pair:AZTA01/AZS1", OUT),
    ("pi_sp", A.CODE, "sp-1", NO_ROLE),
    ("pi_sp", A.SUPERVISE_INTAKE, "sitecase:AZSP01/AZS1", NO_ROLE),  # supervision only on a tree
    ("dm_sp1", A.SUPERVISE_INTAKE, "sitecase:AZSP01/AZS1", True),  # a DM supervises its own pair
    ("dm_sp1", A.SUPERVISE_INTAKE, "sitecase:AZSP01/AZS3", OUT),

    # -- site_pi @project_site (ACM site_pi)
    ("sitepi_sp1", A.VIEW, "sp-1", True),
    ("sitepi_sp1", A.VIEW, "sp-3", OUT),
    ("sitepi_sp1", A.VIEW, "ta-unr", OUT),           # same site id, other project
    ("sitepi_sp1", A.TRIAGE, "sp-1", NO_ROLE),
    ("sitepi_sp1", A.CODE, "sp-1", NO_ROLE),
    ("sitepi_sp1", A.SITE_PI_REPORT, "pair:AZSP01/AZS1", True),
    ("sitepi_sp1", A.SITE_PI_REPORT, "pair:AZSP01/AZS3", OUT),
    ("sitepi_sp1", A.SITE_PI_REPORT, "pair:AZTA01/AZS1", OUT),
    ("sitepi_sp1", A.LIST_DATA, "sp-1", False),

    # -- In-charge: site_pi @unit (ACM "In-charge": every DM power in the
    #    subtree, oversees field work, site PI report; D 9.3: no whole-form sync)
    ("incharge_c1", A.VIEW, "ta-p1", True),
    ("incharge_c1", A.VIEW, "ta-d1", OUT),
    ("incharge_c1", A.TRIAGE, "ta-c1", True),
    ("incharge_c1", A.SYNC_SUBMISSION, "ta-sc1", True),
    ("incharge_c1", A.ROUTE_PIN, "ta-unr", True),
    ("incharge_c1", A.ROUTE_PIN, "pin:P2", True),
    ("incharge_c1", A.ROUTE_PIN, "pin:D1", OUT),
    ("incharge_c1", A.LIST_UNROUTED, "proj:AZTA01", True),
    ("incharge_c1", A.LIST_DATA, "ta-p2", True),
    ("incharge_c1", A.SYNC_FORM, "form:ta1", OUT),
    ("incharge_c1", A.SITE_PI_REPORT, "unit:P1", True),
    ("incharge_c1", A.SITE_PI_REPORT, "unit:D1", OUT),
    ("incharge_c1", A.SUPERVISE_INTAKE, "case:SC1", True),
    ("incharge_c1", A.SUPERVISE_INTAKE, "case:D2", OUT),
    ("incharge_c1", A.CODE, "ta-p1", NO_ROLE),       # ACM: coding still requires a coder grant
    ("incharge_c1", A.REVIEW, "ta-p1", NO_ROLE),

    # -- viewers (ACM collaborator / collaborator_pii: view one submission
    #    read-only within scope, the data grid; no writes)
    ("collab_c1", A.VIEW, "ta-p1", True),
    ("collab_c1", A.VIEW, "ta-d1", OUT),
    ("collab_c1", A.VIEW, "ta-unr", UNROUTED),
    ("collab_c1", A.LIST_DATA, "ta-sc1", True),
    ("collab_c1", A.LIST_DATA, "ta-d1", False),
    ("collab_c1", A.TRIAGE, "ta-p1", NO_ROLE),
    ("collab_c1", A.CODE, "ta-p1", NO_ROLE),
    ("collabpii_sp", A.VIEW, "sp-4", OUT),           # viewer reach stops at an inactive pair, as the DM grid does
    ("collabpii_sp", A.VIEW, "ta-unr", OUT),
    ("collabpii_sp", A.LIST_DATA, "sp-3", True),
    ("collabpii_sp", A.SYNC_FORM, "form:sp1", NO_ROLE),

    # -- interviewer / interview_supervisor (web intake has its own scope;
    #    nothing on coding or DM screens, D 2.3)
    ("interviewer_p1", A.VIEW, "ta-p1", NO_ROLE),
    ("interviewer_p1", A.SUPERVISE_INTAKE, "case:P1", NO_ROLE),
    ("supervisor_c1", A.SUPERVISE_INTAKE, "case:P1", True),
    ("supervisor_c1", A.SUPERVISE_INTAKE, "case:D1", OUT),
    ("supervisor_c1", A.VIEW, "ta-p1", NO_ROLE),
    ("supervisor_c1", A.TRIAGE, "ta-p1", NO_ROLE),

    # -- mentoring institute member: the guard is write-time only, can()
    #    never consults membership (OM "Mentoring institutes", D 2.3)
    ("mentor", A.CODE, "ta-p1", True),
    ("mentor", A.CODE, "ta-c1", OUT),
    ("mentor", A.VIEW, "ta-c1", True),               # collaborator_pii @D1
    ("mentor", A.VIEW, "ta-d1", True),
    ("mentor", A.VIEW, "ta-d2", OUT),
    ("mentor", A.TRIAGE, "ta-d1", NO_ROLE),

    # -- one person, two grants: each lens answers for its own role
    ("mixed", A.CODE, "ta-p1", True),
    ("mixed", A.VIEW, "sp-1", True),                 # collaborator @project on the site project
    ("mixed", A.CODE, "sp-1", OUT),                  # viewing never becomes coding (OM)
    ("mixed", A.LIST_DATA, "sp-3", True),
    ("mixed", A.LIST_DATA, "ta-p1", False),          # a coder grant is not a DM-grid grant
    ("mixed", A.VIEW, "cl-1", CLOSED),

    # -- closed project: resolves no grant (ACM "Closed Projects")
    ("closed_coder", A.VIEW, "cl-1", NO_ROLE),
    ("closed_coder", A.CODE, "cl-1", NO_ROLE),
]
