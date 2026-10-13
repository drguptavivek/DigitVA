"""One role-label table (app.models.va_selectives.ROLE_LABELS) feeds the admin
Access grants panel and the My organization people lists."""
import json
import re

from app.models.va_selectives import ROLE_LABELS, VaAccessRoles
from app.services import organization_service as org
from tests.base import BaseTestCase


class RoleLabelsTests(BaseTestCase):
    def test_every_role_has_a_label(self):
        self.assertEqual(set(ROLE_LABELS), {r.value for r in VaAccessRoles})

    def test_admin_panel_renders_shared_labels(self):
        self._login(str(self.base_admin_id))
        html = self.client.get("/admin/panels/access-grants").get_data(as_text=True)
        match = re.search(r"var ROLE_LABEL = (\{.*?\});", html)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), ROLE_LABELS)

    def test_organization_service_uses_shared_labels(self):
        self.assertIs(org.ROLE_LABELS, ROLE_LABELS)
