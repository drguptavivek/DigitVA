"""Coding workflow routes package."""

from app.services.coding.coder_workflow import AllocationError, AllocationResult
from app.services.rendering.coding_page import render_va_coding_page

from .actions import demo, pick, recode, resume, start, view_submission
from .common import coding, handle_allocation_error
from .dashboard import dashboard

_handle_allocation_error = handle_allocation_error

__all__ = [
    "AllocationError",
    "AllocationResult",
    "_handle_allocation_error",
    "coding",
    "dashboard",
    "demo",
    "pick",
    "recode",
    "render_va_coding_page",
    "resume",
    "start",
    "view_submission",
]
