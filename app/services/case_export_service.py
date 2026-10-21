"""CSV export of the shared case list: ``GET /api/v1/cases/export.csv``.

Policy: docs/policy/case-list-views.md ("Scope and field visibility") and
docs/policy/death-registration-identifiers.md decision 9 / "CSV export". Same
scope and filters as ``case_list_service.list_cases``; the columns are the row
fields a data manager sees minus what ``data-manager-workflow.md`` keeps out of
bulk extracts (no deceased or informant name, address, phone, GPS, payload).

Registration numbers are the recorded exception: one column per active type
(``sort_order``, header = type label) for the projects where the exporter is
admin or holds a live assigned data_manager, project_pi or site_pi grant
(``export_roles``), none for any other exporter. The
response streams: each keyset batch is one ``list_cases`` call (its numbers
decrypted in memory by ``identifier_payloads``, a constant number of queries)
and nothing is written to a file, so no plaintext copy outlives the request.
``prepare`` first runs those batches once as a validation pass (500
``export_unreadable``, no audit row, no body, when a number cannot be
decrypted), then commits the audit rows before the first byte.
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field

from flask import current_app

from app import db
from app.models import MapIdentifierAudit, VaUsers
from app.services import case_list_service as case_list
from app.services.authz import resolve_grants
from app.services.identifier_type_service import list_types
from app.services.web_intake_service import WORKLIST_PAGE_MAX, WebIntakeError

log = logging.getLogger(__name__)

#: Rows per keyset batch (one query for the rows, a few for the numbers).
BATCH = WORKLIST_PAGE_MAX
EVENT = "export_with_identifiers"
#: Row fields exported, in order. No names of the deceased, no coordinates.
COLUMNS = (
    "death_id", "unique_id", "project_id", "site_id", "org_unit_id", "unit_name", "status", "register_state",
    "source", "deceased_sex", "age_years", "date_of_death", "reported_at", "created_at", "updated_at",
    "reporter_name", "interviewer_name", "coder_name",
)
_FORMULA_CHARS = "=+-@"
_FORMULA_STARTS = ("\t", "\r", "\n")
#: Projects whose exporter may get the numbers: admin, or a live ASSIGNED grant
#: in one of these (policy decision 9), in the order the audit row names them.
EXPORT_ROLES = ("data_manager", "project_pi", "site_pi")


class ExportDecryptError(RuntimeError):
    """A number the export promised could not be decrypted; the stream stops."""


def safe_cell(value):
    """*value* ready for a CSV cell: None is empty, and text that a
    spreadsheet would run as a formula (also after leading whitespace or a
    newline) gets a leading apostrophe."""
    if value is None:
        return ""
    if isinstance(value, str) and (value.startswith(_FORMULA_STARTS) or value.lstrip().startswith(tuple(_FORMULA_CHARS))):
        return "'" + value
    return value


@dataclass
class ExportPlan:
    preset: str
    filters: case_list.CaseFilters
    identifier_headers: list[str] = field(default_factory=list)
    #: ``"full"``, ``"partial"`` or None (no identifier columns).
    identifier_columns: str | None = None
    #: Pinned at ``prepare`` (what the audit rows name): ``{project_id: {type code: header}}``.
    columns: dict[str, dict[str, str]] = field(default_factory=dict)


def _filter_trace(filters: case_list.CaseFilters) -> dict:
    """The filter set for the audit row: set filters only, and for the number
    search only that it was used, never the number."""
    trace = {}
    for name, value in vars(filters).items():
        if value in (None, "", (), False):
            continue
        if name == "identifier_number":
            trace[name] = True
        elif isinstance(value, tuple):
            trace[name] = list(value)
        else:
            trace[name] = str(value)
    return trace


def prepare(user: VaUsers, args) -> tuple[ExportPlan, int]:
    """Parse *args* like the list, decide the identifier columns and write (and
    commit) the audit rows. Returns ``(plan, row count)``. Raises
    ``WebIntakeError`` (400) for a bad query, (413 ``export_too_large``) over
    ``EXPORT_MAX_ROWS``, (500 ``export_unreadable``) when a number to be
    exported cannot be decrypted, before anything is written (the validation
    pass runs the stream's batches once, decrypting in memory, before the audit row).

    One ``export_with_identifiers`` row per qualifying project, sharing the
    filter set, the total row count and the type codes of that project
    (``map_identifier_audit.project_id`` is not null, so a multi-project export
    cannot be a single row), the role being that of the grant in that project. No row when no identifier column is exported.
    """
    query = case_list.parse_query(args)
    plan = ExportPlan(preset=query["preset"], filters=query["filters"])
    count, projects = case_list.export_summary(user, preset=plan.preset, filters=plan.filters)
    limit = current_app.config.get("EXPORT_MAX_ROWS", 200000)
    if count > limit:
        raise WebIntakeError(f"The export has {count} rows; narrow the filters to {limit} or fewer.", 413, "export_too_large")
    roles = export_roles(user, projects) if count else {}
    qualifying = sorted(roles)
    codes = {}
    sort_orders: dict[str, int] = {}
    for project_id in qualifying:
        active = [t for t in list_types(project_id) if t.is_active]
        codes[project_id] = [t.code for t in active]
        label_count = Counter(t.label for t in active)
        plan.columns[project_id] = {}
        for t in active:
            header = t.label if label_count[t.label] == 1 else f"{t.label} ({t.code})"
            plan.columns[project_id][t.code] = header
            sort_orders.setdefault(header, t.sort_order)
    if not sort_orders:
        plan.columns = {}
        return plan, count
    plan.identifier_headers = sorted(sort_orders, key=lambda h: (sort_orders[h], h))
    plan.identifier_columns = "full" if len(qualifying) == len(projects) else "partial"
    # Before the audit row and the first byte: an export that cannot be read in full is refused.
    if _first_unreadable(user, plan) is not None:
        raise WebIntakeError("A registration number could not be read; the export was not produced.", 500, "export_unreadable")
    trace = _filter_trace(plan.filters) | {"preset": plan.preset}
    for project_id in qualifying:
        db.session.add(MapIdentifierAudit(
            project_id=project_id, event=EVENT, actor_user_id=user.user_id, actor_role=roles[project_id],
            details={"filters": trace, "row_count": count, "type_codes": codes[project_id],
                     "columns": plan.identifier_columns},
        ))
    db.session.commit()
    return plan, count


def stream(user: VaUsers, plan: ExportPlan):
    """The CSV as UTF-8 byte chunks, one keyset batch at a time.

    Numbers are decrypted only for the projects pinned in *plan* and filled
    only for the type codes pinned there (by code, so equal labels or an
    inactive type holding a value cannot land in another column). A number
    the reader may see but that fails to decrypt raises ``ExportDecryptError``
    before its batch is written: the audit row says "exported", so the body
    must not carry a silent empty cell. The response is already streaming, so
    the client sees a truncated download, not a status. ``prepare`` has already
    run the same batches as a validation pass, so this only fires if a value
    broke between the two.
    """
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([safe_cell(c) for c in (*COLUMNS, *plan.identifier_headers)])
    for page, unreadable in _batches(user, plan):
        if unreadable is not None:  # the validation pass in ``prepare`` normally catches this first
            raise ExportDecryptError("a registration number could not be decrypted")
        for row in page["cases"]:
            colmap = plan.columns.get(row.get("project_id"), {})
            numbers = {colmap[e["code"]]: e.get("value") for e in row.get("identifiers", ()) if e.get("code") in colmap}
            writer.writerow([safe_cell(row.get(c)) for c in COLUMNS]
                            + [safe_cell(numbers.get(h)) for h in plan.identifier_headers])
        yield out.getvalue().encode("utf-8")
        out.seek(0)
        out.truncate()


def _batches(user: VaUsers, plan: ExportPlan):
    """``(page, unreadable)`` per keyset batch, in the list's order. *unreadable*
    is ``(death_id, type code)`` of the first pinned number the exporter may
    see that failed to decrypt (logged by ids only), else None. The read
    transaction is ended after each batch so no pooled connection is held
    while a slow client drains the chunks."""
    pinned = set(plan.columns)
    cursor = None
    while True:
        page = case_list.list_cases(user, preset=plan.preset, filters=plan.filters, cursor=cursor, limit=BATCH,
                                    with_identifiers=bool(pinned), identifier_projects=pinned)
        revealed = case_list.identifier_value_death_ids(
            user, [uuid.UUID(str(r["death_id"])) for r in page["cases"] if r.get("project_id") in pinned]
        ) if pinned else set()
        unreadable = None
        for row in page["cases"]:
            colmap = plan.columns.get(row.get("project_id"), {})
            for entry in row.get("identifiers", ()):
                if entry.get("code") in colmap and "value" not in entry and uuid.UUID(str(row["death_id"])) in revealed:
                    log.error("export: number of death %s (type %s) failed to decrypt", row["death_id"], entry.get("code"))
                    unreadable = (row["death_id"], entry.get("code"))
                    break
            if unreadable:
                break
        yield page, unreadable
        cursor = page["next_cursor"]
        db.session.rollback()  # read-only: hands the connection back until the next batch
        if not cursor or unreadable:
            return


def _first_unreadable(user: VaUsers, plan: ExportPlan):
    """Validation pass: decrypts every audited number batch by batch (nothing
    kept, nothing written) and returns the first unreadable one, else None."""
    if not plan.columns:
        return None
    for _, unreadable in _batches(user, plan):
        if unreadable is not None:
            return unreadable
    return None


def export_roles(user: VaUsers, project_ids) -> dict[str, str]:
    """``{project_id: role}`` for the projects among *project_ids* where *user*
    may export registration numbers (decision 9): ``admin`` everywhere
    (admin is a PII holder in the current code), else the live ASSIGNED
    ``data_manager``, ``project_pi`` or ``site_pi`` grant there, which is also
    the role the audit row names. Narrower than ``identifier_values_visible``
    (no supervisor, interviewer, reporter or ``collaborator_pii``)."""
    wanted = set(project_ids)
    resolved = resolve_grants(user)
    if resolved.is_admin:
        return {p: "admin" for p in wanted}
    held: dict[str, set[str]] = {}
    for g in resolved.grants:
        if not g.virtual and g.source == "assigned" and g.project_id in wanted:
            held.setdefault(g.project_id, set()).add(g.role.value)
    return {p: next(r for r in EXPORT_ROLES if r in roles) for p, roles in held.items() if roles & set(EXPORT_ROLES)}
