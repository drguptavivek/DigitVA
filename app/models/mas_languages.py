import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db


class MasLanguages(db.Model):
    """Canonical language list for the application."""

    __tablename__ = "mas_languages"

    language_code: so.Mapped[str] = so.mapped_column(
        sa.String(32), primary_key=True
    )
    language_name: so.Mapped[str] = so.mapped_column(
        sa.String(64), nullable=False
    )
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, default=True, nullable=False
    )

    aliases: so.Mapped[list["MapLanguageAliases"]] = so.relationship(
        back_populates="language", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Language({self.language_code}: {self.language_name})"


class MapLanguageAliases(db.Model):
    """Maps raw ODK language values to canonical language codes."""

    __tablename__ = "map_language_aliases"

    alias: so.Mapped[str] = so.mapped_column(
        sa.String(64), primary_key=True
    )
    language_code: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        sa.ForeignKey("mas_languages.language_code"),
        nullable=False,
        index=True,
    )

    language: so.Mapped["MasLanguages"] = so.relationship(
        back_populates="aliases"
    )

    def __repr__(self) -> str:
        return f"Alias({self.alias} -> {self.language_code})"
