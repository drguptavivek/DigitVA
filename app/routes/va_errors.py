"""Compatibility shim for the relocated error handlers module."""

import sys

from app.routes import errors as _impl

sys.modules[__name__] = _impl
