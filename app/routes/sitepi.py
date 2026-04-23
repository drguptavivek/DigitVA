"""Compatibility shim for the relocated site PI routes module."""

import sys

from app.routes.operations import sitepi as _impl

sys.modules[__name__] = _impl
