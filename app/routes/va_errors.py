from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError
from flask_limiter.errors import RateLimitExceeded
from app import db

def register_error_handlers(app):
    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if request.path.startswith(("/api/", "/admin/api/")):
            return jsonify({"error": error.description, "code": "csrf_failed"}), 400
        return render_template("va_errors/va_403.html"), 400

    @app.errorhandler(403)
    def forbidden_error(error):
        if request.path.startswith("/api/v1/"):
            return jsonify({"error": error.description or "Forbidden.", "code": "forbidden"}), 403
        return render_template("va_errors/va_403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error):
        if request.path.startswith("/api/v1/"):
            return jsonify({"error": "Not found.", "code": "not_found"}), 404
        return render_template("va_errors/va_404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.path.startswith("/api/v1/"):
            return jsonify({"error": "Internal server error.", "code": "server_error"}), 500
        return render_template("va_errors/va_500.html"), 500

    @app.errorhandler(RateLimitExceeded)
    @app.errorhandler(429)
    def rate_limited_error(error):
        message = (
            "Too many requests in a short time. Please wait 5 minutes and try again."
        )
        if request.path.startswith(("/api/", "/admin/api/", "/data-management/api/")):
            return jsonify({"error": message, "code": "rate_limited"}), 429

        flash(message, "warning")
        return redirect(request.referrer or url_for("coding.dashboard"))
