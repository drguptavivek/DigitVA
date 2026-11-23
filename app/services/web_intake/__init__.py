"""Web intake of WHO VA 2022 questionnaires, split by concern (bead
digitva-r8nh.12). ``app.services.web_intake_service`` stays the one public
module: callers import through it and tests patch names on it.

- ``common``: constants, the clock and device-time readers
- ``scope``: project mode, interviewer scope, unique ids, unit context
- ``register``: the death register
- ``register_access``: registration-number write access and register edits
- ``visits``: visits, contact attempts, pause
- ``drafts``: drafts, the envelope and device answer checks
- ``submission``: draft to submission
- ``revision``: interviewer revisions
- ``interview_choice``: a supervisor chooses between two interviews
- ``device``: device uploads and device cases
- ``worklist``: the interviewer worklist
- ``duplicates``: the possible-duplicate check
- ``supervisor``: the supervisor view
- ``serializers``: API dict shapes
"""


def facade():
    """The ``web_intake_service`` module, looked up at call time. Code here
    reads the names tests patch on it (``_utcnow``, ``pii_scope``,
    ``interviewer_context``, ``route_synced_submission`` and the like)
    through this, so such a patch still reaches them. Imported lazily: the
    facade imports these modules."""
    from app.services import web_intake_service

    return web_intake_service
