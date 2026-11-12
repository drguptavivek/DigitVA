"""Authenticated WHO ICD-11 API proxy and codeinfo client checks."""

from unittest.mock import Mock, patch

from requests import Response

from app.services.who_icd_api import WhoIcdApiUnavailable
from tests.base import BaseTestCase


def _response(status: int, payload: bytes = b"{}", content_type: str = "application/json"):
    response = Response()
    response.status_code = status
    response._content = payload
    response.headers["Content-Type"] = content_type
    return response


class TestIcd11WhoApiProxy(BaseTestCase):
    SID = "uuid:test-who-api-proxy"

    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)

    def _patch_access(self):
        return patch.multiple(
            "app.routes.api.icd11",
            _require_coding_or_reviewing_access=Mock(return_value=None),
            get_icd_classification_for_submission=Mock(return_value="icd11"),
        )

    def test_proxy_forwards_bounded_request_with_required_who_headers(self):
        upstream = _response(200, b'{"code":"GB61.Z"}')
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request", return_value=upstream
        ) as proxy:
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms"
                "?q=diabetes"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"code": "GB61.Z"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        proxy.assert_called_once_with(
            "icd/release/11/2026-01/mms",
            method="GET",
            query_string=b"q=diabetes",
            body=b"",
            content_type=None,
        )

    def test_analytics_is_discarded_without_contacting_upstream(self):
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request"
        ) as proxy:
            response = self.client.post(
                f"/api/v1/icd11/who-api/{self.SID}/analytics/clientanalytics",
                json={"search": "diabetic nephropathy"},
            )

        self.assertEqual(response.status_code, 204)
        proxy.assert_not_called()

    def test_proxy_preserves_bounded_json_post_for_ect_search(self):
        upstream = _response(200, b"[]")
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request", return_value=upstream
        ) as proxy:
            response = self.client.post(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms/search",
                json={"q": "diabetes"},
            )

        self.assertEqual(response.status_code, 200)
        kwargs = proxy.call_args.kwargs
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["content_type"], "application/json")
        self.assertEqual(self.app.json.loads(kwargs["body"]), {"q": "diabetes"})

    def test_proxy_preserves_ect_multipart_search(self):
        upstream = _response(200, b"[]")
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request", return_value=upstream
        ) as proxy:
            response = self.client.post(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms/search",
                data={"q": "diabetic nephropathy"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        kwargs = proxy.call_args.kwargs
        self.assertEqual(kwargs["content_type"], "application/x-www-form-urlencoded")
        self.assertEqual(kwargs["body"], b"q=diabetic+nephropathy")

    def test_upstream_failure_is_a_controlled_service_unavailable(self):
        with self._patch_access(), patch(
            "app.routes.api.icd11.proxy_who_icd_request",
            side_effect=WhoIcdApiUnavailable("unavailable"),
        ):
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/icd/release/11/2026-01/mms"
            )

        self.assertEqual(response.status_code, 503)

    def test_submission_access_is_checked_before_proxying(self):
        with patch(
            "app.routes.api.icd11._require_coding_or_reviewing_access",
            return_value=({"error": "denied"}, 403),
        ), patch("app.routes.api.icd11.proxy_who_icd_request") as proxy:
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/icd/entity/123"
            )

        self.assertEqual(response.status_code, 403)
        proxy.assert_not_called()

    def test_forbidden_resource_is_rejected_before_forwarding(self):
        with self._patch_access(), patch(
            "app.services.who_icd_api.requests.request"
        ) as upstream:
            response = self.client.get(
                f"/api/v1/icd11/who-api/{self.SID}/swagger/index.html"
            )

        self.assertEqual(response.status_code, 400)
        upstream.assert_not_called()

    def test_selection_check_returns_canonical_expression_and_title(self):
        previous_csrf = self.app.config["WTF_CSRF_ENABLED"]
        self.app.config["WTF_CSRF_ENABLED"] = False
        try:
            with self._patch_access(), patch(
                "app.routes.api.icd11.validate_icd11_mms_coding_value_for_submission"
            ) as validate, patch(
                "app.routes.api.icd11.build_icd11_provenance",
                return_value={
                    "code": "1G40.0&XN8Q",
                    "title": "Canonical title",
                    "selected_text": "Example title",
                    "release": "2026-01",
                    "linearization_uri": "http://id.who.int/icd/release/11/2026-01/mms/1",
                    "foundation_uri": None,
                    "codeinfo_uri": "http://id.who.int/icd/release/11/2026-01/mms/codeinfo/1G40.0%26XN8Q",
                },
            ):
                response = self.client.post(
                    f"/api/v1/icd11/selection-check/{self.SID}",
                    json={"code": "1g40.0&xn8q", "selectedText": "  Example title  "},
                )
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = previous_csrf

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "code": "1G40.0&XN8Q",
                "title": "Canonical title",
                "selectedText": "Example title",
                "value": "1G40.0&XN8Q Example title",
                "provenance": {
                    "code": "1G40.0&XN8Q",
                    "title": "Canonical title",
                    "selected_text": "Example title",
                    "release": "2026-01",
                    "linearization_uri": "http://id.who.int/icd/release/11/2026-01/mms/1",
                    "foundation_uri": None,
                    "codeinfo_uri": "http://id.who.int/icd/release/11/2026-01/mms/codeinfo/1G40.0%26XN8Q",
                },
                "warnings": [],
            },
        )
        validate.assert_called_once_with(
            self.SID, "1g40.0&xn8q Example title"
        )

    def _selection_check(self, validate_side_effect):
        previous_csrf = self.app.config["WTF_CSRF_ENABLED"]
        self.app.config["WTF_CSRF_ENABLED"] = False
        try:
            with self._patch_access(), patch(
                "app.routes.api.icd11.validate_icd11_mms_coding_value_for_submission",
                side_effect=validate_side_effect,
            ), patch(
                "app.routes.api.icd11.build_icd11_provenance",
                return_value={"code": "KB2C", "title": "Test KB2C", "selected_text": "Test"},
            ) as provenance:
                response = self.client.post(
                    f"/api/v1/icd11/selection-check/{self.SID}",
                    json={"code": "KB2C", "selectedText": "Test"},
                )
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = previous_csrf
        return response, provenance

    def test_selection_check_warns_on_an_age_conflict_instead_of_refusing(self):
        from app.services.icd_coding_policy import AgeRestrictionConfirmationRequired

        response, provenance = self._selection_check(
            AgeRestrictionConfirmationRequired("KB2C", "neonate_infant", "Perinatal")
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            response.get_json()["warnings"],
            [{
                "code": "AGE_RESTRICTED",
                "icd_code": "KB2C",
                "age_group_selectable": "neonate_infant",
                "restriction_note": "Perinatal",
            }],
        )
        provenance.assert_called_once()

    def test_selection_check_still_refuses_a_sex_conflict(self):
        response, provenance = self._selection_check(
            ValueError("JA00 is not selectable for this submission.")
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("not selectable", response.get_json()["error"])
        provenance.assert_not_called()

    def test_selection_check_keeps_normal_csrf_protection(self):
        with patch(
            "app.routes.api.icd11._require_coding_or_reviewing_access"
        ) as access:
            response = self.client.post(
                f"/api/v1/icd11/selection-check/{self.SID}",
                json={"code": "GB61.Z", "selectedText": "Diabetic nephropathy"},
            )

        self.assertEqual(response.status_code, 400)
        access.assert_not_called()


class TestIcd11SelectionCheckNonLeaf(BaseTestCase):
    """A category with children is refused with its children (digitva-dn15)."""

    SID = "uuid:test-non-leaf"

    def setUp(self):
        super().setUp()
        from app import db
        from app.models.mas_icd11_mms import MasIcd11Mms

        def row(code, parent, *, leaf, order, selectable=True, chapter="01"):
            return MasIcd11Mms(
                release="2026-01", linearization_uri=f"lin:{code}", code=code,
                title=f"Title {code}", class_kind="category", chapter_no=chapter,
                is_residual=code.endswith(".Z"), is_leaf=leaf, sort_order=order,
                parent_linearization_uri=parent, is_coding_selectable=selectable,
                source_version="ICD-11-MMS-2026-01", is_active=True,
            )

        db.session.add_all([
            row("1A40", None, leaf=False, order=1),
            row("1A40.0", "lin:1A40", leaf=True, order=2),
            row("1A40.Z", "lin:1A40", leaf=True, order=3),
            row("XK8G", None, leaf=False, order=4, selectable=False, chapter="X"),
        ])
        db.session.commit()
        self._login(self.base_admin_id)

    def _post(self, code, validate_side_effect=None):
        previous_csrf = self.app.config["WTF_CSRF_ENABLED"]
        self.app.config["WTF_CSRF_ENABLED"] = False
        try:
            with patch.multiple(
                "app.routes.api.icd11",
                _require_coding_or_reviewing_access=Mock(return_value=None),
                get_icd_classification_for_submission=Mock(return_value="icd11"),
            ), patch(
                "app.routes.api.icd11.validate_icd11_mms_coding_value_for_submission",
                side_effect=validate_side_effect,
            ) as validate, patch(
                "app.routes.api.icd11.build_icd11_provenance",
                return_value={"code": code, "title": "T", "selected_text": "T"},
            ):
                response = self.client.post(
                    f"/api/v1/icd11/selection-check/{self.SID}",
                    json={"code": code, "selectedText": "T"},
                )
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = previous_csrf
        return response, validate

    def test_non_leaf_category_is_refused_with_its_children(self):
        response, validate = self._post("1A40")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json(), {
            "error": "1A40 is a category, not a final code. Choose a more specific code under it.",
            "code": "non_leaf_category",
            "children": [
                {"code": "1A40.0", "title": "Title 1A40.0", "uri": "lin:1A40.0"},
                {"code": "1A40.Z", "title": "Title 1A40.Z", "uri": "lin:1A40.Z"},
            ],
        })
        validate.assert_not_called()

    def test_non_leaf_stem_with_extension_is_refused(self):
        response, _ = self._post("1A40&XK8G")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "non_leaf_category")

    def test_leaf_child_is_accepted(self):
        response, validate = self._post("1A40.Z")

        self.assertEqual(response.status_code, 200, response.get_json())
        validate.assert_called_once()

    def test_chapter_x_keeps_its_own_refusal(self):
        response, _ = self._post(
            "XK8G", ValueError("XK8G is not selectable for this submission.")
        )

        self.assertEqual(response.status_code, 422)
        body = response.get_json()
        self.assertNotEqual(body["code"], "non_leaf_category")
        self.assertIn("not selectable", body["error"])

    def test_unknown_code_returns_none(self):
        from app.services.icd11_mms_service import icd11_non_leaf_children

        self.assertIsNotNone(icd11_non_leaf_children("1A40"))
        self.assertIsNone(icd11_non_leaf_children("ZZ99"))
        self.assertIsNone(icd11_non_leaf_children("1A40.0"))

    def _validate_saved(self, code, saved):
        from app.services import icd_coding_value as module

        with patch.object(
            module, "get_icd_classification_for_submission", return_value="icd11"
        ), patch.object(module, "_is_saved_cod", return_value=saved), patch(
            "app.services.icd11_mms_service.validate_icd11_mms_coding_value_for_submission"
        ) as base:
            module.validate_coding_value_for_submission(self.SID, code)
        return base

    def test_save_refuses_a_new_non_leaf_value(self):
        from app.services.icd_coding_value import NonLeafCategory

        with self.assertRaises(NonLeafCategory) as ctx:
            self._validate_saved("1A40", saved=False)
        self.assertEqual(ctx.exception.code, "non_leaf_category")
        self.assertEqual(
            str(ctx.exception),
            "1A40 is a category, not a final code. Choose a more specific code under it.",
        )

    def test_save_still_revalidates_an_already_saved_non_leaf_value(self):
        self._validate_saved("1A40", saved=True).assert_called_once()

    def test_save_accepts_a_leaf(self):
        self._validate_saved("1A40.0", saved=False).assert_called_once()

    def test_saved_cod_lookup_runs_against_the_schema(self):
        from app.services.icd_coding_value import _is_saved_cod

        self.assertFalse(_is_saved_cod("uuid:none", "1A40"))
