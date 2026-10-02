"""A data manager's or viewer's project grant stops at a deactivated
(project, site) pair, on every surface (digitva-0wc stage 3 review)."""

import uuid

import sqlalchemy as sa

from app import db
from app.models import VaForms
from app.services.data_management_service import _dm_visible_forms_condition
from tests.authz.fixture import FORMS, AuthzFixtureMixin
from tests.base import BaseTestCase


class InactivePairTests(AuthzFixtureMixin, BaseTestCase):
    def _visible_forms(self, key):
        return set(db.session.scalars(
            sa.select(VaForms.form_id).where(_dm_visible_forms_condition(self.user(key)))
        ))

    def test_filter_options_skip_a_deactivated_pair(self):
        active, inactive = FORMS["sp1"][0], FORMS["sp4"][0]
        for key in ("dm_sp", "collabpii_sp"):
            with self.subTest(user=key):
                forms = self._visible_forms(key)
                self.assertIn(active, forms)
                self.assertNotIn(inactive, forms)


class VanishedRequesterTests(BaseTestCase):
    def test_a_sync_whose_requester_is_gone_is_refused(self):
        from app.tasks.sync_tasks import _get_request_user

        self.assertIsNone(_get_request_user(None))  # system-triggered run
        with self.assertRaises(PermissionError):
            _get_request_user(uuid.uuid4())
