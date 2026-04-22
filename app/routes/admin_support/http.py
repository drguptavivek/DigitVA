import re

from flask import jsonify


def json_error(message, status_code):
    return jsonify({"error": message}), status_code


def validate_entity_id(entity_id, length, name="ID"):
    if not entity_id or len(entity_id) != length:
        return f"{name} must be exactly {length} characters."
    if not re.match(r"^[A-Z0-9]+$", entity_id):
        return f"{name} must contain only uppercase letters and digits."
    return None
