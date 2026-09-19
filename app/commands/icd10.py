import click

from app.services.icd10_2019_2_service import (
    DEFAULT_ICD10_2019_2_CSV_PATH,
    get_icd10_2019_2_stats,
    import_icd10_2019_2_from_csv,
    import_icd10_2019_2_policy_json,
)


@click.group("icd10")
def icd10_group():
    """ICD-10 master-data commands."""


@icd10_group.command("import-2019-2")
@click.option("--csv-path", default=str(DEFAULT_ICD10_2019_2_CSV_PATH), show_default=True)
@click.option(
    "--apply-policy-columns",
    is_flag=True,
    default=False,
    help="Also update policy columns from the CSV instead of preserving existing DB values.",
)
def import_2019_2(csv_path: str, apply_policy_columns: bool) -> None:
    result = import_icd10_2019_2_from_csv(
        csv_path=csv_path,
        apply_policy_columns=apply_policy_columns,
    )
    click.echo(
        "Imported mas_icd10_2019_2 "
        f"rows={result.total_rows} inserted={result.inserted} "
        f"updated={result.updated} deactivated={result.deactivated}"
    )


@icd10_group.command("stats-2019-2")
def stats_2019_2() -> None:
    stats = get_icd10_2019_2_stats()
    click.echo(
        "\n".join(
            [
                f"total_rows={stats['total_rows']}",
                f"active_rows={stats['active_rows']}",
                f"chapters={stats['chapters']}",
                f"blocks={stats['blocks']}",
                f"three_character_rows={stats['three_character_rows']}",
                f"detailed_rows={stats['detailed_rows']}",
            ]
        )
    )


@icd10_group.command("policy-import")
@click.option("--path", required=True, help="Path to a policy import JSON file.")
def policy_import(path: str) -> None:
    """Full-replacement import of mas_icd10_2019_2 coding-selectability policy.

    This is a global, table-wide change: it affects ICD-10 coding-search
    selectability for every project the moment it runs.
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = f.read()
    result = import_icd10_2019_2_policy_json(payload)
    click.echo(
        "Imported ICD-10 coding-selectability policy "
        f"total_items={result.total_items} updated_items={result.updated_items} "
        f"reset_items={result.reset_items} skipped_items={len(result.skipped_items)}"
    )
    for skipped in result.skipped_items:
        click.echo(f"  skipped: {skipped}")


def init_app(app):
    app.cli.add_command(icd10_group)
