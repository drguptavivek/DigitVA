"""GET /api/v1/app/android/latest: the Android build this server hosts.

Public (an enrolled phone may check before sign-in) and user-free. Derived
only from the APK /download/android serves (the image's pinned release asset),
so there is no second pin to drift. The app falls back to GitHub releases and
never installs anything by itself (docs/policy/expo-client.md).
"""
import hashlib
import os
import re
from functools import lru_cache

from flask import Blueprint, current_app, jsonify, url_for

from app import limiter
from app.routes.api.request_helpers import error
from app.services.worker_enrolment_service import hosted_android_apk

bp = Blueprint("app_release_api", __name__)

# digitva-collect-<major>.<minor>.<patch>-<abi>.apk (docs/current-state/android-release-builds.md)
_ASSET_RE = re.compile(r"^digitva-collect-(\d+)\.(\d+)\.(\d+)-.+\.apk$")


@lru_cache(maxsize=4)
def _sha256(path: str, mtime_ns: int, size: int) -> str:
    # mtime and size key the cache so a replaced file is hashed again.
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@bp.get("/android/latest")
@limiter.limit("30 per minute")
def android_latest():
    """``{version, version_code, tag, asset, url, sha256}``. ``version_code`` is
    the base ``major*10000 + minor*100 + patch``; the installed per-ABI code is
    ``base*10 + ABI`` (armeabi-v7a 1, arm64-v8a 2). 404 ``no_release`` when the
    image pinned no APK or its name is not a release name."""
    asset = hosted_android_apk()
    match = _ASSET_RE.match(asset) if asset else None
    if not match:
        return error("No Android release is hosted on this server.", "no_release", 404)
    major, minor, patch = (int(part) for part in match.groups())
    path = os.path.join(current_app.config["DIGITVA_ANDROID_APK_DIR"], asset)
    stat = os.stat(path)
    version = f"{major}.{minor}.{patch}"
    response = jsonify({
        "version": version,
        "version_code": major * 10000 + minor * 100 + patch,
        "tag": f"android-v{version}",
        "asset": asset,
        "url": url_for("help.download_android", _external=True),
        "sha256": _sha256(path, stat.st_mtime_ns, stat.st_size),
    })
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
