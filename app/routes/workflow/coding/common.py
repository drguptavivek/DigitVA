"""Shared objects for coding workflow routes."""

from flask import Blueprint

from app.services.coding.coder_workflow import AllocationError
from app.authz.legacy_guards.abort_with_flash import (
    va_permission_abortwithflash,
)

coding = Blueprint("coding", __name__)


def handle_allocation_error(error: AllocationError):
    va_permission_abortwithflash(error.message, error.status_code)
