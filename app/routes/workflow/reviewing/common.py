"""Shared objects for reviewing workflow routes."""

import sys

from flask import Blueprint

reviewing = Blueprint("reviewing", __name__)


def render_va_coding_page_for_route(*args, **kwargs):
    route_module = sys.modules.get("app.routes.reviewing") or sys.modules[
        "app.routes.workflow.reviewing"
    ]
    return route_module.render_va_coding_page(*args, **kwargs)
