"""The KPI registry: ``app/data/kpi_registry.json``, one entry per KPI id.

docs/policy/kpis.md ("KPI registry and MCP access") is the specification and
``tests/services/test_kpi_registry.py`` checks the two against each other.
Stdlib only, loaded like the AI question catalog (``ai_analytics_catalog``):
read once, cached, reread when the file changes. An absent or invalid file is
an error here (``RegistryError``), not an empty registry, because the help
page and the search index are built from it.
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "kpi_registry.json"

STAGES = ("input", "process", "output", "outcome")
CATEGORIES = (
    "workforce", "flow", "timeliness", "coding quality", "system", "loop",
    "coverage", "data quality", "equity", "cause mix",
)
TYPES = (
    "rate", "volume", "duration", "gap", "net", "aged volume",
    "distribution", "matrix", "roster",
)
LEVELS = ("Pj", "St", "Dt", "Bk", "Fu", "Sys")
AUDIENCES = ("DM", "admin", "IC")
CADENCES = ("snapshot", "daily", "weekly", "monthly", "on demand")
TIERS = ("core", "registered", "merged", "retired")
VIEWS = ("status", "trend", "forecast", "blocker", "critical_path")
MCP_MODES = ("full", "totals_only", "none")
DIRECTIONS = ("higher_is_better", "lower_is_better", "informational", "band", "target")

# Fields every entry carries (null where the policy does not say).
FIELDS = (
    "id", "name", "question", "stage", "category", "type", "level", "audience",
    "cadence", "tier", "merged_into", "retired_reason", "views", "definition",
    "helper", "unit", "direction", "thresholds", "peer", "min_whole", "cell_min",
    "periods", "dimensions", "sources", "replaces", "mcp", "catalog_key",
    "policy_anchor", "decisions",
)
# Optional field: "pending" marks a core/registered KPI whose compute function is
# not written yet (helper is then null).
HELPER_STATUSES = ("pending",)
_LISTS = ("level", "audience", "views", "periods", "dimensions", "sources", "replaces", "decisions")


class RegistryError(ValueError):
    """The registry file does not satisfy its schema."""


def _check(entry: dict) -> list[str]:
    kid = entry.get("id", "?")
    problems = []

    def bad(msg):
        problems.append(f"{kid}: {msg}")

    for field in FIELDS:
        if field not in entry:
            bad(f"missing field {field}")
    if problems:
        return problems
    for field in ("id", "name", "policy_anchor"):
        if not isinstance(entry[field], str) or not entry[field].strip():
            bad(f"{field} must be a non-empty string")
    if entry["tier"] not in TIERS:
        bad(f"tier {entry['tier']!r}")
    for field in _LISTS:
        if entry[field] is not None and not (
            isinstance(entry[field], list) and all(isinstance(x, str) for x in entry[field])
        ):
            bad(f"{field} must be a list of strings or null")
    for field, allowed in (
        ("stage", STAGES), ("category", CATEGORIES), ("type", TYPES), ("cadence", CADENCES),
        ("mcp", MCP_MODES), ("direction", DIRECTIONS),
    ):
        if entry[field] is not None and entry[field] not in allowed:
            bad(f"{field} {entry[field]!r} not in {allowed}")
    for field, allowed in (("level", LEVELS), ("audience", AUDIENCES), ("views", VIEWS)):
        for value in entry[field] or ():
            if value not in allowed:
                bad(f"{field} {value!r} not in {allowed}")
    for field in ("min_whole", "cell_min"):
        if entry[field] is not None and not (isinstance(entry[field], int) and entry[field] > 0):
            bad(f"{field} must be a positive integer or null")
    if entry["peer"] is not None and not isinstance(entry["peer"], bool):
        bad("peer must be a boolean or null")
    if entry["thresholds"] is not None and not isinstance(entry["thresholds"], dict):
        bad("thresholds must be an object or null")
    definition = entry["definition"]
    if definition is not None and not (
        isinstance(definition, dict) and isinstance(definition.get("measure"), str)
        and isinstance(definition.get("canonical"), list)
    ):
        bad("definition needs measure and canonical[]")
    if entry["helper"] is not None and not (isinstance(entry["helper"], str) and entry["helper"].count(":") == 1):
        bad("helper must be 'module:function'")
    status = entry.get("helper_status")
    if status is not None and status not in HELPER_STATUSES:
        bad(f"helper_status {status!r} not in {HELPER_STATUSES}")
    if status == "pending" and entry["helper"] is not None:
        bad("helper_status pending needs helper null")

    tier = entry["tier"]
    if tier in ("core", "registered"):
        for field in ("question", "stage", "category", "type", "cadence", "mcp", "definition", "level", "audience", "views"):
            if not entry[field]:
                bad(f"{tier} entry needs {field}")
    if tier == "merged" and not entry["merged_into"]:
        bad("merged entry needs merged_into")
    if tier == "retired" and not entry["retired_reason"]:
        bad("retired entry needs retired_reason")
    if tier != "merged" and entry["merged_into"]:
        bad("merged_into only on a merged entry")
    return problems


def validate(entries) -> None:
    """Raise ``RegistryError`` listing every schema problem in *entries*."""
    if not isinstance(entries, list):
        raise RegistryError("kpis must be a list")
    problems = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append(f"entry is not an object: {entry!r}")
            continue
        if entry.get("id") in seen:
            problems.append(f"{entry.get('id')}: duplicate id")
        seen.add(entry.get("id"))
        problems += _check(entry)
    for entry in entries:
        if isinstance(entry, dict) and entry.get("merged_into") and entry["merged_into"] not in seen:
            problems.append(f"{entry['id']}: merged_into {entry['merged_into']} does not exist")
    if problems:
        raise RegistryError("; ".join(problems))


_cache: dict = {"mtime": None, "entries": []}


def load_registry() -> list[dict]:
    """All entries in policy order (a shared list: treat it as read-only)."""
    try:
        mtime = REGISTRY_PATH.stat().st_mtime
    except OSError as exc:
        raise RegistryError(f"KPI registry missing: {REGISTRY_PATH}") from exc
    if _cache["mtime"] != mtime:
        try:
            raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RegistryError(f"KPI registry unreadable: {exc}") from exc
        entries = raw.get("kpis") if isinstance(raw, dict) else None
        validate(entries)
        _cache.update(mtime=mtime, entries=entries)
    return _cache["entries"]


def get_kpi(kpi_id) -> dict | None:
    if not isinstance(kpi_id, str):
        return None
    return next((e for e in load_registry() if e["id"] == kpi_id), None)


def list_kpis(*, stage=None, category=None, level=None, audience=None, tier=None, views=None) -> list[dict]:
    """Entries matching every filter given. ``level``, ``audience`` and
    ``views`` match when the entry's list contains the value."""
    def keep(e):
        return (
            (stage is None or e["stage"] == stage)
            and (category is None or e["category"] == category)
            and (tier is None or e["tier"] == tier)
            and (level is None or level in (e["level"] or ()))
            and (audience is None or audience in (e["audience"] or ()))
            and (views is None or views in (e["views"] or ()))
        )

    return [e for e in load_registry() if keep(e)]


def grouped_for_display() -> list[tuple[str, list[tuple[str, list[dict]]]]]:
    """Core and registered entries as ``[(stage, [(category, [entry])])]``,
    stages in results-chain order, categories and entries in policy order."""
    out = []
    for stage in STAGES:
        categories: dict[str, list[dict]] = {}
        for e in load_registry():
            if e["stage"] == stage and e["tier"] in ("core", "registered"):
                categories.setdefault(e["category"], []).append(e)
        if categories:
            out.append((stage, list(categories.items())))
    return out
