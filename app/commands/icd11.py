import json

import click

from app.services.icd11_mms_service import (
    DEFAULT_ICD11_MMS_CSV_PATH,
    DEFAULT_ICD11_MMS_EXPORT_PATH,
    DEFAULT_ICD11_RELEASE,
    export_icd11_mms_policy_json,
    generate_icd11_mms_seed_csv,
    get_icd11_mms_stats,
    import_icd11_mms_from_export,
    import_icd11_mms_policy_json,
)


@click.group("icd11")
def icd11_group():
    """ICD-11 MMS master-data commands."""


@icd11_group.command("import")
@click.option("--export-path", default=str(DEFAULT_ICD11_MMS_EXPORT_PATH), show_default=True)
@click.option("--release", default=DEFAULT_ICD11_RELEASE, show_default=True)
@click.option(
    "--apply-policy-columns",
    is_flag=True,
    default=False,
    help="Reset policy columns to unreviewed instead of preserving existing DB values.",
)
def import_icd11(export_path: str, release: str, apply_policy_columns: bool) -> None:
    result = import_icd11_mms_from_export(
        export_path=export_path,
        release=release,
        apply_policy_columns=apply_policy_columns,
    )
    click.echo(
        "Imported mas_icd11_mms "
        f"release={release} rows={result.total_rows} inserted={result.inserted} "
        f"updated={result.updated} deactivated={result.deactivated}"
    )


@icd11_group.command("generate-seed-csv")
@click.option("--export-path", default=str(DEFAULT_ICD11_MMS_EXPORT_PATH), show_default=True)
@click.option("--csv-path", default=str(DEFAULT_ICD11_MMS_CSV_PATH), show_default=True)
def generate_seed_csv(export_path: str, csv_path: str) -> None:
    row_count = generate_icd11_mms_seed_csv(export_path=export_path, csv_path=csv_path)
    click.echo(f"Wrote {row_count} rows to {csv_path}")


@icd11_group.command("stats")
@click.option("--release", default=DEFAULT_ICD11_RELEASE, show_default=True)
def stats(release: str) -> None:
    result = get_icd11_mms_stats(release=release)
    click.echo(
        "\n".join(
            [
                f"total_rows={result['total_rows']}",
                f"active_rows={result['active_rows']}",
                f"chapters={result['chapters']}",
                f"blocks={result['blocks']}",
                f"categories={result['categories']}",
                f"residual_rows={result['residual_rows']}",
                f"leaf_rows={result['leaf_rows']}",
            ]
        )
    )


@icd11_group.command("policy-export")
@click.option("--release", default=DEFAULT_ICD11_RELEASE, show_default=True)
@click.option("--output", "output_path", default=None, help="Write to this file instead of stdout.")
def policy_export(release: str, output_path: str | None) -> None:
    payload = export_icd11_mms_policy_json(release=release)
    text = json.dumps(payload, indent=2)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        click.echo(f"Wrote policy export ({payload['row_count']} rows) to {output_path}")
    else:
        click.echo(text)


@icd11_group.command("policy-import")
@click.argument("input_path")
@click.option("--release", default=DEFAULT_ICD11_RELEASE, show_default=True)
def policy_import(input_path: str, release: str) -> None:
    with open(input_path, encoding="utf-8") as handle:
        payload = handle.read()
    result = import_icd11_mms_policy_json(payload, release=release)
    click.echo(
        "Policy import completed "
        f"total_items={result.total_items} updated_items={result.updated_items} "
        f"reset_items={result.reset_items} skipped_items={len(result.skipped_items)}"
    )


def init_app(app):
    app.cli.add_command(icd11_group)
