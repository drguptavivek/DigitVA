"""Static hosting for the Expo web export under ``/app/``.

The export is an optional deployment artifact.  A missing export therefore
returns a normal 404, which keeps a server-only deployment usable while the
client is being built.
"""

import functools
import os
import re
from pathlib import Path

from flask import Blueprint, abort, current_app, send_file

expo_client = Blueprint("expo_client", __name__)

_SPA_ROUTE_ROOTS = frozenset(
    {
        "admin",
        "case",
        "collection",
        "coding",
        "death-registration",
        "data",
        "demo",
        "enrol",
        "engine-check",
        "form",
        "home",
        "index",
        "intake",
        "interview",
        "login",
        "mentoring",
        "new-death",
        "offline-coding",
        "offline-profile",
        "organization",
        "pin-setup",
        "register",
        "review",
        "reviewing",
        "revision",
        "settings",
        "sign-in",
        "standalone",
        "standalone-setup",
        "statistics",
        "supervision",
        "training",
        "unlock",
        "users",
        "worklist",
        "workspace",
    }
)


def _dist_root() -> Path:
    configured = current_app.config.get("EXPO_CLIENT_DIST") or os.environ.get(
        "EXPO_CLIENT_DIST"
    )
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(current_app.root_path).parent / "mobile" / "digitva-collect" / "dist").resolve()


@functools.cache
def export_ready() -> bool:
    """Whether the export has its ``index.html``, so ``/app/`` can serve.

    Memoised per process: a rebuilt export is seen after a restart, which
    keeps the login landing from touching the filesystem on every call.
    """
    return (_dist_root() / "index.html").is_file()


def _safe_file(root: Path, relative_path: str) -> Path | None:
    """Resolve a regular file that remains inside *root*.

    ``send_from_directory`` protects URL path components, but checking the
    resolved path here also refuses symlinks that point outside the export.
    """
    if not relative_path or "\x00" in relative_path or "\\" in relative_path:
        return None
    # Hidden files (.env, .git, .DS_Store) are never part of the public export.
    if any(part.startswith(".") for part in relative_path.split("/")):
        return None
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _known_spa_route(relative_path: str) -> bool:
    route = relative_path.strip("/")
    if not route:
        return True
    first = route.split("/", 1)[0]
    return first in _SPA_ROUTE_ROOTS


def _serve(relative_path: str):
    root = _dist_root()
    if not root.is_dir():
        abort(404)

    asset = _safe_file(root, relative_path)
    if asset is not None:
        # Only content-addressed assets are immutable; entrypoints must see each release.
        hashed_asset = relative_path.startswith(("_expo/", "assets/")) and re.search(
            r"[.-][0-9a-f]{32,64}\.", asset.name
        )
        # Release tarballs have fixed mtimes: stat-based validators can match changed bytes.
        response = send_file(asset, conditional=bool(hashed_asset), etag=bool(hashed_asset))
        if not hashed_asset:
            response.headers.pop("Last-Modified", None)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if hashed_asset else "no-cache"
        )
        return response

    # A path with a file extension is an asset request.  Unknown assets must
    # remain 404 instead of receiving the application's index document.
    final_component = relative_path.rsplit("/", 1)[-1]
    if "." in final_component or not _known_spa_route(relative_path):
        abort(404)

    index = _safe_file(root, "index.html")
    if index is None:
        abort(404)
    response = send_file(index, conditional=False, etag=False)
    response.headers.pop("Last-Modified", None)
    response.headers["Cache-Control"] = "no-cache"
    return response


@expo_client.get("/app/")
def expo_index():
    response = _serve("index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response


@expo_client.get("/app/<path:relative_path>")
def expo_asset(relative_path):
    return _serve(relative_path)
