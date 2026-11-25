"""JSON error reply shared by the admin panel route modules."""

from flask import jsonify


def _json_error(message, status_code):
    return jsonify({"error": message}), status_code
