"""Compatibility shim for relocated error handlers."""

import sys

from app.http import errors as _impl

sys.modules[__name__] = _impl
