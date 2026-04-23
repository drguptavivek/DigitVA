"""Compatibility shim for the relocated form workflow routes module."""

import sys

from app.routes.workflow import forms as _impl

sys.modules[__name__] = _impl
