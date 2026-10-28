#!/usr/bin/env python3
"""Generate the mobile app's offline Rust and production npm notices bundle.

The inventory comes from Cargo's locked mobile-core Android graph and the npm
lockfile's non-development package entries. Only text found in authentic source
files is copied; unavailable notices are recorded without inventing terms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "mobile" / "digitva-collect"
RUST_MANIFEST = ROOT / "vendor" / "smartva-analyze" / "rust" / "Cargo.toml"
OUTPUT = APP / "assets" / "third-party-notices.json"
RUST_TARGET = "aarch64-linux-android"
LICENSE_FILE = re.compile(r"^(license|licence|copying|copyright|notice|unlicense)([-_.].*)?$", re.IGNORECASE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_notice_files(directory: Path) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    try:
        candidates = sorted(
            (path for path in directory.iterdir() if path.is_file() and LICENSE_FILE.match(path.name)),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        return found
    for candidate in candidates:
        if not candidate.is_file():
            continue
        raw = candidate.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not text.strip():
            continue
        found.append({"file": candidate.name, "sha256": sha256(raw), "text": text.rstrip()})
    return found


def register_notices(notice_files: list[dict[str, str]], notice_texts: dict[str, str]) -> list[str]:
    ids: list[str] = []
    for notice in notice_files:
        notice_id = notice["sha256"]
        notice_texts.setdefault(notice_id, notice["text"])
        ids.append(notice_id)
    return ids


def cargo_metadata() -> dict[str, Any]:
    result = subprocess.run(
        [
            "cargo", "metadata", "--manifest-path", str(RUST_MANIFEST),
            "--locked", "--offline", "--format-version", "1",
            "--no-default-features", "--features", "mobile-core",
            "--filter-platform", RUST_TARGET,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def rust_package_entry(package: dict[str, Any], notice_texts: dict[str, str]) -> dict[str, Any]:
    manifest = Path(package["manifest_path"])
    package_dir = manifest.parent
    notice_files = read_notice_files(package_dir)
    if not notice_files and package_dir.name == "rust" and package.get("source") is None:
        # The locally vendored smartva-rust crate's authentic MIT notice is at
        # vendor/smartva-analyze/LICENSE, beside rust/ rather than inside it.
        notice_files = read_notice_files(package_dir.parent)
    notice_ids = register_notices(notice_files, notice_texts)
    return {
        "ecosystem": "Rust",
        "name": package["name"],
        "version": package["version"],
        "license": package.get("license") or "Not declared in Cargo metadata",
        "source": f"https://crates.io/crates/{package['name']}/{package['version']}" if package.get("source") else "Vendored in this repository",
        "notices": [{"file": notice["file"], "id": notice["sha256"]} for notice in notice_files],
        "notice_ids": notice_ids,
        "notice_status": "available" if notice_ids else "license text not found in local source",
    }


def package_name_from_lock_path(path: str) -> str:
    remainder = path.removeprefix("node_modules/")
    parts = remainder.split("/")
    if parts and parts[0].startswith("@") and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0] if parts else remainder


def package_supports_android(package: dict[str, Any]) -> bool:
    """Exclude lockfile optional builds that cannot be installed on Android."""
    os_constraints = package.get("os") or []
    if os_constraints and "android" not in os_constraints and any(not item.startswith("!") for item in os_constraints):
        return False
    if "!android" in os_constraints:
        return False
    cpu_constraints = package.get("cpu") or []
    android_cpus = {"arm", "arm64", "ia32", "x64"}
    if cpu_constraints and not (set(cpu_constraints) & android_cpus):
        return False
    return True


def npm_packages(notice_texts: dict[str, str]) -> list[dict[str, Any]]:
    lock_path = APP / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    entries = []
    for lock_key, package in lock.get("packages", {}).items():
        if not lock_key or not package.get("version") or package.get("dev", False) or not package_supports_android(package):
            continue
        name = package.get("name") or package_name_from_lock_path(lock_key)
        installed_path = APP / lock_key
        package_json = installed_path / "package.json"
        installed = package_json.is_file()
        if installed:
            try:
                installed_manifest = json.loads(package_json.read_text(encoding="utf-8"))
                name = installed_manifest.get("name", name)
            except (OSError, json.JSONDecodeError):
                pass
        notice_files = read_notice_files(installed_path) if installed else []
        notice_ids = register_notices(notice_files, notice_texts)
        entries.append({
            "ecosystem": "npm",
            "name": name,
            "version": package["version"],
            "license": package.get("license") or "Not declared in package-lock.json",
            "source": package.get("resolved") or f"npm:{name}@{package['version']}",
            "optional": bool(package.get("optional")),
            "notices": [{"file": notice["file"], "id": notice["sha256"]} for notice in notice_files],
            "notice_ids": notice_ids,
            "notice_status": (
                "available" if notice_ids else "package not installed locally"
                if not installed else "license text not found in local package"
            ),
        })
    return sorted(entries, key=lambda entry: (entry["name"].casefold(), entry["version"], entry["source"]))


def rust_std_entries(notice_texts: dict[str, str]) -> list[dict[str, Any]]:
    rustc = subprocess.run(["rustc", "--print", "sysroot"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    rustc_version = subprocess.run(["rustc", "--version"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    rustc_verbose = subprocess.run(["rustc", "--version", "--verbose"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    commit = next((line.split(":", 1)[1].strip() for line in rustc_verbose.splitlines() if line.startswith("commit-hash:")), None)
    license_dir = Path(rustc) / "share" / "doc" / "rust" / "licenses"
    files = []
    for name in ("MIT.txt", "Apache-2.0.txt"):
        path = license_dir / name
        if path.is_file():
            raw = path.read_bytes()
            text = raw.decode("utf-8").rstrip()
            files.append({"file": name, "sha256": sha256(raw), "text": text})
    ids = register_notices(files, notice_texts)
    return [{
        "ecosystem": "Rust toolchain",
        "name": "Rust standard library",
        "version": rustc_version,
        "license": "MIT OR Apache-2.0",
        "source": f"https://github.com/rust-lang/rust/tree/{commit}/library" if commit else "https://github.com/rust-lang/rust/tree/master/library",
        "notices": [{"file": item["file"], "id": item["sha256"]} for item in files],
        "notice_ids": ids,
        "notice_status": "available" if ids else "toolchain licence texts not found locally",
    }]


def generate() -> bytes:
    cargo_lock = RUST_MANIFEST.with_name("Cargo.lock")
    npm_lock = APP / "package-lock.json"
    notice_texts: dict[str, str] = {}
    cargo = cargo_metadata()
    packages = [rust_package_entry(package, notice_texts) for package in cargo["packages"]]
    packages.extend(rust_std_entries(notice_texts))
    packages.extend(npm_packages(notice_texts))
    packages.sort(key=lambda entry: (entry["ecosystem"], entry["name"].casefold(), entry["version"]))

    unavailable = [entry for entry in packages if entry["notice_status"] != "available"]
    document = {
        "format_version": 1,
        "scope": "Locked Rust mobile-core Android graph and Android-compatible non-development npm package-lock graph",
        "generation": {
            "generator": "mobile/scripts/generate_third_party_notices.py",
            "rust_target": RUST_TARGET,
            "cargo_lock_sha256": sha256(cargo_lock.read_bytes()),
            "npm_lock_sha256": sha256(npm_lock.read_bytes()),
            "npm_packages": sum(entry["ecosystem"] == "npm" for entry in packages),
            "rust_packages": sum(entry["ecosystem"] == "Rust" for entry in packages),
            "rust_toolchain_entries": sum(entry["ecosystem"] == "Rust toolchain" for entry in packages),
            "unique_notice_texts": len(notice_texts),
            "packages_without_local_notice_text": len(unavailable),
        },
        "package_notices": packages,
        "notice_texts": notice_texts,
    }
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the checked-in bundle is stale")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    content = generate()
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != content:
            print(f"stale generated notices bundle: {args.output}", file=sys.stderr)
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(content)
    data = json.loads(content)
    generation = data["generation"]
    print(json.dumps({"output": str(args.output), "bytes": len(content), **generation}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
