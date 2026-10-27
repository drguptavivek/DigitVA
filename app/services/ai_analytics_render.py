"""Draw an ``ai_cube`` result: Chart.js config, table and KPI numbers.

Deterministic, no model call: the same rows and recipe always give the same
output, for a fresh answer and a saved-query rerun alike. Values are passed
as data (the template emits the config with ``tojson``; Chart.js draws text
on a canvas), never as markup.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

MAX_KPIS = 4
REFERENCE_COLOR = "#111827"

_PALETTE = (
    "#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2",
    "#db2777", "#65a30d", "#ea580c", "#4b5563", "#0d9488", "#9333ea",
)


def _label(value) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _reference(columns, chart) -> str | None:
    """The comparison chart's peer or target column, when the result has it."""
    ref = chart.get("reference_column")
    return ref if chart.get("type") == "comparison" and ref in columns else None


def _series(columns, rows, chart) -> list[str]:
    """Numeric columns to draw: the recipe's, if present, else every numeric
    one; never the comparison's reference column."""
    ref = _reference(columns, chart)
    wanted = [c for c in chart.get("series_columns") or [] if c in columns and c != ref]
    if not wanted and chart.get("value_column") in columns and chart["value_column"] != ref:
        wanted = [chart["value_column"]]
    if not wanted:
        x = chart.get("x_column")
        wanted = [
            c for c in columns
            if c not in (x, ref) and rows and all(_number(r.get(c)) is not None or r.get(c) is None for r in rows)
            and any(_number(r.get(c)) is not None for r in rows)
        ]
    return wanted


def _chart_config(columns, rows, chart, series) -> dict | None:
    kind = chart.get("type")
    x = chart.get("x_column")
    if kind == "table" or not rows or not series:
        return None
    if x not in columns:
        x = next((c for c in columns if c not in series), None)
        if x is None:
            return None
    labels = [_label(r.get(x)) for r in rows]
    if kind == "doughnut":
        datasets = [{
            "label": series[0],
            "data": [_number(r.get(series[0])) for r in rows],
            "backgroundColor": [_PALETTE[i % len(_PALETTE)] for i in range(len(rows))],
        }]
    else:
        datasets = [
            {
                "label": col,
                "data": [_number(r.get(col)) for r in rows],
                "backgroundColor": _PALETTE[i % len(_PALETTE)],
                "borderColor": _PALETTE[i % len(_PALETTE)],
            }
            for i, col in enumerate(series)
        ]
    ref = _reference(columns, chart)
    if kind == "comparison" and ref:
        # Grouped bars with the peer or target value as a line over them.
        datasets.append({
            "type": "line",
            "label": ref,
            "data": [_number(r.get(ref)) for r in rows],
            "borderColor": REFERENCE_COLOR,
            "backgroundColor": REFERENCE_COLOR,
            "borderDash": [6, 4],
            "pointRadius": 0,
            "fill": False,
            "order": 0,
        })
    options = {"responsive": True, "maintainAspectRatio": False, "animation": False}
    if kind == "stacked_bar":
        options["scales"] = {"x": {"stacked": True}, "y": {"stacked": True}}
    if kind == "horizontal_bar":
        options["indexAxis"] = "y"
    return {
        "type": {"line": "line", "doughnut": "doughnut"}.get(kind, "bar"),
        "data": {"labels": labels, "datasets": datasets},
        "options": options,
    }


def _kpis(columns, rows, chart, series) -> list[dict]:
    """Total of the first series, then its top categories."""
    if not rows or not series:
        return []
    value_col = series[0]
    x = chart.get("x_column") if chart.get("x_column") in columns else None
    values = [(r, _number(r.get(value_col))) for r in rows]
    values = [(r, v) for r, v in values if v is not None]
    if not values:
        return []
    total = sum(v for _, v in values)
    kpis = [{"label": f"Total {value_col}", "value": total}]
    if x and len(values) > 1:
        top = sorted(values, key=lambda item: item[1], reverse=True)[: MAX_KPIS - 1]
        kpis += [{"label": _label(r.get(x)), "value": v} for r, v in top]
    return kpis


def _drill(columns, rows, chart, config) -> dict | None:
    """The breakdown-drawer hook: the ai_cube column of the x axis and each
    row's category label, as drawn on the chart; None without one."""
    dimension = chart.get("x_dimension")
    x = chart.get("x_column")
    if config is None or not dimension or x not in columns:
        return None
    return {"column": dimension, "values": [_label(r.get(x)) for r in rows]}


def render(columns: list[str], rows: list[dict], chart: dict) -> dict:
    """Return {"chart": Chart.js config or None, "table": {...}, "kpis": [...],
    "drill": {"column", "values"} or None}."""
    series = _series(columns, rows, chart)
    config = _chart_config(columns, rows, chart, series)
    return {
        "chart": config,
        "table": {
            "columns": columns,
            "rows": [[_label(r.get(c)) if r.get(c) is not None else "" for c in columns] for r in rows],
        },
        "kpis": _kpis(columns, rows, chart, series),
        "drill": _drill(columns, rows, chart, config),
    }
