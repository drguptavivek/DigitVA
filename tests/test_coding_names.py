"""The deceased's name on the coding screens (digitva-8kka). Policy:
docs/policy/coding-workflow-state-machine.md "Names on the coding screens"."""
import uuid
from unittest import mock
from datetime import UTC, datetime

import sqlalchemy as sa
from flask import g

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaStatuses,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services.case_list_service import coding_names
from app.utils.pii_crypto import PiiCryptoError
from app.services.coder_workflow_service import get_pick_available_forms, get_pick_available_page
from tests.base import BaseTestCase
from tests.test_self_coding import SelfCodingFixture


class CodingNamesTests(SelfCodingFixture, BaseTestCase):

    def setUp(self):
        super().setUp()
        self.pii_coder = self._get_or_make_user("cn.pii.coder@test.local", "CnPii123")
        for role in (VaAccessRoles.coder, VaAccessRoles.collaborator_pii):
            db.session.add(VaUserAccessGrants(
                user_id=self.pii_coder.user_id, role=role,
                scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()
        self._n = 0

    def _case(self, sid, name, owner=None):
        """A pick-list case with a register row; *owner* submitted the web interview."""
        if owner is not None:
            self._own_case(sid, owner=owner)
        else:
            self._submission(sid)
        self._n += 1
        db.session.add(VaDeathRegister(
            project_id=self.PROJECT, site_id=self.SITE, death_number=900 + self._n,
            unique_id=f"CN-{uuid.uuid4().hex[:8]}", deceased_name=name, has_deceased_name=True,
            deceased_sex="female", date_of_death=datetime.now(UTC).date(),
            registered_by=self.other.user_id, source="direct", va_sid=sid,
        ))
        db.session.commit()

    def _names(self, user):
        forms = get_pick_available_forms(user, list(user.get_coder_va_forms()))
        return {f["va_sid"]: f["deceased_name"] for f in forms}

    def test_pii_coder_sees_names_outside_self_coding(self):
        self._set_project(self_coding_enabled=False)
        self._case("csc-a", "Asha Rao")
        self.assertEqual(self._names(self.pii_coder), {"csc-a": "Asha Rao"})

    def test_plain_coder_sees_no_name(self):
        self._set_project(self_coding_enabled=False)
        self._case("csc-a", "Asha Rao")
        self.assertEqual(self._names(self.other), {"csc-a": None})

    def test_submitter_sees_only_own_case_in_self_coding_project(self):
        self._case("csc-mine", "Asha Rao", owner=self.submitter)
        self._case("csc-theirs", "Bela Das", owner=self.other)
        self.assertEqual(self._names(self.submitter), {"csc-mine": "Asha Rao", "csc-theirs": None})
        self.assertEqual(self._names(self.other), {"csc-mine": None, "csc-theirs": "Bela Das"})

    def test_submitter_without_pii_sees_nothing_when_not_self_coding(self):
        self._case("csc-mine", "Asha Rao", owner=self.submitter)
        self._set_project(self_coding_enabled=False)
        self.assertEqual(self._names(self.submitter), {"csc-mine": None})

    def test_case_without_register_row_has_no_name(self):
        self._submission("csc-odk")
        self.assertEqual(self._names(self.pii_coder), {"csc-odk": None})

    def test_page_query_count_does_not_grow_with_rows(self):
        self._set_project(self_coding_enabled=False)
        for i in range(5):
            self._case(f"csc-{i}", f"Name {i}")
        coding_names(self.pii_coder, ["csc-0"])  # warm the grant caches
        counts = []
        for size in (1, 5):
            statements = []
            def record(conn, cursor, statement, *a):
                statements.append(statement)
            sids = [f"csc-{i}" for i in range(size)]
            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                result = coding_names(self.pii_coder, sids)
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            self.assertEqual(len(result), size)
            counts.append(len(statements))
        self.assertEqual(counts[0], counts[1])

    def test_allocation_and_page_carry_the_name(self):
        self._case("csc-mine", "Asha Rao", owner=self.submitter)
        forms, _ = get_pick_available_page(
            self.submitter, list(self.submitter.get_coder_va_forms()), limit=10, offset=0)
        self.assertEqual(forms[0]["deceased_name"], "Asha Rao")
        self._hold("csc-mine", self.submitter)
        g.pop("_login_user", None)
        self._login(str(self.submitter.user_id))
        body = self.client.get("/api/v1/coding/allocation").get_json()
        self.assertEqual(body["allocation"]["deceased_name"], "Asha Rao")

    def test_admin_with_pii_sees_names(self):
        self._set_project(self_coding_enabled=False)
        self._case("csc-a", "Asha Rao")
        admin = db.session.get(type(self.pii_coder), self.base_admin_id)
        self.assertEqual(coding_names(admin, ["csc-a"]), {"csc-a": "Asha Rao"})

    def test_draft_not_submitted_gives_no_name(self):
        self._case("csc-mine", "Asha Rao", owner=self.submitter)
        db.session.execute(sa.update(VaWebIntakeDraft).values(status="draft"))
        db.session.commit()
        self.assertEqual(self._names(self.submitter), {"csc-mine": None})

    def test_intake_off_gives_submitter_no_name(self):
        self._case("csc-mine", "Asha Rao", owner=self.submitter)
        self._set_project(web_intake_mode="off")
        self.assertEqual(coding_names(self.submitter, ["csc-mine"]), {})

    def test_crypto_failure_on_one_row_names_the_others(self):
        self._set_project(self_coding_enabled=False)
        self._case("csc-a", "Asha Rao")
        self._case("csc-b", "Bela Das")
        from app.services import register_pii_accessor as accessor
        real = accessor.open_register_pii

        def flaky(rows, **kw):
            if rows[0].va_sid == "csc-a":
                raise PiiCryptoError("row x")
            return real(rows, **kw)

        with mock.patch.object(accessor, "open_register_pii", flaky):
            self.assertEqual(coding_names(self.pii_coder, ["csc-a", "csc-b"]), {"csc-b": "Bela Das"})

    def test_coding_api_responses_are_no_store(self):
        self._case("csc-mine", "Asha Rao", owner=self.submitter)
        self._hold("csc-mine", self.submitter)
        g.pop("_login_user", None)
        self._login(str(self.submitter.user_id))
        for path in ("/api/v1/coding/available", "/api/v1/coding/allocation"):
            self.assertEqual(self.client.get(path).headers.get("Cache-Control"), "no-store", path)
