"""Every top-level Expo route must be served by /app/ on a hard load."""

import re
import unittest
from pathlib import Path

from app.routes.expo_client import _SPA_ROUTE_ROOTS

_APP_DIR = Path(__file__).resolve().parent.parent / "mobile" / "digitva-collect" / "app"


class ExpoClientRouteTests(unittest.TestCase):
    def test_every_expo_route_file_is_in_the_spa_allowlist(self):
        routes = {
            re.sub(r"\.(web|native)$", "", path.stem)
            for path in _APP_DIR.glob("*.tsx")
            if not path.stem.startswith("_") and path.stem != "index"
        }
        self.assertIn("supervision", routes)  # the directory was actually read
        missing = sorted(routes - _SPA_ROUTE_ROOTS)
        self.assertEqual(missing, [], f"/app/ would 404 on reload for: {missing}")


if __name__ == "__main__":
    unittest.main()
