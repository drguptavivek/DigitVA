"""Cache-busting token for the vendored WHO VA form bundle.

The bundle is served from static/ with a 30-day cache, so a URL versioned
only by STATIC_ASSET_VERSION kept browsers on the previous form after a
rebuild. The manifest checksum changes with every rebuild; reading is keyed on
the manifest's mtime so dev picks up a rebuild without a restart, at the cost
of one stat per render.
"""

import functools
import json
import os

_MANIFEST = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "static", "vendor", "who-va-2022", "manifest.json"
)


@functools.lru_cache(maxsize=4)
def _version_for(mtime_ns):
    with open(_MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)["sha256"][:16]


def who_va_bundle_version(fallback=""):
    try:
        return _version_for(os.stat(_MANIFEST).st_mtime_ns)
    except (OSError, ValueError, KeyError):
        return fallback
