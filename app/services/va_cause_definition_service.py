"""WHO VA cause definitions: import, coder listing, ICD lookup, admin edits.

Table: mas_va_cause_definitions (app/models/mas_va_cause_definitions.py).
Policy: docs/policy/va-cause-definitions.md.

The source is docs/kb/WHO_VA_2022_Docs/va_definitions.html (a table of
section rows and code | title | definition rows). docs/ is not shipped in the
image, so `flask va-definitions generate-seed-json` freezes the parsed rows into
resource/va_cause_definitions_who_2022.json, which the migration and
`flask seed run` load.
"""

import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import nh3
import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd11Mms
from app.models.mas_va_cause_definitions import MasVaCauseDefinition
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.icd_coding_value import ICD_CLASSIFICATIONS, extract_icd_code
from app.utils.rich_text import sanitize_rich_text

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_HTML_PATH = _REPO_ROOT / "docs/kb/WHO_VA_2022_Docs/va_definitions.html"
DEFAULT_SEED_JSON_PATH = _REPO_ROOT / "resource/va_cause_definitions_who_2022.json"
DEFAULT_SOURCE = "WHO 2026 PCVA manual for physician reviewers"

# Cause codes only: VAs-NN.NN and VAs-99. Section headings (VAs-01 ...) are
# not codes, and the owner treats VAs-98 ("Other and unspecified
# non-communicable disease") as a group, so neither is a definition.
VA_CODE_RE = re.compile(r"^VAs-(\d{2}\.\d{2}|99)$")
TITLE_MAX_LEN = 500
DEFINITION_MAX_LEN = 20000

# ponytail: one fixed COD bucket scheme per classification links an ICD code
# to its VA cause; make it per project if projects ever differ in scheme.
VA_DEFINITION_SCHEMES = {"icd10": "WHO_2022_VA", "icd11": "WHO_2022_VA_2026"}


@dataclass
class ImportResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_edited: int = 0


def definition_text(definition_html: str) -> str:
    """Plain text of stored definition HTML, for search and the API."""
    if not definition_html:
        return ""
    spaced = definition_html.replace("<", " <")
    text = html.unescape(nh3.clean(spaced, tags=set()))
    return " ".join(text.split())


# ── HTML source parsing ─────────────────────────────────────────────────────

