from flask import render_template
from app import db

def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("va_errors/va_403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("va_errors/va_404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("va_errors/va_500.html"), 500