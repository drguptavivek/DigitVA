"""Web intake for every client (docs/policy/api-v1.md), either credential.

``/api/v1/intake``: cases, death register, drafts, offline uploads and the
supervisor list. Thin handlers over ``app.services.web_intake_service``.
Access is decided per request from the caller's grants (``role_required``,
and per case in the service); the browser cookie needs ``X-CSRFToken`` on a
state change, a device bearer token needs none. Errors are
``{"error", "code"}``. Reference: docs/current-state/device-collection-api.md.
Policy: docs/policy/web-intake.md, docs/policy/field-data-collection.md.

Layout (bead digitva-r8nh.9). One blueprint, ``intake_api``, whose endpoint
names, rules and methods are the old module's (old APKs call them):

- ``_common``: the blueprint, its request hooks and error handlers, parsers
- ``register``: identifier types, consent settings, the death register,
  the identity-free refusal receipt (``POST /refusals``)
- ``cases``: the worklist, one case, flags, visits, attempts, pause
- ``drafts``: drafts, attachments, the browser submit
- ``uploads``: the phone's upload, revisions, outstanding work, prefill policy
- ``supervision``: the supervisor list and actions

The names below stay importable here; the ones tests patch on this package
(``pii_scope``, ``should_redact_pii``, ``visit_notes_for``,
``_supervised_body``) are read back through ``_common._pkg()``.
"""
from app.routes.api.intake import (  # noqa: F401  (routes)
    cases,
    drafts,
    register,
    supervision,
    uploads,
)
from app.routes.api.intake._common import (  # noqa: F401
    ATTACHMENT_MAX_BYTES,
    BODY_MAX_BYTES,
    REPORT_MAX_BYTES,
    SUBMISSION_MAX_BYTES,
    bp,
    intake_svc,
    log,
)
from app.routes.api.intake.supervision import (  # noqa: F401
    _supervised_body,
    revision_access,
    supervised_case_detail,
)
from app.services.viewer_pii_service import pii_scope, should_redact_pii  # noqa: F401
from app.services.visit_note import visit_notes_for  # noqa: F401