class _DefinitionTableParser(HTMLParser):
    """Collect the <td> cells of every table row.

    Cell content is rebuilt as HTML: tags keep no attributes, except that a
    ``<p class="note">`` becomes ``<p><em>`` (the italic NOTE style) because
    the rich-text allowlist carries no classes.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []  # [(tr_class, [inner_html, ...])]
        self._row = None
        self._cell = None  # list of html parts
        self._note_stack = []  # one bool per open <p>

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self._row = (attrs.get("class") or "", [])
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif self._cell is not None:
            is_note = tag == "p" and "note" in (attrs.get("class") or "").split()
            if tag == "p":
                self._note_stack.append(is_note)
            self._cell.append(f"<{tag}><em>" if is_note else f"<{tag}>")

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "td" and self._cell is not None:
            self._row[1].append("".join(self._cell).strip())
            self._cell = None
        elif self._cell is not None:
            is_note = tag == "p" and self._note_stack and self._note_stack.pop()
            self._cell.append(f"</em></{tag}>" if is_note else f"</{tag}>")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(html.escape(data, quote=False))


def parse_va_definitions_html(text: str, source: str = DEFAULT_SOURCE) -> list[dict]:
    """Cause rows for import from the WHO definitions table, in code order.

    Skipped: section rows (group headings), full-width note rows (group-level
    notes), and VAs-98. Raises ValueError when a three-cell row does not
    carry a VA code, rather than importing a partial table.
    """
    parser = _DefinitionTableParser()
    parser.feed(text)
    parser.close()

    rows: dict[str, dict] = {}
    for tr_class, cells in parser.rows:
        if "section" in tr_class.split() or len(cells) < 3:
            continue  # headings, notes, and the <th>-only header row
        code = definition_text(cells[0])
        if code == "VAs-98":
            continue
        if not VA_CODE_RE.match(code):
            raise ValueError(f"Unrecognised VA code {code!r}")
        if code in rows:
            raise ValueError(f"Duplicate VA code {code!r}")
        rows[code] = {
            "va_code": code,
            "title": definition_text(cells[1]),
            "definition_html": sanitize_rich_text(cells[2]),
            "source": source,
        }
    if not rows:
        raise ValueError("No VA codes found in the definitions table.")
    return [rows[code] for code in sorted(rows)]


def load_seed_rows(path: Path | str = DEFAULT_SEED_JSON_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_seed_json(rows: list[dict], path: Path | str = DEFAULT_SEED_JSON_PATH) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=1)
        handle.write("\n")


# ── Import ──────────────────────────────────────────────────────────────────

_IMPORTED_FIELDS = ("title", "definition_html", "source")


def import_va_definitions(rows: list[dict], *, force: bool = False) -> ImportResult:
    """Upsert ``rows`` by va_code and commit.

    A row an admin has edited (``updated_by`` set) is left alone unless
    ``force``; forcing clears ``updated_by`` so the row is back in sync with
    the source. Rows missing from ``rows`` are never deleted or deactivated.
    """
    existing = {
        row.va_code: row for row in db.session.scalars(sa.select(MasVaCauseDefinition))
    }
    result = ImportResult()
    for data in rows:
        values = {field: data[field] for field in _IMPORTED_FIELDS}
        values["definition_html"] = sanitize_rich_text(values["definition_html"])
        row = existing.get(data["va_code"])
        if row is None:
            db.session.add(MasVaCauseDefinition(va_code=data["va_code"], **values))
            result.inserted += 1
            continue
        if row.updated_by is not None and not force:
            result.skipped_edited += 1
            continue
        if all(getattr(row, f) == v for f, v in values.items()) and row.updated_by is None:
            result.unchanged += 1
            continue
        for field, value in values.items():
            setattr(row, field, value)
        row.updated_by = None
        result.updated += 1
    db.session.commit()
    return result


# ── Reads ───────────────────────────────────────────────────────────────────

def _row_dict(row: MasVaCauseDefinition) -> dict:
    return {
        "id": str(row.id),
        "va_code": row.va_code,
        "title": row.title,
        "definition_html": row.definition_html,
        "is_active": row.is_active,
        "source": row.source,
        "edited": row.updated_by is not None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _ordered_rows(active_only: bool):
    # ponytail: whole-table read; a curated master of ~63 rows. Add paging if
    # it ever grows past a few hundred.
    stmt = sa.select(MasVaCauseDefinition).order_by(MasVaCauseDefinition.va_code)
    if active_only:
        stmt = stmt.where(MasVaCauseDefinition.is_active.is_(True))
    return db.session.scalars(stmt).all()


def list_admin_va_definitions() -> list[dict]:
    """Every row, inactive included, in code order (admin panel)."""
    return [_row_dict(row) for row in _ordered_rows(active_only=False)]


def list_coder_va_definitions(query: str | None = None) -> dict:
    """Active rows in code order for the coder modal and help page; one query.

    ``query`` matches case-insensitively on code, title and definition text.
    """
    needle = " ".join((query or "").lower().split())
    definitions = []
    for row in _ordered_rows(active_only=True):
        text = definition_text(row.definition_html)
        if needle and needle not in f"{row.va_code} {row.title} {text}".lower():
            continue
        definitions.append({
            "va_code": row.va_code,
            "title": row.title,
            "definition_html": row.definition_html,
            "definition_text": text,
        })
    return {"definitions": definitions, "total": len(definitions)}


def _icd_candidates(code: str, classification: str) -> list[str]:
    """``code`` then its ancestors, most specific first (upper-case).

    ICD-10: the three-character category (A04.0 -> A04). ICD-11: the parent
    chain in mas_icd11_mms (one recursive query).
    """
    if classification == "icd10":
        return [code] if len(code) <= 3 else [code, code[:3]]
    start = (
        sa.select(MasIcd11Mms.code, MasIcd11Mms.parent_linearization_uri, sa.literal(0).label("depth"))
        .where(MasIcd11Mms.release == DEFAULT_ICD11_RELEASE, sa.func.upper(MasIcd11Mms.code) == code)
        .cte("icd11_chain", recursive=True)
    )
    parent = aliased(MasIcd11Mms)
    chain = start.union_all(
        sa.select(parent.code, parent.parent_linearization_uri, start.c.depth + 1).where(
            parent.release == DEFAULT_ICD11_RELEASE,
            parent.linearization_uri == start.c.parent_linearization_uri,
        )
    )
    ancestors = db.session.execute(
        sa.select(chain.c.code).where(chain.c.code.is_not(None)).order_by(chain.c.depth)
    ).scalars().all()
    return [c.upper() for c in ancestors] or [code]


def find_va_definition_for_icd(value: str | None, classification: str | None = None) -> dict | None:
    """Active VA cause definition for an ICD code, or None.

    ``value`` may be a bare code or a stored coding value ("A04.0-Other
    bacterial ..."). Without ``classification`` the code shape decides (ICD-10
    and ICD-11 code shapes do not overlap). The code, then its ancestors, is
    looked up in the classification's scheme in VA_DEFINITION_SCHEMES; a
    bucket node ``vas_01_02`` is VA cause ``VAs-01.02``. Nodes that are not
    ``vas_*`` causes have no definition.
    """
    classifications = [classification] if classification else list(ICD_CLASSIFICATIONS)
    for cls in classifications:
        code = extract_icd_code(value, cls)
        if code:
            break
    else:
        return None

    candidates = _icd_candidates(code, cls)
    va_code_expr = sa.literal("VAs-") + sa.func.replace(sa.func.substr(MasCodBucketNode.node_code, 5), "_", ".")
    matches = db.session.execute(
        sa.select(sa.func.upper(MapIcdCodBucket.icd_code), MasVaCauseDefinition)
        .join(MasCodBucketScheme, MasCodBucketScheme.scheme_id == MapIcdCodBucket.scheme_id)
        .join(MasCodBucketNode, MasCodBucketNode.node_id == MapIcdCodBucket.node_id)
        .join(MasVaCauseDefinition, MasVaCauseDefinition.va_code == va_code_expr)
        .where(
            MasCodBucketScheme.scheme_code == VA_DEFINITION_SCHEMES[cls],
            MapIcdCodBucket.icd_classification == cls,
            MapIcdCodBucket.is_active.is_(True),
            sa.func.upper(MapIcdCodBucket.icd_code).in_(candidates),
            MasCodBucketNode.node_code.like("vas\\_%", escape="\\"),
            MasVaCauseDefinition.is_active.is_(True),
        )
    ).all()
    if not matches:
        return None
    # ponytail: if a code maps to different causes per age scope, the first
    # row wins; pass the deceased's age scope if schemes ever split that way.
    _, row = min(matches, key=lambda m: candidates.index(m[0]))
    return {
        "icd_code": code,
        "classification": cls,
        "va_code": row.va_code,
        "title": row.title,
        "definition_html": row.definition_html,
    }


# ── Admin writes ────────────────────────────────────────────────────────────

def _clean_title(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("title is required.")
    title = " ".join(value.split())
    if len(title) > TITLE_MAX_LEN:
        raise ValueError(f"title must be at most {TITLE_MAX_LEN} characters.")
    return title


def _clean_definition(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("definition_html must be a string.")
    if len(value) > DEFINITION_MAX_LEN:
        raise ValueError(f"definition_html must be at most {DEFINITION_MAX_LEN} characters.")
    return sanitize_rich_text(value)


def create_va_definition(data: dict, *, user_id) -> dict:
    """Add a VA cause code; raises ValueError on invalid or duplicate input."""
    va_code = data.get("va_code").strip() if isinstance(data.get("va_code"), str) else ""
    if not VA_CODE_RE.match(va_code):
        raise ValueError("va_code must look like VAs-NN.NN (or VAs-99).")
    title = _clean_title(data.get("title"))
    definition = _clean_definition(data.get("definition_html"))
    if db.session.scalar(
        sa.select(MasVaCauseDefinition.id).where(MasVaCauseDefinition.va_code == va_code)
    ):
        raise ValueError(f"{va_code} already exists.")
    row = MasVaCauseDefinition(
        va_code=va_code,
        title=title,
        definition_html=definition,
        is_active=True,
        source="DigitVA admin",
        updated_by=user_id,
    )
    db.session.add(row)
    db.session.commit()
    return _row_dict(row)


def update_va_definition(definition_id, data: dict, *, user_id) -> tuple[dict, list[str]]:
    """Apply title / definition_html / is_active; returns (row, changed fields).

    Raises LookupError for an unknown id, ValueError for invalid input.
    """
    row = db.session.get(MasVaCauseDefinition, definition_id)
    if row is None:
        raise LookupError(definition_id)
    changes = {}
    if "title" in data:
        changes["title"] = _clean_title(data["title"])
    if "definition_html" in data:
        changes["definition_html"] = _clean_definition(data["definition_html"])
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ValueError("is_active must be true or false.")
        changes["is_active"] = data["is_active"]
    if not changes:
        raise ValueError("Nothing to update.")
    changed = [f for f, v in changes.items() if getattr(row, f) != v]
    for field, value in changes.items():
        setattr(row, field, value)
    if changed:
        row.updated_by = user_id
    db.session.commit()
    return _row_dict(row), changed
