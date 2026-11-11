"""Every docs/ seed folder a migration reads is in the server image.

docs/ is excluded from the image (.dockerignore); a fresh database such as the
public demo's migrates from the image alone, so a migration reading an
excluded file fails at boot (the first demo start, 2026-10-27).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "docs/icd-causegrp-mappings/migration-artifacts/"


def _string_literals(source):
    return "".join(a or b for a, b in re.findall(r'"([^"\n]*)"|\'([^\'\n]*)\'', source))


def test_migration_seed_folders_are_in_the_image():
    included = {
        line[1:].strip().rstrip("/")
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.startswith("!docs/")
    }
    needed = set()
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        joined = _string_literals(path.read_text())
        for match in re.finditer(re.escape(PREFIX) + r"([A-Za-z0-9._-]+)", joined):
            folder = PREFIX + match.group(1)
            if (ROOT / folder).is_dir():
                needed.add(folder)
    assert needed, "expected migrations that read seed folders under docs/"
    assert needed <= included, sorted(needed - included)


def test_icd11_generator_inputs_are_in_the_image():
    """A WHO_2022_VA_2026 reset regenerates ICD-11 from these files at runtime."""
    from app.services.cod_bucket_icd11_generator import (
        CAUSE_LIST_PATH,
        CHANGE_LIST_PATH,
        CROSSWALK_PATH,
        DECISIONS_PATH,
    )

    included = {
        line[1:].strip()
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.startswith("!docs/")
    }
    for path in (CAUSE_LIST_PATH, CROSSWALK_PATH, CHANGE_LIST_PATH, DECISIONS_PATH):
        assert (ROOT / path).is_file(), path
        assert path in included, path
