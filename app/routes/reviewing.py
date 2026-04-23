"""Compatibility shim for the relocated reviewing routes module."""

import sys

from app.routes.workflow import reviewing as _impl

sys.modules[__name__] = _impl
