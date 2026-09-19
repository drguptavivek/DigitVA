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
        self.project.web_intake_default_locale = "en"
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
                "show_guidance", "intake_note",
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

    def test_null_available_locales_means_every_instrument_locale(self):
        """NULL offers what the bundled questionnaire has, not ``mas_languages``.

        Today the WHO 2022 bundle carries English only, so an active language
        row is *not* enough to make a code a web form language.
        """
        self._login(str(self.granted_user.user_id))
        payload = self.client.get(self.URL).get_json()
        self.assertEqual(
            payload["available_locales"], [{"code": "en", "label": "English"}]
        )
        self.assertEqual(payload["default_locale"], "en")

    def test_default_locale_is_en_with_no_matching_language_row(self):
        """The form opens in ``en`` even though no ``mas_languages`` row says so.

        This is the bug the 2026-09-19 decision fixes: ``mas_languages`` on a
        seeded install holds ``english``/``hindi``, never ``en``, and the old
        resolver read that as "``en`` is not a language" and opened the form in
        whichever code sorted first.
        """
        self.assertIsNone(
            db.session.get(MasLanguages, "en"),
            "fixture guard: this test is about there being no 'en' row",
        )
        self._login(str(self.granted_user.user_id))
        payload = self.client.get(self.URL).get_json()
        self.assertEqual(payload["default_locale"], "en")

    def test_stored_codes_the_instrument_cannot_render_are_dropped(self):
        """Positive control first: the base locale survives, ``zz`` does not."""
        self.project.web_intake_available_locales = ["en"]
        db.session.commit()
        self._login(str(self.granted_user.user_id))
        self.assertEqual(
            self.client.get(self.URL).get_json()["available_locales"],
            [{"code": "en", "label": "English"}],
        )

        self.project.web_intake_available_locales = ["zz"]
        db.session.commit()
        self.assertEqual(
            self.client.get(self.URL).get_json()["available_locales"],
            [{"code": "en", "label": "English"}],
        )

    def test_a_stored_list_of_language_codes_serves_only_the_base_locale(self):
        """``mas_languages`` codes are narration codes; the screen cannot use them."""
        self.project.web_intake_available_locales = ["fopt_en", "fopt_hi"]
        db.session.commit()

        self._login(str(self.granted_user.user_id))
        payload = self.client.get(self.URL).get_json()
        self.assertEqual(
            payload["available_locales"], [{"code": "en", "label": "English"}]
        )

    def test_a_stored_default_the_instrument_lacks_resolves_to_en(self):
        self.project.web_intake_default_locale = "fopt_old"
        self.project.web_intake_available_locales = ["fopt_hi"]
        db.session.commit()

        self._login(str(self.granted_user.user_id))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["default_locale"], "en")
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
            "web_intake_default_locale": "en",
            "web_intake_available_locales": ["en"],
            "web_intake_narration_languages": ["fopt2_hi"],
            "web_intake_show_guidance": True,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        project = response.get_json()["project"]
        self.assertEqual(project["web_intake_default_locale"], "en")
        self.assertEqual(project["web_intake_available_locales"], ["en"])
        self.assertEqual(project["web_intake_narration_languages"], ["fopt2_hi"])
        self.assertTrue(project["web_intake_show_guidance"])

    def test_put_takes_the_base_locale_and_rejects_a_language_code(self):
        """Positive control first, so the rejection is not a broken payload."""
        self.assertEqual(
            self._put({"web_intake_default_locale": "en"}).status_code, 200
        )
        self.assertEqual(
            self._put({"web_intake_default_locale": "fopt2_hi"}).status_code, 400
        )
        self.assertEqual(
            self._put({"web_intake_default_locale": "fopt2_old"}).status_code, 400
        )

    def test_put_rejects_an_untranslated_code_in_the_available_list(self):
        """An active ``mas_languages`` code is still not a web form language."""
        self.assertEqual(
            self._put({"web_intake_available_locales": ["en"]}).status_code, 200
        )

        response = self._put({"web_intake_available_locales": ["fopt2_hi"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["error"],
            "web_intake_available_locales contains languages the questionnaire "
            "has no translations for: fopt2_hi.",
        )

    def test_put_accepts_an_active_narration_language_and_rejects_a_retired_one(self):
        self.assertEqual(
            self._put({"web_intake_narration_languages": ["fopt2_hi"]}).status_code,
            200,
        )
        response = self._put({"web_intake_narration_languages": ["fopt2_old"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("inactive language codes", response.get_json()["error"])

    def test_put_rejects_a_non_list_locale_field_and_keeps_the_stored_value(self):
        self.assertEqual(
            self._put({"web_intake_available_locales": ["en"]}).status_code, 200
        )
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaProjectMaster, self.PROJECT).web_intake_available_locales,
            ["en"],
        )

        response = self._put({"web_intake_available_locales": "en"})
        self.assertEqual(response.status_code, 400)
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaProjectMaster, self.PROJECT).web_intake_available_locales,
            ["en"],
        )

    def test_put_rejects_a_list_holding_a_non_string(self):
        response = self._put({"web_intake_available_locales": ["en", 7]})
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


class FormOptionsAdminCreationTests(BaseTestCase):
    """POST /admin/api/projects accepts the four tier-2 web form options.

    The Projects admin panel sets them on create as well as on edit, so the
    create route has to validate the same codes the update route does.
    """

    PROJECT = "FOPT05"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code, name, active in (
            ("fopt5_en", "Create English", True),
            ("fopt5_hi", "Create Hindi", True),
            ("fopt5_old", "Create Retired", False),
        ):
            db.session.add(
                MasLanguages(language_code=code, language_name=name, is_active=active)
            )
        db.session.commit()

    def _post(self, payload):
        self._login(str(self.base_admin_user.user_id))
        return self.client.post(
            "/admin/api/projects",
            json=payload,
            headers=self._csrf_headers(),
        )

    def _base_payload(self, project_id):
        return {
            "project_id": project_id,
            "project_name": "Form Options Created Project",
            "project_nickname": "FormOptsNew",
        }

    def test_post_creates_a_project_with_the_four_web_intake_form_option_fields(self):
        payload = self._base_payload(self.PROJECT)
        payload.update({
            "web_intake_default_locale": "en",
            "web_intake_available_locales": ["en"],
            "web_intake_narration_languages": ["fopt5_hi"],
            "web_intake_show_guidance": True,
        })
        response = self._post(payload)
        self.assertEqual(response.status_code, 201, response.get_json())

        served = response.get_json()["project"]
        self.assertEqual(served["web_intake_default_locale"], "en")
        self.assertEqual(served["web_intake_available_locales"], ["en"])
        self.assertEqual(served["web_intake_narration_languages"], ["fopt5_hi"])
        self.assertTrue(served["web_intake_show_guidance"])

        db.session.expire_all()
        stored = db.session.get(VaProjectMaster, self.PROJECT)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.web_intake_default_locale, "en")
        self.assertEqual(stored.web_intake_available_locales, ["en"])
        self.assertEqual(stored.web_intake_narration_languages, ["fopt5_hi"])
        self.assertTrue(stored.web_intake_show_guidance)

    def test_post_rejects_an_untranslated_locale_and_creates_nothing(self):
        """Positive control first, so the absence assertion is not vacuous."""
        control = self._base_payload("FOPT06")
        control["web_intake_default_locale"] = "en"
        self.assertEqual(self._post(control).status_code, 201)
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(VaProjectMaster, "FOPT06"))

        payload = self._base_payload(self.PROJECT)
        payload["web_intake_default_locale"] = "fopt5_hi"
        response = self._post(payload)
        self.assertEqual(response.status_code, 400)

        db.session.expire_all()
        self.assertIsNone(db.session.get(VaProjectMaster, self.PROJECT))

    def test_post_without_the_fields_keeps_the_model_defaults(self):
        response = self._post(self._base_payload(self.PROJECT))
        self.assertEqual(response.status_code, 201, response.get_json())

        db.session.expire_all()
        stored = db.session.get(VaProjectMaster, self.PROJECT)
        self.assertEqual(stored.web_intake_default_locale, "en")
        self.assertIsNone(stored.web_intake_available_locales)
        self.assertIsNone(stored.web_intake_narration_languages)
        self.assertFalse(stored.web_intake_show_guidance)


