"""Compatibility shim for the relocated error handlers module."""

import sys

from app.http import errors as _impl

sys.modules[__name__] = _impl
