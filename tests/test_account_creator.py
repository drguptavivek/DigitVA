"""Every new account records who made it (account-onboarding policy, creator record)."""
import sqlalchemy as sa

from app import db
from app.commands.seed import _seed_admin
from app.models import VaUsers
from app.services import user_account_service as accounts
from tests.base import BaseTestCase


class AccountCreatorTests(BaseTestCase):
    def test_creation_other_names_the_actor_or_null_and_keeps_extras(self):
        self.assertEqual(
            accounts.creation_other("admin", self.base_admin_id, {"k": 1}),
            {"k": 1, "created_by_user_id": str(self.base_admin_id), "created_via": "admin"},
        )
        self.assertEqual(
            accounts.creation_other("sso"), {"created_by_user_id": None, "created_via": "sso"}
        )

    def test_create_invited_user_stamps_actor_and_keeps_extra_keys(self):
        fields = {"email": "stamp@test.local", "name": "Stamp", "phone": "",
                  "languages": ["english"]}
        user = accounts.create_invited_user(
            fields, via="mentor_institute", actor_user_id=self.base_admin_id,
            other={"created_by_mentor_institute": "MC1"})
        self.assertEqual(user.other, {
            "created_by_mentor_institute": "MC1",
            "created_by_user_id": str(self.base_admin_id),
            "created_via": "mentor_institute",
        })

    def test_seed_admin_records_a_null_creator_via_seed(self):
        db.session.execute(sa.delete(VaUsers).where(VaUsers.email == "testadmin@digitva.com"))
        _seed_admin()
        admin = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "testadmin@digitva.com"))
        self.assertEqual(admin.other, {"created_by_user_id": None, "created_via": "seed"})
