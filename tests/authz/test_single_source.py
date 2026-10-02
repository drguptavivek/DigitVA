"""``can`` and ``scope_filter`` are one rule (digitva-0wc, design 3).

For every fixture user and every submission-targeted action, the sids
``can`` allows are exactly the sids ``scope_filter`` selects. And the
predicate is hygienic: it references ``VaSubmissions`` as its only free
table, so embedding it in a query that also joins ``VaForms`` (the
reviewing dashboard does) returns the same rows as a query that does not
(the coder pool). A correlated ``EXISTS`` on ``VaForms`` would pass a plain
"does it execute" check and still multiply rows in the joined query.
"""
import sqlalchemy as sa

from app import db
from app.models import VaForms, VaSubmissions
from app.services.authz import RULES, Action, can, scope_filter
from app.services.authz.actions import SUBMISSION_ACTIONS
from tests.authz.fixture import SIDS, USERS, AuthzFixtureMixin
from tests.base import BaseTestCase


class SingleSourceTests(AuthzFixtureMixin, BaseTestCase):

    def test_can_equals_scope_filter_for_every_user_and_submission_action(self):
        for user_key in USERS:
            grants = self.grants_for(user_key)
            user = self.users[user_key]
            for action in sorted(SUBMISSION_ACTIONS, key=lambda a: a.value):
                with self.subTest(user=user_key, action=action.value):
                    allowed = {
                        sid for sid in SIDS
                        if can(user, action, sid, _grants=grants).allowed
                    }
                    listed = self.scoped_sids(scope_filter(user, action, _grants=grants))
                    self.assertEqual(allowed, listed)

    def test_the_comparison_is_not_vacuous(self):
        # Assert the subject is present: someone is allowed and someone refused.
        grants = self.grants_for("coder_p1")
        listed = self.scoped_sids(
            scope_filter(self.users["coder_p1"], Action.CODE, _grants=grants)
        )
        self.assertIn("ta-p1", listed)
        self.assertNotIn("ta-p2", listed)

    def test_predicate_has_vasubmissions_as_its_only_free_table(self):
        for user_key in USERS:
            grants = self.grants_for(user_key)
            user = self.users[user_key]
            for action in sorted(RULES, key=lambda a: a.value):
                with self.subTest(user=user_key, action=action.value):
                    predicate = scope_filter(user, action, _grants=grants)
                    in_fixture = VaSubmissions.va_sid.in_(sorted(SIDS))
                    plain = db.session.scalars(
                        sa.select(VaSubmissions.va_sid).where(in_fixture, predicate)
                    ).all()
                    joined = db.session.scalars(
                        sa.select(VaSubmissions.va_sid)
                        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
                        .where(in_fixture, predicate)
                    ).all()
                    self.assertEqual(sorted(plain), sorted(joined))
                    self.assertEqual(len(plain), len(set(plain)))

    def test_predicate_compiles_with_no_from_but_va_submissions(self):
        grants = self.grants_for("mixed")
        predicate = scope_filter(self.users["mixed"], Action.VIEW, _grants=grants)
        froms = sa.select(VaSubmissions.va_sid).where(predicate).get_final_froms()
        self.assertEqual([f.name for f in froms], ["va_submissions"])
