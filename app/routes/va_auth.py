"""Compatibility shim for the relocated auth routes module."""

import sys

from app.routes import auth as _impl

sys.modules[__name__] = _impl
