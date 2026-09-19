"""GET /api/v1/organization/<project_id>/form-options and its admin editing.

The contract under test is docs/policy/va-web-form-options.md: every tier-2
(per-project) option the VA web form needs is served from this endpoint, and
the four columns behind it are edited through the project settings PUT in
app/routes/admin.py.
"""
import uuid
from datetime import UTC, datetime

from app import db
from app.models import (
    MapProjectSiteOdk,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasLanguages,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.routes.api.organization import instrument_code_for
from app.services import organization_service as org
from tests.base import BaseTestCase


class FormOptionsApiTests(BaseTestCase):
    PROJECT = "FOPT01"
    SITE_A = "FA01"
    SITE_B = "FA02"
    OTHER_PROJECT = "FOPT03"
    URL = "/api/v1/organization/FOPT01/form-options"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Form Options Project",
                project_nickname="FormOpts",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                social_autopsy_enabled=False,
            )
        )
        for site_id, name in ((cls.SITE_A, "Form Options Site A"), (cls.SITE_B, "Form Options Site B")):
            db.session.add(
                VaSiteMaster(
                    site_id=site_id,
                    site_name=name,
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
            db.session.add(
                VaProjectSites(
                    project_id=cls.PROJECT,
                    site_id=site_id,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                )
            )
        db.session.flush()

        # Two form types: WIDE is linked to both sites, NARROW to one, so the
        # "most sites wins" default rule has something to decide.
        cls.wide = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="FOPT_WIDE",
            form_type_name="Form Options Wide",
            is_active=True,
        )
        cls.narrow = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="FOPT_NARROW",
            form_type_name="Form Options Narrow",
            is_active=True,
        )
        db.session.add_all([cls.wide, cls.narrow])
        db.session.flush()
        db.session.add_all([
            MapProjectSiteOdk(
                project_id=cls.PROJECT, site_id=cls.SITE_A,
                odk_project_id=901, odk_form_id="FOPT_WIDE_A",
                form_type_id=cls.wide.form_type_id,
            ),
            MapProjectSiteOdk(
                project_id=cls.PROJECT, site_id=cls.SITE_B,
                odk_project_id=901, odk_form_id="FOPT_WIDE_B",
                form_type_id=cls.wide.form_type_id,
            ),
            MapProjectSiteOdk(
                project_id=cls.PROJECT, site_id=cls.SITE_A,
                odk_project_id=901, odk_form_id="FOPT_NARROW_A",
                form_type_id=cls.narrow.form_type_id,
            ),
        ])

        for code, name, active in (
            ("fopt_en", "Form Options English", True),
            ("fopt_hi", "Form Options Hindi", True),
            ("fopt_old", "Form Options Retired", False),
        ):
            db.session.add(
                MasLanguages(language_code=code, language_name=name, is_active=active)
            )

        # A second active project, so "granted somewhere" can be told apart
        # from "granted on this project".
        db.session.add(
            VaProjectMaster(
                project_id=cls.OTHER_PROJECT,
                project_code=cls.OTHER_PROJECT,
                project_name="Form Options Other Project",
                project_nickname="FormOptsOther",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()

        # An organization tree on the project under test, so an org_unit-scoped
        # grant has something to hang off.
        org.seed_default_organization(cls.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.PROJECT)}
        district = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["district"].org_level_id,
            unit_code="FD1",
            unit_name="Form Options District",
        )
        cls.chc = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id,
            unit_code="FC1",
            unit_name="Form Options CHC",
        )
        db.session.commit()

        cls.granted_user = cls._get_or_make_user("fopt.granted@test.local", "FormOpts123")
        cls.no_grant_user = cls._get_or_make_user("fopt.nogrant@test.local", "FormOpts123")
        cls.unit_scoped_user = cls._get_or_make_user("fopt.unit@test.local", "FormOpts123")
        cls.other_project_user = cls._get_or_make_user("fopt.other@test.local", "FormOpts123")
        db.session.add_all([
            VaUserAccessGrants(
                user_id=cls.granted_user.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.project,
                project_id=cls.PROJECT,
                grant_status=VaStatuses.active,
            ),
            VaUserAccessGrants(
                user_id=cls.unit_scoped_user.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=cls.chc.org_unit_id,
                grant_status=VaStatuses.active,
            ),
            VaUserAccessGrants(
                user_id=cls.other_project_user.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.project,
                project_id=cls.OTHER_PROJECT,
                grant_status=VaStatuses.active,
            ),
        ])
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.project = db.session.get(VaProjectMaster, self.PROJECT)
        self.project.web_intake_default_locale = "fopt_en"
        self.project.web_intake_available_locales = None
        self.project.web_intake_narration_languages = None
        self.project.web_intake_show_guidance = False
        db.session.commit()

    # -- authorization ------------------------------------------------------

    def test_no_grant_on_project_is_refused(self):
        self._login(str(self.no_grant_user.user_id))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 403)

    def test_unit_scoped_grant_gets_the_same_project_wide_shape(self):
        """A grant anywhere inside the project's tree may read its options.

        The response is project configuration, identical for everyone who may
        see the project at all -- unlike ``/units`` it is not narrowed by what
        the grant reaches.
        """
        self._login(str(self.granted_user.user_id))
        project_scoped = self.client.get(self.URL).get_json()

        self._login(str(self.unit_scoped_user.user_id))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), project_scoped)

    def test_grant_on_another_project_is_refused_here(self):
        self._login(str(self.other_project_user.user_id))
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        # ... and the same user does reach the project they were granted.
        self.assertEqual(
            self.client.get(
                f"/api/v1/organization/{self.OTHER_PROJECT}/form-options"
            ).status_code,
            200,
        )

    def test_unauthenticated_request_is_refused(self):
        response = self.client.get(self.URL)
        self.assertIn(response.status_code, (302, 401))

    def test_missing_project_is_404(self):
        self._login(str(self.granted_user.user_id))
        self.assertEqual(
            self.client.get("/api/v1/organization/NOPE99/form-options").status_code, 404
        )

    # -- shape --------------------------------------------------------------

    def test_granted_user_gets_the_documented_shape(self):
        self._login(str(self.granted_user.user_id))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            set(payload),
            {
                "project_id", "config_version", "enabled_extensions", "form_types",
                "default_locale", "available_locales", "narration_languages",
                "show_guidance",
            },
        )
        self.assertEqual(payload["project_id"], self.PROJECT)
        self.assertIn("digitva_core", payload["enabled_extensions"])
        # social_autopsy is off on this project, and no narration languages
        # are configured by default.
        self.assertNotIn("social_autopsy", payload["enabled_extensions"])
        self.assertNotIn("narration_language", payload["enabled_extensions"])
        self.assertFalse(payload["show_guidance"])

    def test_form_types_come_from_the_mapping_with_one_default(self):
        self._login(str(self.granted_user.user_id))
        payload = self.client.get(self.URL).get_json()
        by_code = {ft["form_type_code"]: ft for ft in payload["form_types"]}
        self.assertEqual(set(by_code), {"FOPT_WIDE", "FOPT_NARROW"})
        self.assertEqual(by_code["FOPT_WIDE"]["title"], "Form Options Wide")
        # Neither code layers on a bundled standard instrument.
        self.assertIsNone(by_code["FOPT_WIDE"]["instrument_code"])
        self.assertIsNone(by_code["FOPT_NARROW"]["instrument_code"])
        self.assertEqual(
            [ft["form_type_code"] for ft in payload["form_types"] if ft["is_default"]],
            ["FOPT_WIDE"],
        )

    def test_abha_extension_follows_the_default_form_type_field_config(self):
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=self.wide.form_type_id,
                field_id="abha_number",
                is_active=True,
            )
        )
        db.session.commit()
        self._login(str(self.granted_user.user_id))
        payload = self.client.get(self.URL).get_json()
        self.assertIn("abha", payload["enabled_extensions"])

    # -- locales ------------------------------------------------------------

    def test_null_available_locales_means_every_active_language(self):
        self._login(str(self.granted_user.user_id))
        payload = self.client.get(self.URL).get_json()
        codes = {entry["code"] for entry in payload["available_locales"]}
        self.assertIn("fopt_en", codes)
        self.assertIn("fopt_hi", codes)
        self.assertNotIn("fopt_old", codes)
        self.assertIn(payload["default_locale"], codes)
        labels = {e["code"]: e["label"] for e in payload["available_locales"]}
        self.assertEqual(labels["fopt_hi"], "Form Options Hindi")

    def test_inactive_stored_default_falls_back_and_still_appears(self):
        self.project.web_intake_default_locale = "fopt_old"
        self.project.web_intake_available_locales = ["fopt_hi"]
        db.session.commit()

        self._login(str(self.granted_user.user_id))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["default_locale"], "fopt_hi")
        self.assertIn(
            payload["default_locale"],
            {entry["code"] for entry in payload["available_locales"]},
        )

    def test_unknown_narration_language_code_is_dropped(self):
        self.project.web_intake_narration_languages = ["fopt_hi", "fopt_old", "zz"]
        db.session.commit()

        self._login(str(self.granted_user.user_id))
        payload = self.client.get(self.URL).get_json()
        self.assertEqual(
            payload["narration_languages"],
            [{"code": "fopt_hi", "label": "Form Options Hindi"}],
        )
        self.assertIn("narration_language", payload["enabled_extensions"])

    # -- config_version -----------------------------------------------------

    def test_config_version_moves_when_a_setting_changes(self):
        self._login(str(self.granted_user.user_id))
        before = self.client.get(self.URL).get_json()["config_version"]
        self.assertIsNotNone(before)

        self.project.web_intake_show_guidance = True
        self.project.project_updated_at = datetime.now(UTC)
        db.session.commit()

        after = self.client.get(self.URL).get_json()
        self.assertNotEqual(after["config_version"], before)
        self.assertTrue(after["show_guidance"])


