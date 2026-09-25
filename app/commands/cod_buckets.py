import click

from app import db
from app.models import VaCodBucketSchemeSnapshot
from app.services.cod_bucket_icd11_generator import (
    DEFAULT_REPORT_DIR,
    apply_icd11_generation,
    generate_icd11_buckets,
    write_icd11_generation_report,
    write_icd11_seed_csv,
)
from app.services.cod_bucket_mapping_service import (
    DEFAULT_CMEA10_WORKBOOK_PATH,
    DEFAULT_SRS_WORKBOOK_PATH,
    DEFAULT_WHO_2022_VA_2026_WORKBOOK_PATH,
    DEFAULT_WHO_2022_VA_ADMIN_OVERRIDES_PATH,
    DEFAULT_WHO_2022_VA_WORKBOOK_PATH,
    SCHEME_CODE_CMEA10,
    SCHEME_CODE_SRS_INDIA,
    SCHEME_CODE_WHO_2022_VA,
    SCHEME_CODE_WHO_2022_VA_2026,
    aggregate_coded_submissions_by_bucket,
    get_cod_bucket_scheme,
    import_cmea10_scheme,
    import_srs_india_scheme,
    import_who_2022_va_2026_scheme,
    import_who_2022_va_scheme,
    list_cod_bucket_schemes,
    snapshot_cod_bucket_scheme,
)
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE


def _snapshot_before_cli_reimport(scheme_code: str) -> None:
    """Snapshot an existing scheme before a CLI re-import replaces it.

    Fresh install (scheme absent) skips this entirely -- nothing to lose yet.
    Commits immediately: unlike the admin reset route, nothing here shares a
    transaction with the import that follows, so the snapshot must be durable
    on its own before that import runs.
    """
    existing = get_cod_bucket_scheme(scheme_code)
    if existing is None:
        return
    snapshot = snapshot_cod_bucket_scheme(
        scheme=existing,
        reason=VaCodBucketSchemeSnapshot.REASON_CLI_IMPORT,
    )
    db.session.commit()
    click.echo(f"Snapshot {snapshot.snapshot_id} saved before re-import.")


@click.group("cod-buckets")
def cod_buckets_group():
    """Cause-of-death reporting bucket commands."""


@cod_buckets_group.command("import-srs-india")
@click.option("--path", default=DEFAULT_SRS_WORKBOOK_PATH, show_default=True)
def import_srs_india(path):
    _snapshot_before_cli_reimport(SCHEME_CODE_SRS_INDIA)
    scheme = import_srs_india_scheme(path)
    click.echo(
        f"Imported {scheme.scheme_code} from {path} "
        f"(mapping_version={scheme.mapping_version})"
    )


@cod_buckets_group.command("import-cmea10")
@click.option("--path", default=DEFAULT_CMEA10_WORKBOOK_PATH, show_default=True)
def import_cmea10(path):
    _snapshot_before_cli_reimport(SCHEME_CODE_CMEA10)
    scheme = import_cmea10_scheme(path)
    click.echo(
        f"Imported {scheme.scheme_code} from {path} "
        f"(mapping_version={scheme.mapping_version})"
    )


@cod_buckets_group.command("import-who-2022-va")
@click.option("--path", default=DEFAULT_WHO_2022_VA_WORKBOOK_PATH, show_default=True)
@click.option(
    "--overrides-path",
    default=DEFAULT_WHO_2022_VA_ADMIN_OVERRIDES_PATH,
    show_default=True,
    help="CSV of frozen admin-editor overrides to reapply on top of the workbook.",
)
def import_who_2022_va(path, overrides_path):
    _snapshot_before_cli_reimport(SCHEME_CODE_WHO_2022_VA)
    scheme = import_who_2022_va_scheme(path, overrides_path)
    click.echo(
        f"Imported {scheme.scheme_code} from {path} "
        f"(mapping_version={scheme.mapping_version})"
    )


@cod_buckets_group.command("import-who-2022-va-2026")
@click.option("--path", default=DEFAULT_WHO_2022_VA_2026_WORKBOOK_PATH, show_default=True)
def import_who_2022_va_2026(path):
    _snapshot_before_cli_reimport(SCHEME_CODE_WHO_2022_VA_2026)
    scheme = import_who_2022_va_2026_scheme(path)
    click.echo(
        f"Imported {scheme.scheme_code} from {path} "
        f"(mapping_version={scheme.mapping_version})"
    )


@cod_buckets_group.command("generate-icd11")
@click.option("--scheme", "scheme_code", required=True, help="e.g. WHO_2022_VA_2026")
@click.option("--release", default=DEFAULT_ICD11_RELEASE, show_default=True)
@click.option("--apply", "apply_changes", is_flag=True, help="Write the rows (default: dry run).")
@click.option("--report-dir", default=DEFAULT_REPORT_DIR, show_default=True)
@click.option(
    "--seed-csv",
    default=None,
    help="Also freeze the mappings in a migration seed CSV "
    "(e.g. resource/who_2022_va_2026_icd11_native_mappings.csv).",
)
def generate_icd11(scheme_code, release, apply_changes, report_dir, seed_csv):
    """Generate the scheme's native ICD-11 buckets from the WHO VA cause list
    and the owner's recorded decisions.

    Dry run by default: decides every code and writes the review report, but
    no database row. --apply replaces only this scheme's ICD-11 rows.
    """
    try:
        result = generate_icd11_buckets(scheme_code=scheme_code, release=release)
    except (LookupError, ValueError) as exc:
        raise click.ClickException(str(exc))
    for path in write_icd11_generation_report(result, report_dir):
        click.echo(f"Wrote {path}")
    if seed_csv:
        click.echo(f"Wrote {write_icd11_seed_csv(result, seed_csv)}")
    click.echo(
        f"{scheme_code} ICD-11 {release}: {len(result.mappings)} mappings, "
        f"{len(result.unmapped)} unmapped, {result.review_count('tie')} ties, "
        f"{result.review_count('pj2x_split')} PJ2x splits, "
        f"{result.review_count('crosswalk_disagreement')} crosswalk disagreements"
    )
    for va_code, count in result.cause_counts.items():
        click.echo(f"  {va_code}\t{count}")
    if not apply_changes:
        click.echo("Dry run: nothing written to the database (use --apply).")
        return
    scheme = apply_icd11_generation(result)
    click.echo(
        f"Applied: {scheme.scheme_code} icd11_method={scheme.icd11_method} "
        f"mapping_version={scheme.mapping_version}"
    )


@cod_buckets_group.command("list")
def list_schemes():
    for scheme in list_cod_bucket_schemes():
        click.echo(
            f"{scheme.scheme_code}\t{scheme.scheme_name}\t"
            f"version={scheme.mapping_version}\tactive={scheme.is_active}"
        )


@cod_buckets_group.command("aggregate")
@click.option("--scheme-code", required=True)
@click.option("--project-id")
@click.option("--site-id")
@click.option("--form-id")
def aggregate(scheme_code, project_id, site_id, form_id):
    rows = aggregate_coded_submissions_by_bucket(
        scheme_code=scheme_code,
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
    )
    for row in rows:
        click.echo(
            "\t".join(
                [
                    row.get("project_id") or "",
                    row.get("site_id") or "",
                    row.get("form_id") or "",
                    row.get("age_scope") or "",
                    row.get("bucket_category") or "",
                    row.get("bucket_subcategory") or "",
                    row.get("bucket_field") or "",
                    str(row.get("coded_count") or 0),
                ]
            )
        )


def init_app(app):
    app.cli.add_command(cod_buckets_group)
