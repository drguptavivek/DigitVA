"""ICD-11 client tokens: issuance, revocation, listing and authentication
(app/services/icd11_client_auth.py), and the client terminology helpers
(app/services/icd11_client_api.py). Policy: docs/policy/icd11-client-api.md."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
import sqlalchemy as sa
from flask import request
from requests import Response

from app import db
from app.models import AuthSecurityEvent
from app.services import icd11_client_api as terms
from app.services import icd11_client_auth as clients
from app.services.icd11_postcoordination import PostcoordinationError, guidance_request
from tests.base import BaseTestCase


class Icd11ClientAuthServiceTests(BaseTestCase):
    def _issue(self, name="DeathNote", scopes=None, days=None):
        row, token = clients.issue_client(name, scopes or ["icd11:search"], days, self.base_admin_user)
        db.session.commit()
        return row, token

    def _authenticate(self, header):
        headers = {"Authorization": header} if header is not None else {}
        with self.app.test_request_context("/api/icd11-client/v1/client", method="POST", headers=headers):
            return clients.authenticate(request)

    def _events(self, client_id):
        return db.session.scalars(
            sa.select(AuthSecurityEvent)
            .where(AuthSecurityEvent.detail["client_id"].astext == str(client_id))
            .order_by(AuthSecurityEvent.occurred_at)
        ).all()

    # -- issuance ----------------------------------------------------------

    def test_issue_stores_only_the_sha256_verifier_and_audits_without_token(self):
        row, token = self._issue(scopes=["icd11:lookup", "icd11:search", "icd11:lookup"])
        self.assertRegex(token, r"^dvicd_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$")
        self.assertEqual(token.split("_")[1], row.key_id)
        self.assertEqual(row.token_sha256, hashlib.sha256(token.encode()).hexdigest())
        # Deduplicated, in SCOPES order.
        self.assertEqual(row.scopes, ["icd11:search", "icd11:lookup"])
        self.assertAlmostEqual(
            (row.expires_at - row.created_at).total_seconds(), timedelta(days=90).total_seconds(), delta=5
        )
        # No column holds the token or its secret part.
        stored = db.session.execute(
            sa.text("SELECT * FROM auth_icd11_api_clients WHERE id = :id"), {"id": row.id}
        ).mappings().one()
        self.assertTrue(stored)
        secret = token.rsplit("_", 1)[1]
        for value in stored.values():
            self.assertNotIn(token, str(value))
            self.assertNotIn(secret, str(value))
        events = self._events(row.id)
        self.assertEqual([event.event_type for event in events], ["icd11_client_issued"])
        event = events[0]
        self.assertEqual(event.actor_user_id, self.base_admin_user.user_id)
        self.assertIsNone(event.user_id)
        self.assertIsNotNone(event.occurred_at)
        self.assertEqual(event.detail["key_id"], row.key_id)
        self.assertEqual(set(event.detail), {"client_id", "key_id", "name", "scopes", "expires_at"})
        self.assertNotIn(secret, json.dumps(event.detail))

    def test_issue_rejects_bad_input_naming_the_field(self):
        cases = [
            (("", ["icd11:search"], None), "name"),
            (("   ", ["icd11:search"], None), "name"),
            (("x" * 121, ["icd11:search"], None), "name"),
            (("App", [], None), "scopes"),
            (("App", None, None), "scopes"),
            (("App", ["icd11:admin"], None), "scopes"),
            (("App", "icd11:search", None), "scopes"),
            (("App", ["icd11:search"], 0), "expires_in_days"),
            (("App", ["icd11:search"], 366), "expires_in_days"),
            (("App", ["icd11:search"], True), "expires_in_days"),
            (("App", ["icd11:search"], "30"), "expires_in_days"),
            (("App", ["icd11:search"], 1.5), "expires_in_days"),
        ]
        for args, field in cases:
            with self.subTest(args=args):
                with self.assertRaises(clients.Icd11ClientInputError) as raised:
                    clients.issue_client(*args, self.base_admin_user)
                self.assertEqual(raised.exception.field, field)
        db.session.rollback()

    def test_issue_accepts_the_boundaries_and_strips_the_name(self):
        for days in (1, 365):
            row, _token = self._issue(name="  Boundary app  ", days=days)
            self.assertEqual(row.name, "Boundary app")
            self.assertAlmostEqual(
                (row.expires_at - row.created_at).total_seconds(), days * 86400, delta=5
            )
        row, _token = self._issue(name="x" * 120)
        self.assertEqual(len(row.name), 120)

    # -- revocation ----------------------------------------------------------

    def test_revoke_is_audited_once_and_idempotent(self):
        row, _token = self._issue()
        clients.revoke_client(row.id, self.base_admin_user)
        db.session.commit()
        first_revoked_at = row.revoked_at
        self.assertIsNotNone(first_revoked_at)
        self.assertEqual(row.revoked_by, self.base_admin_user.user_id)
        clients.revoke_client(row.id, self.base_project_pi_user)
        db.session.commit()
        self.assertEqual(row.revoked_at, first_revoked_at)
        self.assertEqual(row.revoked_by, self.base_admin_user.user_id)
        events = self._events(row.id)
        self.assertEqual(
            [event.event_type for event in events], ["icd11_client_issued", "icd11_client_revoked"]
        )
        self.assertEqual(events[1].actor_user_id, self.base_admin_user.user_id)

    def test_revoke_unknown_id_is_not_found(self):
        with self.assertRaises(clients.Icd11ClientNotFound):
            clients.revoke_client(uuid.uuid4(), self.base_admin_user)

    # -- listing -------------------------------------------------------------

    def test_list_is_newest_first_with_status_and_names_and_no_verifier(self):
        older, _ = self._issue(name="Older app")
        older.created_at = datetime.now(UTC) - timedelta(days=2)
        expired, _ = self._issue(name="Expired app")
        expired.created_at = datetime.now(UTC) - timedelta(days=1)
        expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        newest, _ = self._issue(name="Newest app")
        clients.revoke_client(older.id, self.base_admin_user)
        db.session.commit()

        with mock.patch.object(db.session, "get", wraps=db.session.get) as gets:
            listing = clients.list_clients()
        gets.assert_not_called()  # names come from the one joined query
        mine = [c for c in listing["clients"] if c["id"] in {str(older.id), str(expired.id), str(newest.id)}]
        self.assertEqual([c["name"] for c in mine], ["Newest app", "Expired app", "Older app"])
        self.assertEqual([c["status"] for c in mine], ["active", "expired", "revoked"])
        self.assertEqual(mine[2]["revoked_by"], self.base_admin_user.name)
        self.assertEqual(mine[0]["created_by"], self.base_admin_user.name)
        self.assertIsNone(mine[0]["revoked_by"])
        self.assertFalse(listing["truncated"])
        for client in mine:
            self.assertIn("key_id", client)
            self.assertNotIn("token_sha256", client)
        self.assertNotIn(newest.token_sha256, json.dumps(listing))

    def test_list_is_bounded(self):
        with mock.patch.object(clients, "LIST_LIMIT", 2):
            for index in range(3):
                self._issue(name=f"Bounded {index}")
            listing = clients.list_clients()
        self.assertEqual(len(listing["clients"]), 2)
        self.assertTrue(listing["truncated"])

    # -- authentication ------------------------------------------------------

    def test_authenticate_accepts_a_live_token_any_scheme_case(self):
        row, token = self._issue()
        self.assertEqual(self._authenticate(f"Bearer {token}").id, row.id)
        self.assertEqual(self._authenticate(f"bearer {token}").id, row.id)
        self.assertEqual(self._authenticate(f"BEARER {token}").id, row.id)

    def test_authenticate_refuses_malformed_tokens_without_a_database_read(self):
        _row, token = self._issue()
        for header in (None, "", f"Basic {token}", "Bearer", "Bearer dvicd_abc",
                       f"Bearer {token}x", f"Bearer {token[:-1]}", f"Bearer x{token}",
                       f"Bearer {token.replace('dvicd_', 'dvdev_')}"):
            with self.subTest(header=header):
                with mock.patch.object(db.session, "scalar") as scalar:
                    with self.assertRaises(clients.Icd11ClientAuthError) as raised:
                        self._authenticate(header)
                scalar.assert_not_called()
                self.assertEqual((raised.exception.code, raised.exception.status), ("INVALID_TOKEN", 401))

    def test_authenticate_refuses_unknown_revoked_and_expired(self):
        row, token = self._issue()
        unknown = f"dvicd_{row.key_id}_{'A' * 43}"
        with self.assertRaises(clients.Icd11ClientAuthError) as raised:
            self._authenticate(f"Bearer {unknown}")
        self.assertEqual(raised.exception.code, "INVALID_TOKEN")

        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.session.commit()
        with self.assertRaises(clients.Icd11ClientAuthError) as raised:
            self._authenticate(f"Bearer {token}")
        self.assertEqual((raised.exception.code, raised.exception.status), ("TOKEN_EXPIRED", 401))

        clients.revoke_client(row.id, self.base_admin_user)
        db.session.commit()
        with self.assertRaises(clients.Icd11ClientAuthError) as raised:
            self._authenticate(f"Bearer {token}")
        self.assertEqual((raised.exception.code, raised.exception.status), ("TOKEN_REVOKED", 401))

    def test_last_used_is_set_on_first_use_and_throttled(self):
        row, token = self._issue()
        self.assertIsNone(row.last_used_at)
        self._authenticate(f"Bearer {token}")
        first = row.last_used_at
        self.assertIsNotNone(first)
        self._authenticate(f"Bearer {token}")
        self.assertEqual(row.last_used_at, first)
        row.last_used_at = datetime.now(UTC) - timedelta(seconds=61)
        db.session.commit()
        stale = row.last_used_at
        self._authenticate(f"Bearer {token}")
        self.assertGreater(row.last_used_at, stale)

    def test_require_scope(self):
        row, _token = self._issue(scopes=["icd11:search"])
        clients.require_scope(row, "icd11:search")
        with self.assertRaises(clients.Icd11ClientAuthError) as raised:
            clients.require_scope(row, "icd11:lookup")
        self.assertEqual((raised.exception.code, raised.exception.status), ("INSUFFICIENT_SCOPE", 403))


# -- terminology helpers (no database) -----------------------------------------

MMS = "http://id.who.int/icd/release/11/2026-01/mms"


def test_browser_url_for_plain_mms_uris_only():
    assert terms.browser_url(f"{MMS}/882244568") == "https://icd.who.int/browse/2026-01/mms/en#882244568"
    assert terms.browser_url(f"{MMS}/882244568/unspecified") == (
        "https://icd.who.int/browse/2026-01/mms/en#882244568%2Funspecified"
    )
    assert terms.browser_url(f"{MMS}/882244568/other") == (
        "https://icd.who.int/browse/2026-01/mms/en#882244568%2Fother"
    )
    for uri in (
        f"{MMS}/100 & {MMS}/300",
        f"{MMS}/100 / {MMS}/300",
        "http://id.who.int/icd/release/11/2024-01/mms/882244568",
        "http://id.who.int/icd/entity/882244568",
        "https://evil.example/icd/release/11/2026-01/mms/1",
        f"{MMS}/882244568/x",
        f"{MMS}/882244568?q=1",
        "",
        None,
        123,
    ):
        assert terms.browser_url(uri) is None, uri


def _who(payload, status=200):
    response = Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    return response


def test_search_words_asks_for_keyword_results_and_bounds_them():
    words = [{"label": f"<em class='found'>tuber</em>culosis {i}", "dontChangeResult": False} for i in range(25)]
    with mock.patch.object(terms, "proxy_who_icd_request", return_value=_who({"words": words})) as proxy:
        result = terms.search_words(" tuber ")
    resource = proxy.call_args.args[0]
    body = proxy.call_args.kwargs["body"].decode()
    assert resource == "icd/release/11/2026-01/mms/search"
    assert proxy.call_args.kwargs["method"] == "POST"
    for part in ("q=tuber", "includeKeywordResult=true", "useFlexiSearch=false",
                 "flatResults=true", "medicalCodingMode=true"):
        assert part in body
    assert result["words"][0] == "tuberculosis 0"
    assert len(result["words"]) == 20
    assert result["truncated"] is True

    with mock.patch.object(terms, "proxy_who_icd_request",
                           return_value=_who({"words": words[:2], "wordSuggestionsChopped": False})):
        assert terms.search_words("tuber") == {"words": ["tuberculosis 0", "tuberculosis 1"], "truncated": False}
    with mock.patch.object(terms, "proxy_who_icd_request",
                           return_value=_who({"words": [], "wordSuggestionsChopped": True})):
        assert terms.search_words("tuber") == {"words": [], "truncated": True}


def test_validate_expression_refusals():
    assert terms.validate_expression("1B12.2&1B12.2")["refusal"]["code"] == "REPEATED_PART"
    with mock.patch.object(terms, "codeinfo_item", return_value=None):
        result = terms.validate_expression("ZZ99")
    assert result == {"valid": False, "refusal": {"code": "CODE_NOT_FOUND", "message": mock.ANY}}
    item = {"code": "1B10.Z", "leaf": True}
    with mock.patch.object(terms, "codeinfo_item", return_value=item):
        assert terms.validate_expression("1B10.Z") == {"valid": True, "item": item, "certificate_refusal": None}
    category = {"code": "1B12", "leaf": False}
    with mock.patch.object(terms, "codeinfo_item", return_value=category):
        result = terms.validate_expression("1B12")
    assert result["valid"] is True
    assert result["certificate_refusal"]["code"] == "NOT_CERTIFIABLE"
    assert "category" in result["certificate_refusal"]["message"]


def test_client_slots_are_separate_from_the_coders_guidance_slots():
    held = []
    try:
        for _ in range(4):
            slot = terms.client_slot()
            slot.__enter__()
            held.append(slot)
        with pytest.raises(PostcoordinationError) as busy:
            with terms.client_slot():
                pass
        assert (busy.value.code, busy.value.status) == ("GUIDANCE_BUSY", 429)
        # The coders' default capacity is untouched while every client slot is taken.
        with guidance_request():
            pass
    finally:
        for slot in reversed(held):
            slot.__exit__(None, None, None)
    with terms.client_slot():
        pass
