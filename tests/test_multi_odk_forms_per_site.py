"""A project-site may map several ODK forms, each with its own va_forms row.

Uniqueness on map_project_site_odk is (project, site, odk_project_id,
odk_form_id); the reverse rule — one ODK form belongs to one project-site —
still holds. Policy: docs/policy/admin-api-access.md.
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
)
from app.services.runtime_form_sync_service import (
    ensure_runtime_form_for_mapping,
    get_active_mapping_for_form,
    get_active_mappings_for_project_site,
    sync_runtime_forms_from_site_mappings,
)
from tests.base import BaseTestCase


class MultipleOdkFormsPerProjectSiteTests(BaseTestCase):
    PROJECT = "MOF001"
    SITE = "MF01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT, project_code=cls.PROJECT,
                project_name="Multi form project", project_nickname="MultiForm",
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE, site_abbr=cls.SITE, site_name="Multi form site",
                site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        if db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.PROJECT,
                VaProjectSites.site_id == cls.SITE,
            )
        ) is None:
            db.session.add(VaProjectSites(
                project_id=cls.PROJECT, site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT, project_code=cls.PROJECT,
                project_name="Multi form project", project_nickname="MultiForm",
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(VaSites(
                site_id=cls.SITE, project_id=cls.PROJECT, site_name="Multi form site",
                site_abbr=cls.SITE, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(
            sa.delete(VaForms).where(VaForms.project_id == self.PROJECT)
        )
        db.session.execute(
            sa.delete(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == self.PROJECT
            )
        )
        db.session.commit()

    def _map(self, odk_form_id, odk_project_id=42):
        mapping = MapProjectSiteOdk(
            project_id=self.PROJECT,
            site_id=self.SITE,
            odk_project_id=odk_project_id,
            odk_form_id=odk_form_id,
        )
        db.session.add(mapping)
        db.session.commit()
        return mapping

    def test_each_mapping_gets_its_own_runtime_form(self):
        self._map("FORM_ALPHA")
        self._map("FORM_BETA")

        forms = sync_runtime_forms_from_site_mappings()
        mine = [f for f in forms if f.project_id == self.PROJECT]
        db.session.commit()

        self.assertEqual(len(mine), 2)
        self.assertEqual(
            {f.odk_form_id for f in mine}, {"FORM_ALPHA", "FORM_BETA"}
        )
        # Distinct legacy identities, allocated from the same project-site prefix.
        self.assertEqual(len({f.form_id for f in mine}), 2)
        for form in mine:
            self.assertTrue(form.form_id.startswith(self.PROJECT + self.SITE))

    def test_rerunning_the_sync_does_not_add_or_rewrite_forms(self):
        self._map("FORM_ALPHA")
        self._map("FORM_BETA")
        first = {
            f.form_id: f.odk_form_id
            for f in sync_runtime_forms_from_site_mappings()
            if f.project_id == self.PROJECT
        }
        db.session.commit()

        second = {
            f.form_id: f.odk_form_id
            for f in sync_runtime_forms_from_site_mappings()
            if f.project_id == self.PROJECT
        }
        db.session.commit()
        self.assertEqual(first, second)
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaForms)
                .where(VaForms.project_id == self.PROJECT)
            ),
            2,
        )

    def test_a_form_resolves_back_to_its_own_mapping(self):
        alpha = self._map("FORM_ALPHA")
        beta = self._map("FORM_BETA", odk_project_id=43)
        sync_runtime_forms_from_site_mappings()
        db.session.commit()

        forms = {
            f.odk_form_id: f
            for f in db.session.scalars(
                sa.select(VaForms).where(VaForms.project_id == self.PROJECT)
            ).all()
        }
        self.assertEqual(
            get_active_mapping_for_form(forms["FORM_ALPHA"]).id, alpha.id
        )
        self.assertEqual(
            get_active_mapping_for_form(forms["FORM_BETA"]).id, beta.id
        )

    def test_listing_mappings_for_a_project_site_returns_all_of_them(self):
        self._map("FORM_ALPHA")
        self._map("FORM_BETA")
        mappings = get_active_mappings_for_project_site(self.PROJECT, self.SITE)
        self.assertEqual(
            [m.odk_form_id for m in mappings], ["FORM_ALPHA", "FORM_BETA"]
        )

    def test_repointing_a_mapping_keeps_its_runtime_form(self):
        mapping = self._map("FORM_ALPHA")
        form = ensure_runtime_form_for_mapping(mapping)
        db.session.commit()
        original_form_id = form.form_id

        previous_key = (
            mapping.project_id, mapping.site_id,
            str(mapping.odk_project_id), mapping.odk_form_id,
        )
        mapping.odk_form_id = "FORM_ALPHA_V2"
        db.session.flush()
        repointed = ensure_runtime_form_for_mapping(mapping, previous_key=previous_key)
        db.session.commit()

        # Same row, now pointing at the new ODK form: submissions stay attached.
        self.assertEqual(repointed.form_id, original_form_id)
        self.assertEqual(repointed.odk_form_id, "FORM_ALPHA_V2")
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaForms)
                .where(VaForms.project_id == self.PROJECT)
            ),
            1,
        )

    def test_without_the_previous_key_a_repoint_materializes_a_second_form(self):
        """The guard rail: this is why the admin route passes previous_key."""
        mapping = self._map("FORM_ALPHA")
        ensure_runtime_form_for_mapping(mapping)
        db.session.commit()

        mapping.odk_form_id = "FORM_ALPHA_V2"
        db.session.flush()
        ensure_runtime_form_for_mapping(mapping)
        db.session.commit()
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaForms)
                .where(VaForms.project_id == self.PROJECT)
            ),
            2,
        )

    def test_the_same_odk_form_twice_on_one_project_site_is_refused(self):
        self._map("FORM_ALPHA")
        db.session.add(
            MapProjectSiteOdk(
                project_id=self.PROJECT,
                site_id=self.SITE,
                odk_project_id=42,
                odk_form_id="FORM_ALPHA",
            )
        )
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_the_same_form_id_on_a_different_odk_project_is_a_different_form(self):
        self._map("SHARED_NAME", odk_project_id=42)
        self._map("SHARED_NAME", odk_project_id=43)
        mappings = get_active_mappings_for_project_site(self.PROJECT, self.SITE)
        self.assertEqual([m.odk_project_id for m in mappings], [42, 43])

        sync_runtime_forms_from_site_mappings()
        db.session.commit()
        forms = db.session.scalars(
            sa.select(VaForms).where(VaForms.project_id == self.PROJECT)
        ).all()
        self.assertEqual({f.odk_project_id for f in forms}, {"42", "43"})

    def test_panel_carries_the_mapping_picker_and_hidden_mapping_id(self):
        self._login(str(self.base_admin_id))
        response = self.client.get("/admin/panels/project-forms")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("pf-mapping-id-", body)
        self.assertIn("pf-mapping-sel", body)
        self.assertIn("pf-remove-mapping", body)
        self.assertIn("Add another form", body)
        # The save payload must name the mapping, or an edit would add a form.
        self.assertIn("mapping_id: mappingId || null", body)
