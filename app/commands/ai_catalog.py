"""`flask ai-catalog generate` — ask a model for the AI question catalog.

docs/policy/ai-analytics-questions.md ("Question catalog"). Sends only the
fixed system instruction and a fixed request for questions (no data). Every
answer is checked with the SQL parser and ``EXPLAIN`` as
``digitva_ai_reader`` over the chosen admin's ``ai_cube``; failures are
dropped. Writes ``app/data/ai_question_catalog.json`` and
``docs/kb/ai-question-catalog.md`` for review and commit.
"""

import json

import click
import sqlalchemy as sa

from app import db
from app.services import ai_analytics_catalog as catalog
from app.services import ai_analytics_planner as planner
from app.services import ai_analytics_providers as providers
from app.services.ai_analytics_sandbox import SandboxError, explain_query

BATCH_SIZE = 20
MAX_TOKENS = 16000
THEMES = (
    "the coding workflow, intake and narrative quality",
    "causes of death: WHO 2026 VA cause sections, causes and ICD codes, by age band and sex",
    "monthly and site trends, and SmartVA top cause vs final cause agreement",
)
GENERATE_REQUEST = (
    "List {count} distinct questions a data manager commonly asks about this aggregate VA data, "
    "about {theme}. For each give: key (unique snake_case, at most 40 characters), question "
    "(how a user would type it), description (one sentence), keywords (3 to 6 words), sql and "
    "chart, following every rule above."
)
CATALOG_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "question": {"type": "string"},
                    "description": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "sql": {"type": "string"},
                    "chart": planner.CHART_SCHEMA,
                },
                "required": ["key", "question", "description", "keywords", "sql", "chart"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def _admin(email):
    """The admin with *email*, else the first active global admin by email."""
    from app.models import (
        VaAccessRoles,
        VaAccessScopeTypes,
        VaStatuses,
        VaUserAccessGrants,
        VaUsers,
    )

    query = sa.select(VaUsers).where(sa.exists().where(
        VaUserAccessGrants.user_id == VaUsers.user_id,
        VaUserAccessGrants.role == VaAccessRoles.admin,
        VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
        VaUserAccessGrants.grant_status == VaStatuses.active,
    ))
    if email:
        query = query.where(sa.func.lower(VaUsers.email) == email.strip().lower())
    user = db.session.scalar(query.order_by(VaUsers.email).limit(1))
    if user is None:
        raise click.ClickException("No admin user found; pass --as with an admin's email.")
    return user


def _checked(raw, user, seen: set) -> dict | None:
    """The entry if it is well formed, new and passes the parser and EXPLAIN."""
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip().lower()
    entry = {
        "key": key,
        "question": str(raw.get("question") or "").strip()[:200],
        "description": str(raw.get("description") or "").strip()[:500],
        "keywords": [str(k).strip()[:40] for k in raw.get("keywords") or [] if str(k).strip()][:6],
        "sql": str(raw.get("sql") or "").strip(),
    }
    try:
        entry["chart"] = planner.parse_chart(raw.get("chart"))
    except planner.AiQuestionsError:
        return None
    if not catalog.KEY_PATTERN.match(key) or key in seen or not entry["question"]:
        return None
    try:
        explain_query(entry["sql"], user)
    except SandboxError as exc:
        click.echo(f"  dropped {key}: {exc.message}")
        return None
    seen.add(key)
    return entry


@click.group("ai-catalog")
def ai_catalog_group():
    """AI question catalog commands."""


@ai_catalog_group.command("generate")
@click.option("--provider", type=click.Choice(providers.PROVIDERS), default=None,
              help="An enabled provider; default: the first enabled.")
@click.option("--count", default=60, show_default=True, type=click.IntRange(5, 120))
@click.option("--as", "email", default=None, help="Admin whose ai_cube the EXPLAIN uses.")
def generate_command(provider, count, email) -> None:
    """Ask the model for about COUNT questions, keep those that pass, write the catalog."""
    try:
        provider = planner._resolve_provider(provider)
    except planner.AiQuestionsError as exc:
        raise click.ClickException(exc.message) from None
    user = _admin(email)
    per_theme = max(count // len(THEMES), 1)
    entries, seen = [], set()
    for theme in THEMES:
        for start in range(0, per_theme, BATCH_SIZE):
            size = min(BATCH_SIZE, per_theme - start)
            click.echo(f"Asking {provider} for {size} questions on {theme}")
            prompt = GENERATE_REQUEST.format(count=size, theme=theme)
            try:
                reply = providers.plan(provider, planner.SYSTEM_INSTRUCTION, prompt, CATALOG_SCHEMA,
                                       max_tokens=MAX_TOKENS)
                questions = json.loads(reply.text).get("questions") or []
            except providers.ProviderError as exc:
                raise click.ClickException(exc.message) from None
            except Exception as exc:  # noqa: BLE001 - report the SDK failure by type only
                raise click.ClickException(f"The model call failed: {type(exc).__name__}") from exc
            entries += [e for e in (_checked(q, user, seen) for q in questions) if e]
    if not entries:
        raise click.ClickException("No question passed the checks; the catalog was not changed.")
    catalog.write_catalog(entries, source=f"flask ai-catalog generate ({providers.model_name(provider)})")
    click.echo(f"Wrote {len(entries)} questions to {catalog.CATALOG_PATH.name} and {catalog.CATALOG_DOC_PATH.name}")


def init_app(app):
    app.cli.add_command(ai_catalog_group)