class FormOptionsAdminEditingTests(BaseTestCase):
    PROJECT = "FOPT02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Form Options Admin Project",
                project_nickname="FormOptsAdmin",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        for code, name, active in (
            ("fopt2_en", "Admin English", True),
            ("fopt2_hi", "Admin Hindi", True),
            ("fopt2_old", "Admin Retired", False),
        ):
            db.session.add(
                MasLanguages(language_code=code, language_name=name, is_active=active)
            )
        db.session.commit()

    def _put(self, payload):
        self._login(str(self.base_admin_user.user_id))
        return self.client.put(
            f"/admin/api/projects/{self.PROJECT}",
            json=payload,
            headers=self._csrf_headers(),
        )

    def test_put_sets_the_four_web_intake_form_option_fields(self):
        response = self._put({
            "web_intake_default_locale": "fopt2_hi",
            "web_intake_available_locales": ["fopt2_en", "fopt2_hi"],
            "web_intake_narration_languages": ["fopt2_hi"],
            "web_intake_show_guidance": True,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        project = response.get_json()["project"]
        self.assertEqual(project["web_intake_default_locale"], "fopt2_hi")
        self.assertEqual(
            project["web_intake_available_locales"], ["fopt2_en", "fopt2_hi"]
        )
        self.assertEqual(project["web_intake_narration_languages"], ["fopt2_hi"])
        self.assertTrue(project["web_intake_show_guidance"])

    def test_put_rejects_an_inactive_default_locale(self):
        response = self._put({"web_intake_default_locale": "fopt2_old"})
        self.assertEqual(response.status_code, 400)

    def test_put_rejects_an_inactive_code_in_a_list(self):
        response = self._put({"web_intake_available_locales": ["fopt2_old"]})
        self.assertEqual(response.status_code, 400)

    def test_put_rejects_a_non_list_locale_field_and_keeps_the_stored_value(self):
        self.assertEqual(
            self._put({"web_intake_available_locales": ["fopt2_en"]}).status_code, 200
        )
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaProjectMaster, self.PROJECT).web_intake_available_locales,
            ["fopt2_en"],
        )

        response = self._put({"web_intake_available_locales": "fopt2_hi"})
        self.assertEqual(response.status_code, 400)
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaProjectMaster, self.PROJECT).web_intake_available_locales,
            ["fopt2_en"],
        )

    def test_put_rejects_a_list_holding_a_non_string(self):
        response = self._put({"web_intake_available_locales": ["fopt2_en", 7]})
        self.assertEqual(response.status_code, 400)

    def test_empty_narration_list_stores_empty_and_disables_the_extension(self):
        """``[]`` is "offer none", distinct from NULL only in how it was set.

        Positive control first: a real code must turn the extension on, so the
        cleared case proves the clearing and not a fixture that never worked.
        """
        self.assertEqual(
            self._put({"web_intake_narration_languages": ["fopt2_hi"]}).status_code, 200
        )
        self._login(str(self.base_admin_user.user_id))
        payload = self.client.get(
            f"/api/v1/organization/{self.PROJECT}/form-options"
        ).get_json()
        self.assertEqual(
            payload["narration_languages"],
            [{"code": "fopt2_hi", "label": "Admin Hindi"}],
        )
        self.assertIn("narration_language", payload["enabled_extensions"])

        self.assertEqual(
            self._put({"web_intake_narration_languages": []}).status_code, 200
        )
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaProjectMaster, self.PROJECT).web_intake_narration_languages,
            [],
        )
        payload = self.client.get(
            f"/api/v1/organization/{self.PROJECT}/form-options"
        ).get_json()
        self.assertEqual(payload["narration_languages"], [])
        self.assertNotIn("narration_language", payload["enabled_extensions"])


