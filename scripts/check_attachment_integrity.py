#!/usr/bin/env python3
"""Check attachment integrity between the DB and DigitVA's attachment store.

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
import os
from pathlib import Path
from typing import Iterable

import sqlalchemy as sa

from app import create_app, db
from app.models import VaSubmissionAttachments, VaSubmissions
from app.services.attachment_service import (
    STORE_STATE_S3,
    local_attachment_file_exists,
    scan_local_media_files,
)
from app.services.attachment_store import StoreTarget, get_attachment_store


def _normalized_path(app_data: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    p = Path(raw_path)
    if not p.is_absolute():
        p = app_data / p
    return p.resolve(strict=False)


# Filesystem inventory lives behind the attachment service; kept as an alias
# for existing callers and tests.
_scan_media_files = scan_local_media_files


def _orphan_destination(source_path: Path) -> Path:
    try:
        media_root = next(parent for parent in source_path.parents if parent.name == "media")
    except StopIteration as exc:
        raise ValueError(f"Path is not under a media directory: {source_path}") from exc
    relative_path = source_path.relative_to(media_root)
    destination = media_root / ".orphaned" / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not destination.exists():
        return destination

    suffix = "".join(destination.suffixes)
    stem = destination.name[: -len(suffix)] if suffix else destination.name
    counter = 1
    while True:
        candidate_name = f"{stem}.{counter}{suffix}"
        candidate = destination.with_name(candidate_name)
        if not candidate.exists():
            return candidate
        counter += 1


def _quarantine_orphans(orphan_files: Iterable[Path]) -> list[tuple[Path, Path]]:
    moved: list[tuple[Path, Path]] = []
    for source_path in orphan_files:
        destination = _orphan_destination(source_path)
        source_path.replace(destination)
        moved.append((source_path, destination))
    return moved


def run_check(
    form_id: str | None,
    max_report: int,
    quarantine_orphans: bool = False,
) -> int:
    app = create_app()
    with app.app_context():
        app_data = Path(app.config["APP_DATA"]).resolve(strict=False)

        stmt = (
            sa.select(
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
                VaSubmissionAttachments.local_path,
                VaSubmissionAttachments.exists_on_odk,
                VaSubmissions.va_form_id,
            )
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
            .order_by(VaSubmissions.va_form_id, VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename)
        )
        if form_id:
            stmt = stmt.where(VaSubmissions.va_form_id == form_id)

        rows = db.session.execute(stmt).mappings().all()

        referenced_paths: set[str] = set()
        missing_rows: list[dict] = []
        outside_app_data_rows: list[dict] = []

        for row in rows:
            norm_path = _normalized_path(app_data, row["local_path"])
            norm_str = str(norm_path) if norm_path else None
            if norm_str:
                referenced_paths.add(norm_str)
                if not str(norm_path).startswith(str(app_data) + os.sep):
                    outside_app_data_rows.append(
                        {
                            "va_sid": row["va_sid"],
                            "form_id": row["va_form_id"],
                            "filename": row["filename"],
                            "local_path": row["local_path"],
                        }
                    )

            if row["exists_on_odk"] is True:
                if norm_path is None:
                    missing_rows.append(
                        {
                            "reason": "local_path_null",
                            "va_sid": row["va_sid"],
                            "form_id": row["va_form_id"],
                            "filename": row["filename"],
                            "local_path": None,
                        }
                    )
                elif not local_attachment_file_exists(str(norm_path)):
                    missing_rows.append(
                        {
                            "reason": "file_missing",
                            "va_sid": row["va_sid"],
                            "form_id": row["va_form_id"],
                            "filename": row["filename"],
                            "local_path": str(norm_path),
                        }
                    )

        disk_file_count, disk_files = _scan_media_files(app_data)
        orphan_paths = [p for p in disk_files if str(p) not in referenced_paths]
        moved_orphans: list[tuple[Path, Path]] = []
        if quarantine_orphans and orphan_paths:
            moved_orphans = _quarantine_orphans(orphan_paths)
            disk_file_count, disk_files = _scan_media_files(app_data)
            orphan_paths = [p for p in disk_files if str(p) not in referenced_paths]

        print("Attachment Integrity Check")
        print(f"APP_DATA: {app_data}")
        print(f"Scope form_id: {form_id or 'ALL'}")
        print(f"DB attachment rows scanned: {len(rows)}")
        print(f"Disk files scanned under */media: {disk_file_count}")
        print("")
        print(f"Missing files for DB rows (exists_on_odk=true): {len(missing_rows)}")
        print(f"Orphan files on disk (not referenced by DB): {len(orphan_paths)}")
        print(f"DB paths outside APP_DATA: {len(outside_app_data_rows)}")

        if missing_rows:
            print("")
            print(f"Sample missing rows (max {max_report}):")
            for row in missing_rows[:max_report]:
                print(
                    f"- [{row['form_id']}] {row['va_sid']} :: {row['filename']} "
                    f"reason={row['reason']} path={row['local_path']}"
                )

        if moved_orphans:
            print("")
            print(f"Quarantined orphan files into .orphaned (max {max_report}):")
            for source_path, destination in moved_orphans[:max_report]:
                print(f"- {source_path} -> {destination}")

        if orphan_paths:
            print("")
            print(f"Sample orphan files (max {max_report}):")
            for path in orphan_paths[:max_report]:
                print(f"- {path}")

        if outside_app_data_rows:
            print("")
            print(f"Sample DB paths outside APP_DATA (max {max_report}):")
            for row in outside_app_data_rows[:max_report]:
                print(
                    f"- [{row['form_id']}] {row['va_sid']} :: {row['filename']} "
                    f"path={row['local_path']}"
                )

        return 0 if not missing_rows and not orphan_paths else 2


def run_s3_check(form_id: str | None, max_report: int) -> int:
    """Compare the rows recorded as S3-stored against what the bucket holds.

    Both sides are bounded: rows are streamed with ``yield_per`` and keys are
    read one ``list_objects_v2`` page at a time, so neither a large table nor a
    large bucket is materialised. Nothing is written or deleted.
    """
    app = create_app()
    with app.app_context():
        store = get_attachment_store()
        if store.name != STORE_STATE_S3:
            print("ATTACHMENT_STORE is not 's3'; nothing to check against a bucket.")
            return 1

        stmt = (
            sa.select(
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
                VaSubmissionAttachments.storage_name,
                VaSubmissionAttachments.store_state,
                VaSubmissions.va_form_id,
            )
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
            .where(VaSubmissionAttachments.exists_on_odk.is_(True))
            .order_by(VaSubmissions.va_form_id, VaSubmissionAttachments.va_sid)
        )
        if form_id:
            stmt = stmt.where(VaSubmissions.va_form_id == form_id)

        expected: dict[str, tuple[str, str, str]] = {}
        not_yet_uploaded: list[tuple[str, str, str]] = []
        row_count = 0
        for row in db.session.execute(stmt).yield_per(500):
            row_count += 1
            if not row.storage_name:
                continue
            key = store.key_for(
                StoreTarget(va_form_id=row.va_form_id, storage_name=row.storage_name)
            )
            if row.store_state != STORE_STATE_S3:
                not_yet_uploaded.append((row.va_form_id, row.va_sid, row.filename))
                continue
            expected[key] = (row.va_form_id, row.va_sid, row.filename)

        present_keys: set[str] = set()
        key_count = 0
        for key, _size, _etag in store.iter_keys():
            key_count += 1
            present_keys.add(key)

        missing = [(key, meta) for key, meta in expected.items() if key not in present_keys]
        orphans = sorted(present_keys - set(expected))

        print("Attachment Integrity Check (S3 store)")
        print(f"Bucket prefix: {store.key_prefix or '(none)'}")
        print(f"Scope form_id: {form_id or 'ALL'}")
        print(f"DB attachment rows scanned: {row_count}")
        print(f"Keys listed under the prefix: {key_count}")
        print("")
        print(f"Rows recorded as s3 with no object: {len(missing)}")
        print(f"Orphan keys not referenced by any row: {len(orphans)}")
        print(f"Rows still awaiting the cutover: {len(not_yet_uploaded)}")

        if missing:
            print("")
            print(f"Sample missing objects (max {max_report}):")
            for key, (row_form_id, va_sid, filename) in missing[:max_report]:
                print(f"- [{row_form_id}] {va_sid} :: {filename} key={key}")

        if orphans:
            print("")
            print(f"Sample orphan keys (max {max_report}):")
            for key in orphans[:max_report]:
                print(f"- {key}")

        if not_yet_uploaded:
            print("")
            print(f"Sample rows awaiting the cutover (max {max_report}):")
            for row_form_id, va_sid, filename in not_yet_uploaded[:max_report]:
                print(f"- [{row_form_id}] {va_sid} :: {filename}")

        return 0 if not missing and not orphans else 2

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
