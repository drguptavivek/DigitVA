"""Shared objects for coding workflow routes."""

from flask import Blueprint

from app.services.coder_workflow_service import AllocationError
from app.utils import va_permission_abortwithflash

coding = Blueprint("coding", __name__)


def handle_allocation_error(error: AllocationError):
    va_permission_abortwithflash(error.message, error.status_code)
