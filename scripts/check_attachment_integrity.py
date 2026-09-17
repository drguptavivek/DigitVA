#!/usr/bin/env python3
"""Report attachment integrity between the DB and DigitVA's attachment store.

A thin reporting wrapper: the checks themselves are
``attachment_service.local_integrity_check()`` and
``attachment_service.s3_integrity_check()``, because deciding what counts as a
missing blob or an orphan is an attachment-module decision, not a script's.

Local store (``--store local``):
1. Missing files for DB attachment rows (exists_on_odk=true).
2. Orphan files on disk under APP_DATA/*/media not referenced by DB.

S3 store (``--store s3``):
1. Rows recorded as ``store_state='s3'`` whose object is not in the bucket.
2. Keys under the configured prefix that no row references.
3. Rows still awaiting the cutover (``store_state`` other than ``s3``).

The check never deletes or overwrites anything in the bucket; orphan
quarantining is a local-store-only affordance.
"""

from __future__ import annotations

import argparse

from app import create_app
from app.services.attachment_service import (
    local_integrity_check,
    orphan_quarantine_destination,
    quarantine_orphan_files,
    s3_integrity_check,
    scan_local_media_files,
)
from app.services.attachment_store import AttachmentStoreError

# Kept under their historical script-level names for existing callers and tests.
_scan_media_files = scan_local_media_files
_orphan_destination = orphan_quarantine_destination
_quarantine_orphans = quarantine_orphan_files


def run_check(
    form_id: str | None,
    max_report: int,
    quarantine_orphans: bool = False,
) -> int:
    app = create_app()
    with app.app_context():
        report = local_integrity_check(
            form_id=form_id, quarantine_orphans=quarantine_orphans
        )

    print("Attachment Integrity Check")
    print(f"APP_DATA: {report['app_data']}")
    print(f"Scope form_id: {form_id or 'ALL'}")
    print(f"DB attachment rows scanned: {report['rows_scanned']}")
    print(f"Disk files scanned under */media: {report['disk_files_scanned']}")
    print("")
    print(f"Missing files for DB rows (exists_on_odk=true): {len(report['missing_rows'])}")
    print(f"Orphan files on disk (not referenced by DB): {len(report['orphan_paths'])}")
    print(f"DB paths outside APP_DATA: {len(report['outside_app_data_rows'])}")

    if report["missing_rows"]:
        print("")
        print(f"Sample missing rows (max {max_report}):")
        for row in report["missing_rows"][:max_report]:
            print(
                f"- [{row['form_id']}] {row['va_sid']} :: {row['filename']} "
                f"reason={row['reason']} path={row['local_path']}"
            )

    if report["moved_orphans"]:
        print("")
        print(f"Quarantined orphan files into .orphaned (max {max_report}):")
        for source_path, destination in report["moved_orphans"][:max_report]:
            print(f"- {source_path} -> {destination}")

    if report["orphan_paths"]:
        print("")
        print(f"Sample orphan files (max {max_report}):")
        for path in report["orphan_paths"][:max_report]:
            print(f"- {path}")

    if report["outside_app_data_rows"]:
        print("")
        print(f"Sample DB paths outside APP_DATA (max {max_report}):")
        for row in report["outside_app_data_rows"][:max_report]:
            print(
                f"- [{row['form_id']}] {row['va_sid']} :: {row['filename']} "
                f"path={row['local_path']}"
            )

    return 0 if report["clean"] else 2


def run_s3_check(form_id: str | None, max_report: int) -> int:
    app = create_app()
    with app.app_context():
        try:
            report = s3_integrity_check(form_id=form_id)
        except AttachmentStoreError as exc:
            print(str(exc))
            return 1

    print("Attachment Integrity Check (S3 store)")
    print(f"Bucket prefix: {report['key_prefix'] or '(none)'}")
    print(f"Scope form_id: {form_id or 'ALL'}")
    print(f"DB attachment rows scanned: {report['rows_scanned']}")
    print(f"Keys listed under the prefix: {report['keys_listed']}")
    print("")
    print(f"Rows recorded as s3 with no object: {len(report['missing_objects'])}")
    print(f"Orphan keys not referenced by any row: {len(report['orphan_keys'])}")
    print(f"Rows still awaiting the cutover: {len(report['awaiting_cutover'])}")

    if report["missing_objects"]:
        print("")
        print(f"Sample missing objects (max {max_report}):")
        for key, (row_form_id, va_sid, filename) in report["missing_objects"][:max_report]:
            print(f"- [{row_form_id}] {va_sid} :: {filename} key={key}")

    if report["orphan_keys"]:
        print("")
        print(f"Sample orphan keys (max {max_report}):")
        for key in report["orphan_keys"][:max_report]:
            print(f"- {key}")

    if report["awaiting_cutover"]:
        print("")
        print(f"Sample rows awaiting the cutover (max {max_report}):")
        for row_form_id, va_sid, filename in report["awaiting_cutover"][:max_report]:
            print(f"- [{row_form_id}] {va_sid} :: {filename}")

    return 0 if report["clean"] else 2


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check missing attachment files and orphan files in APP_DATA."
    )
    parser.add_argument(
        "--form-id",
        default=None,
        help="Optional form_id scope (example: ICMR01MP0101).",
    )
    parser.add_argument(
        "--max-report",
        type=int,
        default=50,
        help="Maximum rows/files to print per section.",
    )
    parser.add_argument(
        "--quarantine-orphans",
        action="store_true",
        help="Move orphaned files into a .orphaned subdirectory under each media folder.",
    )
    parser.add_argument(
        "--store",
        choices=("local", "s3"),
        default="local",
        help="Which attachment store to check (default: local).",
    )
    args = parser.parse_args()
    if args.store == "s3":
        if args.quarantine_orphans:
            parser.error("--quarantine-orphans is local-store only; the S3 check never writes.")
        raise SystemExit(run_s3_check(args.form_id, args.max_report))
    raise SystemExit(run_check(args.form_id, args.max_report, args.quarantine_orphans))


if __name__ == "__main__":
    main()
