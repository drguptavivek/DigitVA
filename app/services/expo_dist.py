"""Where the Expo web export lives on disk.

Shared by ``app.routes.expo_client`` (serves it under ``/app/``) and
``ui_string_service`` (reads its ``ui-strings`` folder), so the service does
not import a route module (digitva-r8nh.13).
"""

import os
from pathlib import Path

from flask import current_app


def _dist_root() -> Path:
    configured = current_app.config.get("EXPO_CLIENT_DIST") or os.environ.get(
        "EXPO_CLIENT_DIST"
    )
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(current_app.root_path).parent / "mobile" / "digitva-collect" / "dist").resolve()
