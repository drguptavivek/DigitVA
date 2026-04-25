from flask import Blueprint

admin = Blueprint("admin", __name__)


from app.routes.admin_sections import register_admin_sections  # noqa: E402

register_admin_sections()

__all__ = ["admin"]
