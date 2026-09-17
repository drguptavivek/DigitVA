"""Tests for the ODK form mapping conflict rule.

Covers `app/services/odk_form_mapping_service.py` directly and through
`flask odk-mappings audit`: dry-run reporting, the guarded `--fix` deletion of a
stale mapping on a deactivated project-site, and the refusal when two conflicting
mappings are both on active pairs.
"""

from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectOdk,
    MapProjectSiteOdk,
    MasOdkConnections,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.services.odk_form_mapping_service import find_conflicting_odk_form_mapping
from app.utils.credential_crypto import encrypt_credential
from tests.base import BaseTestCase


class OdkMappingsCliTests(BaseTestCase):
    KEEP_PROJECT = "CLM001"
    KEEP_SITE = "CM01"
    STALE_PROJECT = "CLM002"
    STALE_SITE = "CM02"
    ODK_PROJECT_ID = 91
    ODK_FORM_ID = "CLI_SHARED_FORM"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runner = cls.app.test_cli_runner()
        now = datetime.now(timezone.utc)
        for project_id, name in (
            (cls.KEEP_PROJECT, "ODK Mapping CLI Keep"),
            (cls.STALE_PROJECT, "ODK Mapping CLI Stale"),
        ):
            db.session.add_all(
                [
                    VaProjectMaster(
                        project_id=project_id,
                        project_code=project_id,
                        project_name=name,
                        project_nickname=project_id,
                        project_status=VaStatuses.active,
                        project_registered_at=now,
                        project_updated_at=now,
                    ),
                    VaResearchProjects(
                        project_id=project_id,
                        project_code=project_id,
                        project_name=name,
                        project_nickname=project_id,
                        project_status=VaStatuses.active,
                        project_registered_at=now,
                        project_updated_at=now,
                    ),
                ]
            )
        for site_id in (cls.KEEP_SITE, cls.STALE_SITE):
            db.session.add(
                VaSiteMaster(
                    site_id=site_id,
                    site_name=f"ODK Mapping CLI {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
        db.session.flush()

        for project_id, site_id in (
            (cls.KEEP_PROJECT, cls.KEEP_SITE),
            (cls.STALE_PROJECT, cls.STALE_SITE),
        ):
            db.session.add_all(
                [
                    VaSites(
                        site_id=site_id,
                        project_id=project_id,
                        site_name=f"ODK Mapping CLI {site_id}",
                        site_abbr=site_id,
                        site_status=VaStatuses.active,
                        site_registered_at=now,
                        site_updated_at=now,
                    ),
                    VaProjectSites(
                        project_id=project_id,
                        site_id=site_id,
                        project_site_status=VaStatuses.active,
                        project_site_registered_at=now,
                        project_site_updated_at=now,
                    ),
                ]
            )
        db.session.flush()

        for project_id, site_id in (
            (cls.KEEP_PROJECT, cls.KEEP_SITE),
            (cls.STALE_PROJECT, cls.STALE_SITE),
        ):
            db.session.add(
                VaForms(
                    form_id=f"{project_id}{site_id}01",
                    project_id=project_id,
                    site_id=site_id,
                    odk_form_id=cls.ODK_FORM_ID,
                    odk_project_id=str(cls.ODK_PROJECT_ID),
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
        db.session.flush()

        pepper = cls.app.config["ODK_CREDENTIAL_PEPPER"]
        username_enc, username_salt = encrypt_credential("admin@odk.test", pepper)
        password_enc, password_salt = encrypt_credential("s3cr3t", pepper)
        connection = MasOdkConnections(
            connection_name="ODK Mapping CLI Server",
            base_url="https://odk.test",
            username_enc=username_enc,
            username_salt=username_salt,
            password_enc=password_enc,
            password_salt=password_salt,
            status=VaStatuses.active,
        )
        db.session.add(connection)
        db.session.flush()
        cls.connection_id = connection.connection_id
        db.session.add_all(
            [
                MapProjectOdk(
                    project_id=cls.KEEP_PROJECT, connection_id=connection.connection_id
                ),
                MapProjectOdk(
                    project_id=cls.STALE_PROJECT, connection_id=connection.connection_id
                ),
            ]
        )
        db.session.add(
            VaSubmissions(
                va_sid="uuid:odk-mapping-cli-1",
                va_form_id=f"{cls.STALE_PROJECT}{cls.STALE_SITE}01",
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="cli",
                va_odk_reviewstate="reviewed",
                va_instance_name="odk-mapping-cli-1",
                va_uniqueid_real="odk-mapping-cli-1",
                va_uniqueid_masked="odk-mapping-cli-1",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=50,
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        # The command commits, which releases the per-test SAVEPOINT
        # (docs/policy/test-harness.md), so rebuild both conflicting mappings and
        # reset the pair statuses before every test.
        db.session.execute(
            sa.delete(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id.in_(
                    [self.KEEP_PROJECT, self.STALE_PROJECT]
                )
            )
        )
        db.session.add_all(
            [
                MapProjectSiteOdk(
                    project_id=self.KEEP_PROJECT,
                    site_id=self.KEEP_SITE,
                    odk_project_id=self.ODK_PROJECT_ID,
                    odk_form_id=self.ODK_FORM_ID,
                ),
                MapProjectSiteOdk(
                    project_id=self.STALE_PROJECT,
                    site_id=self.STALE_SITE,
                    odk_project_id=self.ODK_PROJECT_ID,
                    odk_form_id=self.ODK_FORM_ID,
                ),
            ]
        )
        db.session.execute(
            sa.update(VaProjectSites)
            .where(
                VaProjectSites.project_id.in_([self.KEEP_PROJECT, self.STALE_PROJECT])
            )
            .values(project_site_status=VaStatuses.active)
        )
        db.session.commit()

    def _deactivate_stale_pair(self):
        db.session.execute(
            sa.update(VaProjectSites)
            .where(
                VaProjectSites.project_id == self.STALE_PROJECT,
                VaProjectSites.site_id == self.STALE_SITE,
            )
            .values(project_site_status=VaStatuses.deactive)
        )
        db.session.commit()

    def _mapping_pairs(self):
        return set(
            db.session.execute(
                sa.select(MapProjectSiteOdk.project_id, MapProjectSiteOdk.site_id).where(
                    MapProjectSiteOdk.odk_form_id == self.ODK_FORM_ID
                )
            ).all()
        )

    def test_audit_dry_run_reports_conflict_and_deletes_nothing(self):
        self._deactivate_stale_pair()

        result = self.runner.invoke(args=["odk-mappings", "audit"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(self.ODK_FORM_ID, result.output)
        self.assertIn(f"{self.KEEP_PROJECT}/{self.KEEP_SITE}", result.output)
        self.assertIn(f"{self.STALE_PROJECT}/{self.STALE_SITE}", result.output)
        self.assertIn("pair=deactive submissions=1", result.output)
        self.assertIn("Dry-run", result.output)
        self.assertEqual(
            self._mapping_pairs(),
            {
                (self.KEEP_PROJECT, self.KEEP_SITE),
                (self.STALE_PROJECT, self.STALE_SITE),
            },
        )

    def test_audit_fix_removes_only_the_deactivated_duplicate(self):
        self._deactivate_stale_pair()

        result = self.runner.invoke(args=["odk-mappings", "audit", "--fix"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Deleted mapping", result.output)
        self.assertIn("deleted=1", result.output)
        self.assertEqual(self._mapping_pairs(), {(self.KEEP_PROJECT, self.KEEP_SITE)})

        rerun = self.runner.invoke(args=["odk-mappings", "audit", "--fix"])
        self.assertEqual(rerun.exit_code, 0, rerun.output)
        self.assertIn("No ODK form mapping conflicts found.", rerun.output)

    def test_audit_fix_refuses_when_both_pairs_are_active(self):
        result = self.runner.invoke(args=["odk-mappings", "audit", "--fix"])

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("REFUSED", result.output)
        self.assertEqual(
            self._mapping_pairs(),
            {
                (self.KEEP_PROJECT, self.KEEP_SITE),
                (self.STALE_PROJECT, self.STALE_SITE),
            },
        )

    def test_find_conflicting_mapping_reports_the_other_pair(self):
        conflict = find_conflicting_odk_form_mapping(
            self.STALE_PROJECT, self.STALE_SITE, self.ODK_PROJECT_ID, self.ODK_FORM_ID
        )

        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.project_id, self.KEEP_PROJECT)
        self.assertEqual(conflict.site_id, self.KEEP_SITE)

    def test_find_conflicting_mapping_ignores_the_same_pair(self):
        db.session.execute(
            sa.delete(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == self.STALE_PROJECT
            )
        )
        db.session.flush()

        self.assertIsNone(
            find_conflicting_odk_form_mapping(
                self.KEEP_PROJECT, self.KEEP_SITE, self.ODK_PROJECT_ID, self.ODK_FORM_ID
            )
        )

    def test_find_conflicting_mapping_blocks_on_a_deactivated_pair(self):
        self._deactivate_stale_pair()

        conflict = find_conflicting_odk_form_mapping(
            self.STALE_PROJECT, "CM03", self.ODK_PROJECT_ID, self.ODK_FORM_ID
        )

        self.assertIsNotNone(conflict)

    def test_find_conflicting_mapping_skips_project_without_connection(self):
        db.session.execute(
            sa.delete(MapProjectOdk).where(
                MapProjectOdk.project_id == self.STALE_PROJECT
            )
        )
        db.session.flush()

        self.assertIsNone(
            find_conflicting_odk_form_mapping(
                self.STALE_PROJECT, self.STALE_SITE, self.ODK_PROJECT_ID, self.ODK_FORM_ID
            )
        )
