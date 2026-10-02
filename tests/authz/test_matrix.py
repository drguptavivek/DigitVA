"""The hand-written access matrix (tests/authz/matrix.py) against the module.

Each row goes through ``can`` (or, for list actions with a submission
target, ``scope_filter`` membership). Policy and fixture: see matrix.py and
fixture.py.
"""
from app.services.authz import Action, Reason, can, scope_filter
from tests.authz.fixture import AuthzFixtureMixin
from tests.authz.matrix import MATRIX
from tests.base import BaseTestCase

_LIST_ACTIONS = {Action.LIST_DATA, Action.LIST_UNROUTED}


class AuthzMatrixTests(AuthzFixtureMixin, BaseTestCase):

    def _check(self, user_key, action, target_key, expected):
        grants = self.grants_for(user_key)
        user = self.users.get(user_key)
        if action in _LIST_ACTIONS and ":" not in target_key:
            listed = self.scoped_sids(scope_filter(user, action, _grants=grants))
            self.assertEqual(target_key in listed, expected)
            return
        decision = can(user, action, self.target(target_key), _grants=grants)
        if isinstance(expected, Reason):
            self.assertFalse(decision.allowed)
            self.assertIs(decision.reason, expected, decision.message)
        else:
            self.assertEqual(decision.allowed, expected, decision.reason)

    def test_matrix(self):
        self.assertGreaterEqual(len(MATRIX), 150)
        for row in MATRIX:
            with self.subTest(row=row):
                self._check(*row)

    def test_every_fixture_sid_exists(self):
        # Guard: a misspelt sid would make every "refused" row pass vacuously.
        sids = {row[2] for row in MATRIX if ":" not in row[2]}
        self.assertTrue(sids)
        self.assertLessEqual(sids, self.all_sids())
