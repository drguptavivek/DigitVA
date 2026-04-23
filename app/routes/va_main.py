"""Compatibility shim for the relocated public routes module."""

import sys

from app.routes import home as _impl

sys.modules[__name__] = _impl
