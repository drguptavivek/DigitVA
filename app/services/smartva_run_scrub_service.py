"""Blank personal data in existing SmartVA run files (PII policy OD7).

New runs no longer receive any sealed field (``va_smartva_02_prepdata``).
Run directories written before that hold them in several files: the input
CSV under the WHO ids, SmartVA's intermediates under its own names
(``Id10073 -> gen_6_7``, ``Id10017 -> gen_5_0``, ``Id10018 -> gen_5_0a``,
``Id10057 -> gen_2_3a``: ``smartva/data/who_data.py`` ``RENAME_QUESTIONS``)
and the per-death outputs as ``national_id``, ``name``, ``surname`` and
``geography1-5`` (``smartva/output_prep.py``). SmartVA scores none of them
(docs/kb/smart-va/demographic-general.md) and nothing in the app reads a run
file after the run, so the cells are blanked in place: headers, row count and
every other cell stay as they were.

Dry run by default, counts per file kind only (never a path, a value or a
submission id). ``apply`` rewrites each file through a temporary file and an
atomic rename. Local runs: only regular files under ``APP_SMARTVA_RUNS``,
never a symlink or a path that resolves outside it. S3 (``smartva_runs/``
archive): download, blank, upload to the same key, verify the size; earlier
object versions are left to the operator (bucket versioning and lifecycle),
never deleted here. Idempotent: a blanked cell is empty, so a rerun rewrites
nothing.

Order: local first, then S3. ``archive_form_run`` re-uploads every local file
whose size differs from its object, so an unscrubbed local copy of an
archived run would undo an S3 scrub on the next archive sweep. The S3 apply
therefore refuses (``ScrubRefused``) while any local run file still has a
cell to blank; a scrubbed local file and its scrubbed object come from the
same rewrite, so their sizes match and nothing is re-uploaded.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import sys
import tempfile
from collections import Counter

from flask import current_app

from app.services.pii_field_registry import all_sealed_field_ids

log = logging.getLogger(__name__)

#: SmartVA's own names for sealed WHO fields in its intermediate files.
SMARTVA_RENAMED_COLUMNS = frozenset({"gen_6_7", "gen_5_0", "gen_5_0a", "gen_2_3a"})
#: Output columns SmartVA fills from those, in the per-death output files only
#: (``name`` and the like may mean something else in an aggregate file).
SMARTVA_OUTPUT_COLUMNS = frozenset({
    "national_id", "name", "name2", "surname", "surname2",
    "geography1", "geography2", "geography3", "geography4", "geography5",
})
_PER_DEATH_OUTPUTS = re.compile(r"(^|-)predictions\.csv$|^individual-cause-of-death\.csv$")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class ScrubRefused(RuntimeError):
    """A precondition refused an apply. The message names no path or value."""


def columns_to_blank(filename: str, sealed: frozenset[str]) -> frozenset[str]:
    """The header names blanked in a run file called *filename*."""
    columns = sealed | SMARTVA_RENAMED_COLUMNS
    if _PER_DEATH_OUTPUTS.search(filename):
        columns |= SMARTVA_OUTPUT_COLUMNS
    return columns


def file_kind(filename: str) -> str:
    """The file name without any UUID: the unit counts are reported by."""
    return _UUID.sub("", filename)


def scrub_csv(path: str, columns: frozenset[str], *, apply: bool) -> int:
    """Blank every non-empty cell of *columns* in the CSV at *path*; returns
    the cells blanked (or that would be). Bytes round-trip through
    ``surrogateescape``, so a file that is not valid UTF-8 is not mangled."""
    # A payload cell (a narrative) can exceed csv's 128 KiB default.
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    with open(path, newline="", encoding="utf-8", errors="surrogateescape") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return 0
    indexes = [i for i, name in enumerate(rows[0]) if name.strip() in columns]
    blanked = 0
    for row in rows[1:]:
        for i in indexes:
            if i < len(row) and row[i] != "":
                row[i] = ""
                blanked += 1
    if blanked and apply:
        fd, tmp_path = tempfile.mkstemp(prefix=".scrub-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8", errors="surrogateescape") as out:
                csv.writer(out).writerows(rows)
            os.replace(tmp_path, path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    return blanked


def scrub_local_runs(*, apply: bool = False) -> dict:
    """Scrub every CSV under ``APP_SMARTVA_RUNS``. Returns ``{"files": {kind:
    n}, "files_with_cells": {kind: n}, "cells": {kind: n}, "errors": n}``."""
    root = current_app.config.get("APP_SMARTVA_RUNS")
    counts = _empty_counts()
    if not root or not os.path.isdir(root):
        return counts
    real_root = os.path.realpath(root)
    sealed = all_sealed_field_ids()
    for dirpath, dirnames, filenames in os.walk(real_root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            if not filename.endswith(".csv") or os.path.islink(path) or not os.path.isfile(path):
                continue
            if os.path.commonpath([real_root, os.path.realpath(path)]) != real_root:
                continue
            _count_file(counts, filename, lambda: scrub_csv(path, columns_to_blank(filename, sealed), apply=apply))
    return counts


def scrub_archived_runs(*, apply: bool = False) -> dict:
    """Scrub every CSV object under the ``smartva_runs/`` archive prefix of
    the S3 store, one object at a time through a private temporary file.
    Returns the counts of ``scrub_local_runs``, plus ``skipped_local_store``."""
    from app.services.attachment_store import get_attachment_store
    from app.services.smartva_run_archive_service import ARCHIVE_KEY_ROOT, archiving_enabled

    counts = _empty_counts()
    if not archiving_enabled():
        return {**counts, "skipped_local_store": True}
    if apply:
        local = scrub_local_runs(apply=False)
        if sum(local["cells"].values()) or local["errors"]:
            raise ScrubRefused(
                "Local SmartVA run files still hold personal-data cells; run `flask smartva scrub-runs "
                "--apply` (local) first, or the next archive sweep re-uploads them over the scrubbed objects."
            )
    store = get_attachment_store()
    sealed = all_sealed_field_ids()
    absolute_root = store.absolute_key(ARCHIVE_KEY_ROOT)
    with tempfile.TemporaryDirectory(prefix="smartva-scrub-") as workdir:
        for absolute_key, _size, _etag in store.iter_keys(absolute_root):
            if not absolute_key.endswith(".csv"):
                continue
            key = absolute_key[len(store.key_prefix):]
            filename = key.rsplit("/", 1)[-1]
            local = os.path.join(workdir, "object.csv")

            def scrub_object():
                store.get_key(key, local)
                blanked = scrub_csv(local, columns_to_blank(filename, sealed), apply=apply)
                if blanked and apply:
                    store.put_key(key, local, content_type="text/csv")
                    head = store.head_key(key) or {}
                    if head.get("ContentLength") != os.path.getsize(local):
                        raise RuntimeError("size mismatch after upload")
                return blanked

            _count_file(counts, filename, scrub_object)
            if os.path.exists(local):
                os.remove(local)
    return {**counts, "skipped_local_store": False}


def _empty_counts() -> dict:
    return {"files": Counter(), "files_with_cells": Counter(), "cells": Counter(), "errors": 0}


def _count_file(counts: dict, filename: str, scrub) -> None:
    kind = file_kind(filename)
    counts["files"][kind] += 1
    try:
        blanked = scrub()
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the sweep
        counts["errors"] += 1
        # The kind and error class only: a message could carry a path or a key.
        log.warning("smartva scrub | a %s file failed: %s", kind, type(exc).__name__)
        return
    if blanked:
        counts["files_with_cells"][kind] += 1
        counts["cells"][kind] += blanked
