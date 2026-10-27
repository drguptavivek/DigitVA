"""GET /help/search: login required, JSON suggestions."""

import os
from unittest import mock

from app.services import ai_search_service as svc
from tests.base import BaseTestCase


class HelpSearchRouteTests(BaseTestCase):
    def test_requires_a_login(self):
        response = self.client.get("/help/search?q=recode")
        self.assertIn(response.status_code, (302, 401))

    def test_returns_suggestions_for_a_signed_in_user(self):
        self._login(self.base_coder_id)
        svc.clear_fallback_cache()
        with mock.patch.dict(os.environ, {"TYPESENSE_HOST": "", "TYPESENSE_API_KEY": ""}):
            response = self.client.get("/help/search?q=pasword resett")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Password Reset",
            [r["title"] for r in response.get_json()["results"]],
        )
        svc.clear_fallback_cache()

    def test_short_query_is_empty(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/help/search?q=a").get_json(), {"results": []})
