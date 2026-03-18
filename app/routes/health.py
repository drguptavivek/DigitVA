from flask import Blueprint, jsonify
from app import limiter

health = Blueprint("health", __name__)


@health.get("/health")
@limiter.exempt
def health_check():
    return jsonify({"status": "healthy"}), 200
