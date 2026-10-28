"""Public server compatibility and hosted Android release metadata.

Public (an enrolled phone may check before sign-in) and user-free. Derived
only from the APKs the download routes serve (the image's pinned release assets),
so there is no second pin to drift. The app falls back to GitHub releases and
never installs anything by itself (docs/policy/expo-client.md).
"""
import hashlib
import os
import re
from functools import lru_cache

from flask import Blueprint, current_app, jsonify, request, url_for

from app import limiter
from app.routes.api.request_helpers import error
from app.services.worker_enrolment_service import hosted_android_apk

bp = Blueprint("app_release_api", __name__)

# digitva-collect-<major>.<minor>.<patch>-<abi>.apk (docs/current-state/android-release-builds.md)
_ASSET_RE = re.compile(r"^digitva-collect-(?:plus-)?(\d+)\.(\d+)\.(\d+)-arm64-v8a\.apk$")


@lru_cache(maxsize=4)
def _sha256(path: str, mtime_ns: int, size: int) -> str:
    # mtime and size key the cache so a replaced file is hashed again.
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@bp.get("/version")
@limiter.limit("30 per minute")
def server_version():
    """Return the deployed revision and the native API compatibility level."""
    revision = current_app.config.get("DIGITVA_BUILD_REVISION") or ""
    response = jsonify({
        "api_compatibility": 1,
        "build_revision": revision if re.fullmatch(r"[0-9a-f]{40}", revision) else None,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/android/latest")
@limiter.limit("30 per minute")
def android_latest():
    """Return metadata for the selected variant. ``version_code`` is
    the base ``major*10000 + minor*100 + patch``; the installed per-ABI code is
    ``base*10 + ABI`` (armeabi-v7a 1, arm64-v8a 2). 404 ``no_release`` when the
    image pinned no APK or its name is not a release name."""
    variant = request.args.get("variant", "normal")
    if variant not in ("normal", "plus"):
        return error("Invalid Android release variant.", "invalid_variant", 400)
    asset = hosted_android_apk(variant)
    match = _ASSET_RE.match(asset) if asset else None
    if not match:
        return error("No Android release is hosted on this server.", "no_release", 404)
    major, minor, patch = (int(part) for part in match.groups())
    path = os.path.join(current_app.config["DIGITVA_ANDROID_APK_DIR"], asset)
    stat = os.stat(path)
    version = f"{major}.{minor}.{patch}"
    tag = f"android-v{version}"
    if variant == "plus":
        plus_tag = current_app.config.get("DIGITVA_PLUS_ANDROID_APK_TAG", "")
        tag = plus_tag if re.fullmatch(
            rf"collect-plus-v{re.escape(version)}-plus\.[1-9]\d*", plus_tag
        ) else None
    response = jsonify({
        "version": version,
        "version_code": major * 10000 + minor * 100 + patch,
        "tag": tag,
        "asset": asset,
        "url": url_for("help.download_android_plus" if variant == "plus" else "help.download_android", _external=True),
        "sha256": _sha256(path, stat.st_mtime_ns, stat.st_size),
        "variant": variant,
        "size_bytes": stat.st_size,
    })
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
