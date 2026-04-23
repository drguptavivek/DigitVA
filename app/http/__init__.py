"""HTTP-layer helpers and application handlers."""

from .errors import register_error_handlers
from .responses import json_error, validate_entity_id

__all__ = [
    "json_error",
    "register_error_handlers",
    "validate_entity_id",
]
