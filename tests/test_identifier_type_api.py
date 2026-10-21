"""Registration identifier types: configuration API, audit, intake read, re-wrap job.

Policy: docs/policy/death-registration-identifiers.md ("Tests": Type save).
"""
import uuid
from datetime import UTC, date, datetime
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.commands.pii import rewrap_pending
from app.models import (
    MapDeathIdentifier,
    MapIdentifierAudit,
    MasDeathIdentifierType,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services.death_identifier_rules import clean_type_fields
from app.services.identifier_type_service import supervises_project
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.utils import pii_crypto
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

PROJECT = "IDT01"
OTHER = "IDT02"
SITE = "IT01"
ROLE = VaAccessRoles


def _url(project=PROJECT, type_id=None):
    base = f"/api/v1/projects/{project}/identifier-types"
    return f"{base}/{type_id}" if type_id else base


class IdentifierTypeApiTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (PROJECT, OTHER):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, web_intake_mode="both",
            ))
        db.session.add(VaSiteMaster(
            site_id=SITE, site_name=SITE, site_abbr=SITE, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=PROJECT, site_id=SITE, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(PROJECT, SITE)
        db.session.add(VaForms(
            form_id=f"{PROJECT}{SITE}01", project_id=PROJECT, site_id=SITE, odk_form_id="ODK_IDT",
            odk_project_id="7", form_type="WHO VA 2022", form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        cls.users = {}
        for name, role, project in (
            ("pi", ROLE.project_pi, PROJECT),
            ("dm", ROLE.data_manager, PROJECT),
            ("other_pi", ROLE.project_pi, OTHER),
            ("other_dm", ROLE.data_manager, OTHER),
            ("interviewer", ROLE.interviewer, PROJECT),
            ("coder", ROLE.coder, PROJECT),
        ):
            user = cls._get_or_make_user(f"idt.{name}@test.local", "IdentTypes123")
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
                project_id=project, notes="identifier type test", grant_status=VaStatuses.active,
            ))
            cls.users[name] = user
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()  # in-memory buckets outlive a test; the create route allows 30 a minute

    BODY = {"code": "mccd", "label": "MCCD number", "min_length": 6, "max_length": 20,
            "char_type": "letters_digits_hyphen_slash", "pattern": r"MCCD/\d{4}/\d{6}",
            "example": "mccd/2026/000123"}

    def as_user(self, name):
        user = self.base_admin_user if name == "admin" else self.users[name]
        self._login(str(user.user_id))

    def post(self, body=None, project=PROJECT, csrf=True):
        return self.client.post(_url(project), json=body if body is not None else self.BODY,
                                headers=self._csrf_headers() if csrf else {})

    def create(self, **overrides):
        self.as_user("pi")
        response = self.post({**self.BODY, **overrides})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()["identifier_type"]

    def audit_rows(self, project=PROJECT):
        return db.session.scalars(
            sa.select(MapIdentifierAudit).where(MapIdentifierAudit.project_id == project)
            .order_by(MapIdentifierAudit.created_at)
        ).all()

    # -- who may configure ------------------------------------------------

    def test_admin_project_pi_and_data_manager_may_create_each_with_one_audit_row(self):
        for index, (who, role) in enumerate((("admin", "admin"), ("pi", "project_pi"), ("dm", "data_manager"))):
            self.as_user(who)
            response = self.post({**self.BODY, "code": f"mccd{index}"})
            self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
            created = response.get_json()["identifier_type"]
            self.assertEqual(created["example"], "MCCD/2026/000123")  # stored capitalised
            rows = [r for r in self.audit_rows() if str(r.identifier_type_id) == created["identifier_type_id"]]
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0].event, rows[0].actor_role), ("type_created", role))
        self.assertEqual(len(self.audit_rows()), 3)

    def test_other_projects_pi_gets_404_and_coder_or_interviewer_403(self):
        self.as_user("pi")
        self.assertEqual(self.client.get(_url()).status_code, 200)  # subject present first
        for who in ("other_pi", "other_dm"):
            self.as_user(who)
            self.assertEqual(self.client.get(_url()).status_code, 404, who)
            self.assertEqual(self.post().status_code, 404, who)
        for who in ("coder", "interviewer"):
            self.as_user(who)
            self.assertEqual(self.client.get(_url()).status_code, 403, who)
            self.assertEqual(self.post().status_code, 403, who)
        self.assertEqual(self.audit_rows(), [])

    def test_unknown_project_is_404_and_anonymous_is_401(self):
        self.as_user("admin")
        self.assertEqual(self.client.get(_url("NOPE99")).status_code, 404)
        from flask import g

        g.pop("_login_user", None)
        self.client = self.app.test_client()
        self.assertEqual(self.client.get(_url()).status_code, 401)

    def test_create_without_csrf_token_is_refused(self):
        self.as_user("pi")
        response = self.post(csrf=False)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertEqual(db.session.scalars(sa.select(MasDeathIdentifierType)).all(), [])

    # -- type save --------------------------------------------------------

    def test_refusals_are_400_and_write_nothing(self):
        self.as_user("pi")
        self.assertEqual(self.post({**self.BODY, "code": "ok1"}).status_code, 201)  # subject present
        before = len(self.audit_rows())
        bad = {
            "min above max": {"min_length": 30},
            "unknown char type": {"char_type": "hex"},
            "example fails length": {"example": "MCCD"},
            "example fails character type": {"example": "MCCD#2026#000123"},
            "example fails pattern": {"example": "MCCX/2026/000123"},
            "backreference": {"pattern": r"(\d)\1", "example": None},
            "lookaround": {"pattern": r"(?=\d)\d+", "example": None},
            "nested quantifier": {"pattern": r"(\d+)+", "example": None},
            "repeat over 64": {"pattern": r"\d{1,1000}", "example": None},
            "pattern too long": {"pattern": "A" * 201, "example": None},
            "bad code": {"code": "Bad-Code"},
            "unknown field": {"project_id": "OTHER1"},
        }
        for name, change in bad.items():
            with self.subTest(name):
                response = self.post({**self.BODY, **change})
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
                self.assertEqual(response.get_json()["code"], "invalid_request")
        self.assertEqual(len(self.audit_rows()), before)

    def test_each_char_type_is_accepted(self):
        self.as_user("pi")
        for index, char_type in enumerate(("digits", "letters", "letters_digits", "letters_digits_hyphen_slash")):
            body = {"code": f"t{index}", "label": char_type, "char_type": char_type}
            self.assertEqual(self.post(body).status_code, 201, char_type)

    def test_duplicate_code_in_a_project_is_refused_but_allowed_in_another(self):
        self.create()
        self.as_user("pi")
        self.assertEqual(self.post().status_code, 409)
        self.as_user("other_pi")
        self.assertEqual(self.post(project=OTHER).status_code, 201)

    # -- update -----------------------------------------------------------

    def test_update_audits_old_and_new_and_never_values(self):
        created = self.create()
        self.as_user("dm")
        response = self.client.put(_url(type_id=created["identifier_type_id"]),
                                   json={"label": "Medical certificate", "required_at_report": True},
                                   headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        updated = self.audit_rows()[-1]
        self.assertEqual(updated.event, "type_updated")
        self.assertEqual(updated.actor_role, "data_manager")
        self.assertEqual(updated.details, {
            "label": {"old": "MCCD number", "new": "Medical certificate"},
            "required_at_report": {"old": False, "new": True},
        })

    def test_update_with_no_effective_change_writes_no_audit_row(self):
        created = self.create()
        type_id = created["identifier_type_id"]
        self.as_user("pi")
        before = len(self.audit_rows())
        self.assertEqual(before, 1)  # the create row is there
        same = self.client.put(_url(type_id=type_id), json={"label": created["label"], "min_length": 6},
                               headers=self._csrf_headers())
        self.assertEqual(same.status_code, 200)
        self.assertEqual(same.get_json()["identifier_type"]["label"], created["label"])
        self.assertEqual(len(self.audit_rows()), before)
        changed = self.client.put(_url(type_id=type_id), json={"min_length": 7}, headers=self._csrf_headers())
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(len(self.audit_rows()), before + 1)

    def test_char_type_of_the_wrong_json_type_is_400_on_create_and_update(self):
        created = self.create()
        self.as_user("pi")
        for bad in (["digits"], {"a": 1}):
            with self.subTest(bad=bad):
                self.assertEqual(self.post({**self.BODY, "code": "other", "char_type": bad}).status_code, 400)
                put = self.client.put(_url(type_id=created["identifier_type_id"]), json={"char_type": bad},
                                      headers=self._csrf_headers())
                self.assertEqual(put.status_code, 400, put.get_data(as_text=True))
                self.assertEqual(put.get_json()["code"], "invalid_request")

    def test_update_can_deactivate_and_is_checked_as_a_whole(self):
        created = self.create()
        type_id = created["identifier_type_id"]
        self.as_user("pi")
        refused = self.client.put(_url(type_id=type_id), json={"max_length": 8}, headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 400)  # the stored example no longer fits
        ok = self.client.put(_url(type_id=type_id), json={"is_active": False}, headers=self._csrf_headers())
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(ok.get_json()["identifier_type"]["is_active"])

    def test_update_of_a_type_in_another_project_is_404(self):
        created = self.create()
        self.as_user("other_pi")
        response = self.client.put(_url(OTHER, created["identifier_type_id"]), json={"label": "x"},
                                   headers=self._csrf_headers())
        self.assertEqual(response.status_code, 404)

    def test_code_cannot_change_once_values_exist(self):
        created = self.create()
        type_id = created["identifier_type_id"]
        self.as_user("pi")
        free = self.client.put(_url(type_id=type_id), json={"code": "mccd_new"}, headers=self._csrf_headers())
        self.assertEqual(free.status_code, 200)  # no values yet: allowed
        self.add_value(uuid.UUID(type_id), "MCCD/2026/000123")
        locked = self.client.put(_url(type_id=type_id), json={"code": "mccd_other"}, headers=self._csrf_headers())
        self.assertEqual(locked.status_code, 409)
        self.assertEqual(locked.get_json()["code"], "code_locked")
        label_only = self.client.put(_url(type_id=type_id), json={"label": "Renamed"}, headers=self._csrf_headers())
        self.assertEqual(label_only.status_code, 200)

    def test_there_is_no_delete(self):
        created = self.create()
        self.as_user("pi")
        response = self.client.delete(_url(type_id=created["identifier_type_id"]), headers=self._csrf_headers())
        self.assertEqual(response.status_code, 405)

    # -- intake read ------------------------------------------------------

    def test_intake_lists_only_active_types_with_the_documented_fields(self):
        kept = self.create(code="crs", label="CRS", example=None, pattern=None, sort_order=2)
        gone = self.create(code="old", label="Old", example=None, pattern=None, sort_order=1)
        self.as_user("pi")
        self.client.put(_url(type_id=gone["identifier_type_id"]), json={"is_active": False},
                        headers=self._csrf_headers())
        for who in ("dm", "interviewer"):
            self.as_user(who)
            response = self.client.get(f"/api/v1/intake/identifier-types?project_id={PROJECT.lower()}")
            self.assertEqual(response.status_code, 200, (who, response.get_data(as_text=True)))
            types = response.get_json()["identifier_types"]
            self.assertEqual([t["code"] for t in types], ["crs"], who)  # present, and the inactive one absent
            self.assertEqual(set(types[0]), {
                "code", "label", "min_length", "max_length", "char_type", "pattern", "example",
                "required_at_report", "sort_order"})
        self.assertEqual(kept["code"], "crs")

    def test_intake_refuses_other_projects_and_non_intake_roles(self):
        self.create(code="crs", label="CRS", example=None, pattern=None)
        self.as_user("dm")
        self.assertEqual(self.client.get(f"/api/v1/intake/identifier-types?project_id={OTHER}").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/intake/identifier-types").status_code, 400)
        self.as_user("interviewer")
        self.assertEqual(self.client.get(f"/api/v1/intake/identifier-types?project_id={OTHER}").status_code, 403)
        self.as_user("coder")
        self.assertEqual(self.client.get(f"/api/v1/intake/identifier-types?project_id={PROJECT}").status_code, 403)

    # -- values and the re-wrap job --------------------------------------

    def death(self):
        death = VaDeathRegister(
            project_id=PROJECT, site_id=SITE, death_number=uuid.uuid4().int % 10**9,
            unique_id=f"IDT-{uuid.uuid4().hex[:12]}", deceased_name="Test Case", deceased_sex="female",
            date_of_death=date(2026, 1, 1), registered_by=self.users["interviewer"].user_id,
            source="register", status="registered",
        )
        db.session.add(death)
        db.session.flush()
        return death

    def add_value(self, type_id, value):
        death = self.death()
        aad = death.death_id.bytes + type_id.bytes
        ciphertext, wrapped, key_id = pii_crypto.encrypt_value(value, aad)
        row = MapDeathIdentifier(
            death_id=death.death_id, identifier_type_id=type_id, value_ciphertext=ciphertext,
            dek_wrapped=wrapped, value_blind_index=pii_crypto.blind_index(type_id.bytes, value),
            key_id=key_id, entered_by=self.users["interviewer"].user_id,
        )
        db.session.add(row)
        db.session.flush()
        return row, aad

    def test_rewrap_job_moves_rows_to_the_new_key_and_leaves_ciphertext_untouched(self):
        type_id = uuid.UUID(self.create(code="crs", label="CRS", example=None, pattern=None)["identifier_type_id"])
        values = ["CRS-0001", "CRS-0002", "CRS-0003"]
        rows = [self.add_value(type_id, v) for v in values]
        before = {r.death_identifier_id: (r.value_ciphertext, r.dek_wrapped) for r, _ in rows}
        for row, _ in rows:  # no plaintext in any stored column (the rows exist: checked first)
            self.assertEqual(db.session.get(MapDeathIdentifier, row.death_identifier_id).key_id, row.key_id)
            for column in (row.value_ciphertext, row.dek_wrapped, row.value_blind_index, row.key_id):
                self.assertFalse(any(v in column for v in values))

        old = self.app.extensions["pii_keyring"]
        new_public, new_private = pii_crypto.generate_keyset("rot2")
        rotated = pii_crypto.Keyring(new_public, {**old.private, "rot2": new_private}, old.blind_key)
        with mock.patch.dict(self.app.extensions, {"pii_keyring": rotated}):
            with self.assertLogs("app.commands.pii", level="INFO") as logs:
                counts = rewrap_pending(batch_size=2)
            self.assertEqual(counts, {"rewrapped": 3, "failed": 0, "skipped": 0})
            self.assertFalse(any(v in "\n".join(logs.output) for v in values))
            self.assertEqual(rewrap_pending(), {"rewrapped": 0, "failed": 0, "skipped": 0})  # idempotent
        db.session.expire_all()
        for row, aad in rows:
            fresh = db.session.get(MapDeathIdentifier, row.death_identifier_id)
            self.assertEqual(fresh.key_id, "rot2")
            self.assertEqual(fresh.value_ciphertext, before[row.death_identifier_id][0])
            self.assertNotEqual(fresh.dek_wrapped, before[row.death_identifier_id][1])

        # The old private key is dropped: every row still reads.
        new_only = pii_crypto.Keyring(new_public, {"rot2": new_private}, old.blind_key)
        with mock.patch.dict(self.app.extensions, {"pii_keyring": new_only}):
            for (row, aad), value in zip(rows, values):
                fresh = db.session.get(MapDeathIdentifier, row.death_identifier_id)
                self.assertEqual(
                    pii_crypto.decrypt_value(fresh.value_ciphertext, fresh.dek_wrapped, aad, row_ref="t"), value)

    def test_rewrap_job_counts_a_row_it_cannot_unwrap_and_continues(self):
        type_id = uuid.UUID(self.create(code="crs", label="CRS", example=None, pattern=None)["identifier_type_id"])
        row, _ = self.add_value(type_id, "CRS-0009")
        old = self.app.extensions["pii_keyring"]
        new_public, new_private = pii_crypto.generate_keyset("rot3")
        lost = pii_crypto.Keyring(new_public, {"rot3": new_private}, old.blind_key)  # old key not mounted
        with mock.patch.dict(self.app.extensions, {"pii_keyring": lost}):
            with self.assertLogs("app.commands.pii", level="ERROR") as logs:
                counts = rewrap_pending()
        self.assertEqual(counts, {"rewrapped": 0, "failed": 1, "skipped": 0})
        self.assertIn(str(row.death_identifier_id), "\n".join(logs.output))
        self.assertNotIn("CRS-0009", "\n".join(logs.output))

    def test_rewrap_job_does_not_overwrite_a_row_edited_after_it_was_read(self):
        type_id = uuid.UUID(self.create(code="crs", label="CRS", example=None, pattern=None)["identifier_type_id"])
        raced, _ = self.add_value(type_id, "CRS-0100")
        quiet, _ = self.add_value(type_id, "CRS-0200")
        raced_id, quiet_id = raced.death_identifier_id, quiet.death_identifier_id
        edited = pii_crypto.encrypt_value("CRS-0101", b"x" * 32)[1]  # a concurrent writer's new wrapped key
        old = self.app.extensions["pii_keyring"]
        new_public, new_private = pii_crypto.generate_keyset("rot4")
        rotated = pii_crypto.Keyring(new_public, {**old.private, "rot4": new_private}, old.blind_key)
        real_rewrap = pii_crypto.rewrap_dek

        def rewrap_after_a_concurrent_edit(dek_wrapped, *, row_ref):
            result = real_rewrap(dek_wrapped, row_ref=row_ref)
            if row_ref == str(raced_id):  # between the read and the write
                db.session.execute(sa.update(MapDeathIdentifier).where(
                    MapDeathIdentifier.death_identifier_id == raced_id).values(dek_wrapped=edited))
            return result

        with mock.patch.dict(self.app.extensions, {"pii_keyring": rotated}), \
                mock.patch.object(pii_crypto, "rewrap_dek", rewrap_after_a_concurrent_edit):
            counts = rewrap_pending()
        self.assertEqual(counts, {"rewrapped": 1, "failed": 0, "skipped": 1})
        db.session.expire_all()
        self.assertEqual(db.session.get(MapDeathIdentifier, quiet_id).key_id, "rot4")  # subject moved
        raced_now = db.session.get(MapDeathIdentifier, raced_id)
        self.assertEqual(raced_now.dek_wrapped, edited)  # the new row survives
        self.assertNotEqual(raced_now.key_id, "rot4")


class IntakeIdentifierTypesSupervisorTests(UnitScopeFixture, BaseTestCase):
    """GET /api/v1/intake/identifier-types for supervising roles: allowed inside
    their own project, 403 ``project_forbidden`` anywhere else.
    CSC001 is a tree project (District D01 > CHC C01 > PHC P01, P02)."""

    URL = "/api/v1/intake/identifier-types?project_id={}"

    def setUp(self):
        super().setUp()
        _, self.district, self.chc, self.phc_a, self.phc_b = self._tree()
        cleaned = clean_type_fields({"code": "crs", "label": "CRS"})
        db.session.add(MasDeathIdentifierType(project_id=self.PROJECT, **cleaned))
        db.session.commit()

    def project_user(self, key, role):
        user = self._get_or_make_user(f"idt.sup.{key}@test.local", "IdentSup123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def get(self, user, project):
        self._login(str(user.user_id))
        return self.client.get(self.URL.format(project))

    def assert_lists_crs(self, user):
        response = self.get(user, self.PROJECT)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual([t["code"] for t in response.get_json()["identifier_types"]], ["crs"])

    def assert_project_forbidden(self, user, project):
        response = self.get(user, project)
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["code"], "project_forbidden")

    def test_in_charge_at_a_unit_project_pi_on_a_tree_and_supervisor_may_read(self):
        incharge = self._user_with("idt.sup.incharge@test.local", VaAccessRoles.site_pi, self.phc_a)
        pi = self.project_user("pi", VaAccessRoles.project_pi)
        supervisor = self._user_with("idt.sup.supervisor@test.local", VaAccessRoles.interview_supervisor, self.chc)
        for user in (incharge, pi, supervisor):
            with self.subTest(user=user.email):
                self.assert_lists_crs(user)

    def test_the_same_users_are_forbidden_in_another_project(self):
        incharge = self._user_with("idt.sup.incharge2@test.local", VaAccessRoles.site_pi, self.phc_a)
        pi = self.project_user("pi2", VaAccessRoles.project_pi)
        supervisor = self._user_with("idt.sup.supervisor2@test.local", VaAccessRoles.interview_supervisor, self.chc)
        for user in (incharge, pi, supervisor):
            self.assert_lists_crs(user)  # the subject can read its own project first
            with self.subTest(user=user.email):
                self.assert_project_forbidden(user, "NOPE99")

    def test_supervises_project_counts_only_the_supervising_scopes(self):
        incharge = self._user_with("idt.sup.incharge3@test.local", VaAccessRoles.site_pi, self.phc_b)
        pi = self.project_user("pi3", VaAccessRoles.project_pi)
        pair_site_pi = self._get_or_make_user("idt.sup.pair@test.local", "IdentSup123")
        pair = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE))
        db.session.add(VaUserAccessGrants(
            user_id=pair_site_pi.user_id, role=VaAccessRoles.site_pi,
            scope_type=VaAccessScopeTypes.project_site, project_site_id=pair,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertTrue(supervises_project(incharge, self.PROJECT))
        self.assertTrue(supervises_project(pi, self.PROJECT))
        self.assertFalse(supervises_project(pair_site_pi, self.PROJECT))  # a classical site_pi is not a supervisor
        self.assertFalse(supervises_project(incharge, "NOPE99"))
        self.assertEqual(self.get(pair_site_pi, self.PROJECT).status_code, 403)

    def test_admin_reads_the_types_of_any_project(self):
        admin = self.base_admin_user
        self._login(str(admin.user_id))
        for project in (self.PROJECT, "NOPE99"):
            response = self.get(admin, project)
            self.assertEqual(response.status_code, 200, project)
        self.assertEqual([t["code"] for t in self.get(admin, self.PROJECT).get_json()["identifier_types"]], ["crs"])
        stranger = self._get_or_make_user("idt.sup.stranger@test.local", "IdentSup123")
        self.assertEqual(self.get(stranger, self.PROJECT).status_code, 403)  # no role at all

    def test_only_a_project_wide_data_manager_configures_types(self):
        config = f"/api/v1/projects/{self.PROJECT}/identifier-types"
        project_dm = self.project_user("dm_project", VaAccessRoles.data_manager)
        unit_dm = self._user_with("idt.sup.dm_unit@test.local", VaAccessRoles.data_manager, self.phc_a)
        pair = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE))
        site_dm = self._get_or_make_user("idt.sup.dm_site@test.local", "IdentSup123")
        db.session.add(VaUserAccessGrants(
            user_id=site_dm.user_id, role=VaAccessRoles.data_manager, scope_type=VaAccessScopeTypes.project_site,
            project_site_id=pair, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(project_dm.user_id))
        self.assertEqual(self.client.get(config).status_code, 200)  # subject present first
        body = {"code": "scoped", "label": "Scoped", "min_length": 4, "max_length": 8, "char_type": "digits"}
        created = self.client.post(config, json=body, headers=self._csrf_headers())
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        for name, user in (("unit", unit_dm), ("site", site_dm)):
            self._login(str(user.user_id))
            self.assertEqual(self.client.get(config).status_code, 403, name)
            refused = self.client.post(config, json={**body, "code": f"{name}code"}, headers=self._csrf_headers())
            self.assertEqual(refused.status_code, 403, name)
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(MasDeathIdentifierType).where(
                MasDeathIdentifierType.project_id == self.PROJECT, MasDeathIdentifierType.code.in_(("unitcode", "sitecode")))),
            0)
        # A project PI is unchanged, whatever the scope rule for the data manager.
        pi = self.project_user("pi_cfg", VaAccessRoles.project_pi)
        self._login(str(pi.user_id))
        self.assertEqual(self.client.get(config).status_code, 200)
