"""Compatibility shim for the relocated coding routes module."""

import sys

from app.routes.workflow import coding as _impl

sys.modules[__name__] = _impl
