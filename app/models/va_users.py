import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db, login
from typing import Optional
from flask_login import UserMixin
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from werkzeug.security import generate_password_hash, check_password_hash


class VaUsers(UserMixin, db.Model):
    __tablename__ = "va_users"
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    email: so.Mapped[str] = so.mapped_column(
        sa.String(128), unique=True, nullable=False, index=True
    )
    password: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(256), nullable=False
    )
    vacode_language: so.Mapped[list[str]] = so.mapped_column(
        ARRAY(sa.String), nullable=False
    )
    vacode_formcount: so.Mapped[int] = so.mapped_column(
        sa.Integer, default=0, nullable=False
    )
    permission: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    landing_page: so.Mapped[str] = so.mapped_column(sa.String(255), nullable=False)
    pw_reset_t_and_c: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False, nullable=False)
    email_verified: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False, nullable=False)
    phone: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(15), nullable=True
    )
    other: so.Mapped[Optional[dict]] = so.mapped_column(JSONB, nullable=True)
    user_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    user_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    user_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"VA User -> {self.email} ({self.user_status}): {self.name}"

    def get_id(self) -> str:
        return str(self.user_id)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def is_coder(self, va_form=None):
        if "coder" not in self.permission:
            return False
        coder_va_form = set(self.permission["coder"])
        if va_form:
            return va_form in coder_va_form
        return bool(coder_va_form)

    def is_site_pi(self, va_form=None):
        if "sitepi" not in self.permission:
            return False
        site_pi_va_form = set(self.permission["sitepi"])
        if va_form:
            return va_form in site_pi_va_form
        return bool(site_pi_va_form)

    def is_reviewer(self, va_form=None):
        if "reviewer" not in self.permission:
            return False
        reviewer_va_form = set(self.permission["reviewer"])
        if va_form:
            return va_form in reviewer_va_form
        return bool(reviewer_va_form)

    def get_coder_va_forms(self):
        if "coder" not in self.permission:
            return set()
        return set(self.permission["coder"])

    def get_site_pi_va_forms(self):
        if "sitepi" not in self.permission:
            return set()
        return set(self.permission["sitepi"])

    def get_reviewer_va_forms(self):
        if "reviewer" not in self.permission:
            return set()
        return set(self.permission["reviewer"])

    def get_all_accessible_va_forms(self):
        all_va_forms = set()
        if self.permission:
            for role, va_forms in self.permission.items():
                all_va_forms.update(va_forms)
        return all_va_forms

    def has_va_form_access(self, va_form, role=None):
        if role:
            return role in self.permission and va_form in self.permission[role]
        for va_forms in self.permission.values():
            if va_form in va_forms:
                return True
        return False


@login.user_loader
def load_user(user_id: str):
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None
    return db.session.get(VaUsers, uid)