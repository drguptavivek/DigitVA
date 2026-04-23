"""Compatibility shim for the relocated data-management routes module."""

import sys

from app.routes.operations import data_management as _impl

sys.modules[__name__] = _impl