class InstrumentCodeHelperTests(BaseTestCase):
    """``instrument_code_for`` reads ``mas_form_types.base_instrument_code``.

    A DigitVA form type is a layer on a standard instrument, and which
    instrument it layers on is recorded per form type since 2026-09-19. The
    naming convention that stood in for the column is gone: a ``WHO_2022_VA*``
    code whose column is NULL resolves to nothing, which is exactly the state
    the form-type PUT can leave behind.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_form_type("ICF_BASE", "Instrument Column Base")
        cls._ensure_form_type("ICF_LAYER", "Instrument Column Layer")
        cls._ensure_form_type(
            "WHO_2022_VA_ICFNULL",
            "WHO prefixed with no instrument",
            base_instrument_code=None,
        )
        cls.unbundled = cls._ensure_form_type(
            "ICF_PHMRC", "Instrument Column PHMRC", base_instrument_code=None
        )
        db.session.commit()

    def test_a_code_resolves_to_its_stored_base_instrument(self):
        self.assertEqual(instrument_code_for("ICF_BASE"), "WHO_2022_VA")
        self.assertEqual(instrument_code_for("ICF_LAYER"), "WHO_2022_VA")

    def test_a_form_type_row_resolves_without_a_query(self):
        row = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "ICF_BASE")
        )
        self.assertEqual(instrument_code_for(row), "WHO_2022_VA")

    def test_the_who_prefix_alone_no_longer_resolves(self):
        """Positive control first: the prefix rule really is gone.

        ``WHO_2022_VA_ICFNULL`` carries the prefix the old rule matched on and
        a NULL column, which the form-type PUT can produce.
        """
        self.assertEqual(instrument_code_for("ICF_BASE"), "WHO_2022_VA")
        self.assertIsNone(instrument_code_for("WHO_2022_VA_ICFNULL"))

    def test_an_unregistered_or_unbundled_code_has_no_instrument(self):
        self.assertIsNone(instrument_code_for("ICF_PHMRC"))
        self.assertIsNone(instrument_code_for("ICF_NOT_REGISTERED"))
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

        # The social layer may already be registered by the seed; the helper
        # is get-or-create and sets the base_instrument_code the migration
        # backfills on a real database but cannot on a create_all schema.
        social = cls._ensure_form_type(
            "WHO_2022_VA_SOCIAL", "WHO 2022 VA with social autopsy"
        )
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


class WebFormTypeAndExtensionOptionsTests(BaseTestCase):
    """The web questionnaire and the two extensions are project settings.

    WP1 of docs/planning/web-capture-project-configuration-plan.md. A project
    that collects only on the web has no ODK mapping, so before this the
    endpoint served an empty ``form_types`` list and the intake page stopped
    with "This project has no questionnaire configured".
    """

    PROJECT = "FOPT07"
    URL = "/api/v1/organization/FOPT07/form-options"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Web Only Project",
                project_nickname="WebOnly",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                web_intake_mode="direct",
            )
        )
        db.session.flush()
        cls.base_type = cls._ensure_form_type("WHO_2022_VA", "WHO 2022 VA Form")
        cls.social_type = cls._ensure_form_type(
            "WHO_2022_VA_SOCIAL", "WHO 2022 VA with social autopsy"
        )
        cls.web_user = cls._get_or_make_user("fopt.webonly@test.local", "FormOpts123")
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.web_user.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.project,
                project_id=cls.PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.project = db.session.get(VaProjectMaster, self.PROJECT)
        self.project.web_intake_mode = "direct"
        self.project.web_intake_form_type_id = None
        self.project.web_intake_intake_note = None
        self.project.web_intake_death_summary_enabled = True
        db.session.commit()
        self._login(str(self.web_user.user_id))

    def _payload(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_a_web_only_project_gets_the_default_questionnaire(self):
        payload = self._payload()
        self.assertEqual(
            [
                (ft["form_type_code"], ft["instrument_code"], ft["is_default"])
                for ft in payload["form_types"]
            ],
            [("WHO_2022_VA", "WHO_2022_VA", True)],
        )

    def test_a_configured_layer_is_the_default_questionnaire(self):
        """Positive control first: the fallback answers before it is configured."""
        self.assertEqual(
            [ft["form_type_code"] for ft in self._payload()["form_types"]],
            ["WHO_2022_VA"],
        )

        self.project.web_intake_form_type_id = self.social_type.form_type_id
        db.session.commit()

        payload = self._payload()
        default = next(ft for ft in payload["form_types"] if ft["is_default"])
        self.assertEqual(default["form_type_code"], "WHO_2022_VA_SOCIAL")
        self.assertEqual(default["instrument_code"], "WHO_2022_VA")

    def test_web_intake_off_does_not_invent_a_questionnaire(self):
        """The most-sites rule still answers for an ODK-only project."""
        self.project.web_intake_mode = "off"
        db.session.commit()
        self.assertEqual(self._payload()["form_types"], [])

    def test_intake_screen_carries_the_default_note_and_goes_when_blanked(self):
        from app.services.web_intake_service import DEFAULT_INTAKE_NOTE

        payload = self._payload()
        self.assertIn("intake_screen", payload["enabled_extensions"])
        self.assertEqual(payload["intake_note"], DEFAULT_INTAKE_NOTE)

        self.project.web_intake_intake_note = "Read this first."
        db.session.commit()
        payload = self._payload()
        self.assertEqual(payload["intake_note"], "Read this first.")
        self.assertIn("intake_screen", payload["enabled_extensions"])

        self.project.web_intake_intake_note = ""
        db.session.commit()
        payload = self._payload()
        self.assertIsNone(payload["intake_note"])
        self.assertNotIn("intake_screen", payload["enabled_extensions"])

    def test_death_summary_is_on_by_default_and_goes_when_switched_off(self):
        self.assertIn("death_summary", self._payload()["enabled_extensions"])

        self.project.web_intake_death_summary_enabled = False
        db.session.commit()
        self.assertNotIn("death_summary", self._payload()["enabled_extensions"])


class WebFormTypeAdminValidationTests(BaseTestCase):
    """A project may only be configured with a usable, confirmed form type."""

    PROJECT = "FOPT08"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Web Form Type Admin Project",
                project_nickname="WebTypeAdmin",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                web_intake_mode="direct",
            )
        )
        # One active site, so switching web intake on really materializes a
        # web va_forms row — the path that reads the configured form type.
        db.session.add(
            VaSiteMaster(
                site_id="FT08",
                site_name="Web Form Type Admin Site",
                site_abbr="FT08",
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT,
                site_id="FT08",
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.flush()
        cls.good = cls._ensure_form_type("FTV_GOOD", "Validated Good")
        cls.inactive = cls._ensure_form_type(
            "FTV_INACTIVE", "Validated Inactive", is_active=False
        )
        cls.unconfirmed = cls._ensure_form_type(
            "FTV_UNCONFIRMED", "Validated Unconfirmed", pii_confirmed=False
        )
        cls.no_instrument = cls._ensure_form_type(
            "FTV_NO_INSTRUMENT", "Validated Without Instrument",
            base_instrument_code=None,
        )
        db.session.commit()

    def _put(self, payload):
        self._login(str(self.base_admin_user.user_id))
        return self.client.put(
            f"/admin/api/projects/{self.PROJECT}",
            json=payload,
            headers=self._csrf_headers(),
        )

    def test_put_accepts_an_active_confirmed_type_and_serves_its_code(self):
        response = self._put(
            {"web_intake_form_type_id": str(self.good.form_type_id)}
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        project = response.get_json()["project"]
        self.assertEqual(
            project["web_intake_form_type_id"], str(self.good.form_type_id)
        )
        self.assertEqual(project["web_intake_form_type_code"], "FTV_GOOD")

    def test_put_rejects_inactive_unconfirmed_and_uninstrumented_types(self):
        """Positive control first: the good type is accepted in this same test."""
        self.assertEqual(
            self._put({"web_intake_form_type_id": str(self.good.form_type_id)}).status_code,
            200,
        )

        for form_type, expected in (
            (self.inactive, "is not active"),
            (self.unconfirmed, "unconfirmed PII set"),
            (self.no_instrument, "no base_instrument_code"),
        ):
            with self.subTest(form_type=form_type.form_type_code):
                response = self._put(
                    {"web_intake_form_type_id": str(form_type.form_type_id)}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected, response.get_json()["error"])

        # ... and the rejected values were not written to the project.
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaProjectMaster, self.PROJECT).web_intake_form_type_id,
            self.good.form_type_id,
        )

    def test_put_rejects_an_unknown_or_malformed_id(self):
        malformed = self._put({"web_intake_form_type_id": "not-a-uuid"})
        self.assertEqual(malformed.status_code, 400)
        self.assertIn("Invalid web_intake_form_type_id", malformed.get_json()["error"])

        unknown = self._put({"web_intake_form_type_id": str(uuid.uuid4())})
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("Form type not found", unknown.get_json()["error"])

    def test_put_clears_the_setting_with_null(self):
        self.assertEqual(
            self._put({"web_intake_form_type_id": str(self.good.form_type_id)}).status_code,
            200,
        )
        response = self._put({"web_intake_form_type_id": None})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["project"]["web_intake_form_type_id"])

    def test_put_sets_the_note_and_the_death_summary_switch(self):
        response = self._put({
            "web_intake_intake_note": "  Welcome to the study.  ",
            "web_intake_death_summary_enabled": False,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        project = response.get_json()["project"]
        self.assertEqual(project["web_intake_intake_note"], "Welcome to the study.")
        self.assertFalse(project["web_intake_death_summary_enabled"])

        response = self._put({"web_intake_intake_note": None})
        self.assertIsNone(response.get_json()["project"]["web_intake_intake_note"])

    def test_put_rejects_a_non_text_note(self):
        response = self._put({"web_intake_intake_note": 7})
        self.assertEqual(response.status_code, 400)

    def test_web_form_types_endpoint_lists_active_types_with_their_status(self):
        self._login(str(self.base_admin_user.user_id))
        response = self.client.get("/admin/api/web-form-types")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        by_code = {ft["form_type_code"]: ft for ft in payload["form_types"]}

        self.assertIn("FTV_GOOD", by_code)
        self.assertEqual(by_code["FTV_GOOD"]["base_instrument_code"], "WHO_2022_VA")
        self.assertTrue(by_code["FTV_GOOD"]["pii_confirmed"])
        self.assertTrue(by_code["FTV_GOOD"]["is_active"])

        self.assertIn("FTV_UNCONFIRMED", by_code)
        self.assertFalse(by_code["FTV_UNCONFIRMED"]["pii_confirmed"])
        self.assertIsNone(by_code["FTV_NO_INSTRUMENT"]["base_instrument_code"])
        # Inactive types are not offered at all.
        self.assertNotIn("FTV_INACTIVE", by_code)

    def test_switching_web_intake_on_with_a_retired_type_is_a_400(self):
        """Materializing a web form on a deactivated type is refused, not a 500.

        Positive control first: the same PUT succeeds while the configured
        type is active.
        """
        self.assertEqual(
            self._put({
                "web_intake_form_type_id": str(self.good.form_type_id),
                "web_intake_mode": "direct",
            }).status_code,
            200,
        )

        # A form type can be deactivated after a project was configured with
        # it. The stored setting is then only discovered when a *new* web form
        # row has to be materialized, so clear the rows the control created.
        from app.models import VaForms

        for form in db.session.scalars(
            db.select(VaForms).where(
                VaForms.project_id == self.PROJECT, VaForms.form_source == "web"
            )
        ).all():
            db.session.delete(form)
        project = db.session.get(VaProjectMaster, self.PROJECT)
        project.web_intake_form_type_id = self.inactive.form_type_id
        db.session.commit()

        response = self._put({"web_intake_mode": "both"})
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("not an active form type", response.get_json()["error"])

    def test_web_form_types_endpoint_is_admin_only(self):
        self._login(str(self.base_project_pi_user.user_id))
        self.assertEqual(self.client.get("/admin/api/web-form-types").status_code, 403)


class WebProjectDefaultsOnCreateTests(BaseTestCase):
    """POST /admin/api/projects applies WEB_PROJECT_DEFAULTS.

    Decided 2026-09-19: a project created with web intake on gets the whole
    web-capture configuration, not only the keys the caller happened to send.
    An explicit value always wins, and a project created with web intake off
    keeps the model defaults.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.default_type = cls._ensure_form_type("WHO_2022_VA", "WHO 2022 VA Form")
        cls.other_type = cls._ensure_form_type(
            "WHO_2022_VA_SOCIAL", "WHO 2022 VA with social autopsy"
        )
        for code, name in (("english", "English"), ("hindi", "Hindi")):
            existing = db.session.get(MasLanguages, code)
            if existing is None:
                db.session.add(
                    MasLanguages(language_code=code, language_name=name, is_active=True)
                )
        db.session.commit()

    def _post(self, project_id, **extra):
        self._login(str(self.base_admin_user.user_id))
        payload = {
            "project_id": project_id,
            "project_name": "Defaults Project",
            "project_nickname": "Defaults",
        }
        payload.update(extra)
        return self.client.post(
            "/admin/api/projects", json=payload, headers=self._csrf_headers()
        )

    def test_a_web_project_is_created_with_every_default(self):
        from app.services.web_form_instruments import all_instrument_locales

        response = self._post("FDEF01", web_intake_mode="direct")
        self.assertEqual(response.status_code, 201, response.get_json())

        db.session.expire_all()
        project = db.session.get(VaProjectMaster, "FDEF01")
        self.assertEqual(project.web_intake_mode, "direct")
        self.assertEqual(project.web_intake_form_type_id, self.default_type.form_type_id)
        self.assertIsNone(project.web_intake_intake_note)
        self.assertTrue(project.web_intake_death_summary_enabled)
        self.assertFalse(project.social_autopsy_enabled)
        self.assertEqual(project.coding_intake_mode, "pick_and_choose")
        # The two language lists keep only the codes their validators accept:
        # "hi" is not an instrument locale yet, so it is dropped rather than
        # failing the create.
        self.assertEqual(
            project.web_intake_available_locales,
            [code for code in ("en", "hi") if code in all_instrument_locales()],
        )
        self.assertEqual(
            project.web_intake_narration_languages, ["english", "hindi"]
        )

    def test_web_intake_off_keeps_the_model_defaults(self):
        response = self._post("FDEF02")
        self.assertEqual(response.status_code, 201, response.get_json())

        db.session.expire_all()
        project = db.session.get(VaProjectMaster, "FDEF02")
        self.assertEqual(project.web_intake_mode, "off")
        self.assertIsNone(project.web_intake_form_type_id)
        self.assertIsNone(project.web_intake_available_locales)
        self.assertIsNone(project.web_intake_narration_languages)
        self.assertTrue(project.social_autopsy_enabled)
        self.assertEqual(project.coding_intake_mode, "random_form_allocation")

    def test_an_explicit_value_wins_over_the_default(self):
        response = self._post(
            "FDEF03",
            web_intake_mode="both",
            web_intake_form_type_id=str(self.other_type.form_type_id),
            web_intake_intake_note="",
            web_intake_death_summary_enabled=False,
            social_autopsy_enabled=True,
            coding_intake_mode="random_form_allocation",
            web_intake_narration_languages=["english"],
        )
        self.assertEqual(response.status_code, 201, response.get_json())

        db.session.expire_all()
        project = db.session.get(VaProjectMaster, "FDEF03")
        self.assertEqual(project.web_intake_mode, "both")
        self.assertEqual(project.web_intake_form_type_id, self.other_type.form_type_id)
        self.assertEqual(project.web_intake_intake_note, "")
        self.assertFalse(project.web_intake_death_summary_enabled)
        self.assertTrue(project.social_autopsy_enabled)
        self.assertEqual(project.coding_intake_mode, "random_form_allocation")
        self.assertEqual(project.web_intake_narration_languages, ["english"])

    def test_the_payload_modes_are_honoured_on_create(self):
        response = self._post(
            "FDEF04", web_intake_mode="death_register",
            coding_intake_mode="pick_and_choose",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        served = response.get_json()["project"]
        self.assertEqual(served["web_intake_mode"], "death_register")
        self.assertEqual(served["coding_intake_mode"], "pick_and_choose")

    def test_an_invalid_mode_is_refused_and_creates_nothing(self):
        for field, value in (
            ("web_intake_mode", "sideways"),
            ("coding_intake_mode", "whatever"),
        ):
            with self.subTest(field=field):
                response = self._post("FDEF05", **{field: value})
                self.assertEqual(response.status_code, 400)
        db.session.expire_all()
        self.assertIsNone(db.session.get(VaProjectMaster, "FDEF05"))