class InstrumentCodeHelperTests(BaseTestCase):
    """``instrument_code_for`` — the layer-to-instrument naming convention.

    A DigitVA form type is a layer on a standard instrument, so every
    ``WHO_2022_VA*`` code must resolve to the one bundled WHO 2022 instrument.
    """

    def test_the_exact_code_resolves_to_itself(self):
        self.assertEqual(instrument_code_for("WHO_2022_VA"), "WHO_2022_VA")

    def test_a_layer_code_resolves_to_the_standard_instrument(self):
        self.assertEqual(instrument_code_for("WHO_2022_VA_SOCIAL"), "WHO_2022_VA")
        self.assertEqual(instrument_code_for("WHO_2022_VA_2026"), "WHO_2022_VA")

    def test_an_unrelated_code_has_no_bundled_instrument(self):
        self.assertIsNone(instrument_code_for("PHMRC_2016"))
        self.assertIsNone(instrument_code_for(None))


class FormOptionsInstrumentCodeTests(BaseTestCase):
    """A project whose default form type is a WHO 2022 layer.

    ``WHO_2022_VA_SOCIAL`` is not a separate questionnaire: the endpoint must
    serve it the standard instrument it layers on, so the intake page renders
    rather than refusing it.
    """

    PROJECT = "FOPT04"
    SITE = "FA04"
    URL = "/api/v1/organization/FOPT04/form-options"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Form Options Social Project",
                project_nickname="FormOptsSocial",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id=cls.SITE,
                site_name="Form Options Social Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.flush()

        # The social layer may already be registered by the seed; reuse it
        # rather than colliding on the unique form_type_code.
        social = db.session.execute(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA_SOCIAL"
            )
        ).scalar_one_or_none()
        if social is None:
            social = MasFormTypes(
                form_type_id=uuid.uuid4(),
                form_type_code="WHO_2022_VA_SOCIAL",
                form_type_name="WHO 2022 VA with social autopsy",
                is_active=True,
            )
            db.session.add(social)
            db.session.flush()
        db.session.add(
            MapProjectSiteOdk(
                project_id=cls.PROJECT, site_id=cls.SITE,
                odk_project_id=904, odk_form_id="FOPT_SOCIAL_A",
                form_type_id=social.form_type_id,
            )
        )
        cls.social_user = cls._get_or_make_user("fopt.social@test.local", "FormOpts123")
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.social_user.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.project,
                project_id=cls.PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def test_the_social_layer_is_served_the_standard_instrument(self):
        self._login(str(self.social_user.user_id))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        default = next(
            ft for ft in response.get_json()["form_types"] if ft["is_default"]
        )
        self.assertEqual(default["form_type_code"], "WHO_2022_VA_SOCIAL")
        self.assertEqual(default["instrument_code"], "WHO_2022_VA")
