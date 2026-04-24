"""Compatibility shim for the relocated VA form routes package."""

import sys

from app.routes import forms as _impl

sys.modules[__name__] = _impl
