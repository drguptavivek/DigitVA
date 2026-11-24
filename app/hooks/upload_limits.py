import re

from flask import request

from app.services.attachment_service import MAX_BYTES as _ATTACHMENT_MAX_BYTES
from app.services.bundle_ingest_service import MAX_BYTES as _BUNDLE_MAX_BYTES


def register_upload_limits(app):
    # CSRFProtect parses the request body in its before_request hook, before any
    # route can set its own cap. Config.MAX_CONTENT_LENGTH bounds every body; this
    # hook, registered before the CSRF one, raises it only for the uploads that
    # legitimately exceed it. Routes may still set a stricter cap of their own.
    _mib = 1024 * 1024
    _slack = 64 * 1024  # multipart framing around a file
    _upload_limits = (
        ("PUT", r"/api/v1/intake/drafts/[^/]+/attachments/[^/]+", _ATTACHMENT_MAX_BYTES),
        ("POST", r"/api/v1/intake/bundles(/validate)?", _BUNDLE_MAX_BYTES),
        ("POST", r"/admin/api/organization/[^/]+/project-users/import", _mib + _slack),
        ("POST", r"/admin/api/organization/[^/]+/import", 5 * _mib + _slack),
        ("POST", r"/admin/api/instrument-translations/[^/]+/[^/]+/(import|xliff)", 5 * _mib + _slack),
        ("POST", r"/admin/api/form-types/import", 10 * _mib + _slack),
        # Policy and scheme JSON imports have no cap of their own.
        ("POST", r"/admin/api/(icd10/2019-2|icd11/mms)/policy-import", 16 * _mib),
        ("POST", r"/admin/api/cod-bucket-schemes/[^/]+/import", 16 * _mib),
        ("POST", r"/api/v1/icd10/2019-2/policy-import", 16 * _mib),
    )
    # The hook keeps the table in its closure: tests/routes/test_request_body_limit.py reads it there.
    _upload_limits = tuple((m, re.compile(p), cap) for m, p, cap in _upload_limits)

    @app.before_request
    def _raise_upload_body_limit():
        for method, pattern, cap in _upload_limits:
            if request.method == method and pattern.fullmatch(request.path):
                request.max_content_length = cap
                break
        return None
