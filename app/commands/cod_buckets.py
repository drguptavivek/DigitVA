import click

from app.services.analytics.cod_buckets import (
    DEFAULT_CMEA10_WORKBOOK_PATH,
    DEFAULT_SRS_WORKBOOK_PATH,
    aggregate_coded_submissions_by_bucket,
    import_cmea10_scheme,
    import_srs_india_scheme,
    list_cod_bucket_schemes,
)


@click.group("cod-buckets")
def cod_buckets_group():
    """Cause-of-death reporting bucket commands."""


@cod_buckets_group.command("import-srs-india")
@click.option("--path", default=DEFAULT_SRS_WORKBOOK_PATH, show_default=True)
def import_srs_india(path):
    scheme = import_srs_india_scheme(path)
    click.echo(
        f"Imported {scheme.scheme_code} from {path} "
        f"(mapping_version={scheme.mapping_version})"
    )


@cod_buckets_group.command("import-cmea10")
@click.option("--path", default=DEFAULT_CMEA10_WORKBOOK_PATH, show_default=True)
def import_cmea10(path):
    scheme = import_cmea10_scheme(path)
    click.echo(
        f"Imported {scheme.scheme_code} from {path} "
        f"(mapping_version={scheme.mapping_version})"
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
