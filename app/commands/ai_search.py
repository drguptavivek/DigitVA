"""`flask ai-search` — the Typesense suggestions index.

See docs/policy/ai-analytics-questions.md ("Suggestions").
"""

import click

from app.services.ai_search_service import reindex_all


@click.group("ai-search")
def ai_search_group():
    """Suggestions search commands."""


@ai_search_group.command("reindex")
def reindex_command() -> None:
    """Rebuild the help, VA definition and catalog documents in Typesense."""
    try:
        count = reindex_all()
    except Exception as exc:  # noqa: BLE001 - report without the request detail
        raise click.ClickException(f"Reindex failed: {type(exc).__name__}") from exc
    click.echo(f"Indexed {count} documents")


def init_app(app):
    app.cli.add_command(ai_search_group)
