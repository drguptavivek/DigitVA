"""Hard separation of the training project from real work in the Expo API.

Policy: docs/policy/training-demo-project.md, "Separation from real work".

Every list, count and allocation endpoint the Expo screens call runs in one of
two scopes, chosen per request from ``?training=``:

* ``exclude`` (default, ``training`` absent or ``0``): the training project is
  invisible to everyone, including a trainee.
* ``only`` (``training=1``): nothing but the training project, and only for a
  caller with an active participation in an active session whose role opens the
  area in that session's type (``training_demo_service.AREA_RULES``). Anyone else gets 403.

``use`` stores the scope on the request; the query builders then add
``conditions`` / ``form_conditions`` to their own WHERE. Every request starts
in ``exclude`` (Flask pages and API alike) unless ``resolve`` sets ``only``;
only the trainer tools (``TRAINER_PREFIXES``) run in ``all``, with no filter.
Outside a request (CLI, Celery) ``current()`` is None and nothing is added.
"""
import sqlalchemy as sa
from flask import abort, current_app, has_request_context, jsonify, make_response, request
from flask_login import current_user

ONLY = "only"
EXCLUDE = "exclude"
ALL = "all"
# Trainer tools that must see the training project: the admin Training
# sessions panel and its JSON API, and the trainer report.
TRAINER_PREFIXES = ("/admin/panels/training-sessions", "/admin/api/training", "/data-management/training")
_KEY = "digitva.training_scope"
_TRUE, _FALSE = ("1", "true"), ("", "0", "false")


def training_project_id() -> str | None:
    """The configured training project id, or None when training is off."""
    return current_app.config.get("DIGITVA_TRAINING_PROJECT_ID") or None


def _refuse(message: str, code: str, status: int):
    abort(make_response(jsonify({"error": message, "code": code}), status))


def use(scope: str) -> str:
    """Set the scope of this request and return it."""
    request.environ[_KEY] = scope
    return scope


def open_trainer_tools() -> None:
    """App before_request: the trainer tools run unfiltered (``all``)."""
    if request.path.startswith(TRAINER_PREFIXES):
        use(ALL)


def current() -> str | None:
    """The scope of this request (``exclude`` unless an endpoint or the trainer
    hook set another), or None outside a request."""
    return request.environ.get(_KEY, EXCLUDE) if has_request_context() else None


def resolve(area: str, *more_areas: str) -> str:
    """Read ``?training=`` of the request, authorize it for *area* (or any of
    *more_areas*, keys of ``training_demo_service.AREA_RULES``), set it and
    return it.

    400 ``invalid_request`` for a value other than 0/1; 403 ``forbidden`` for
    ``training=1`` without the matching active participation (or with training
    off). The check runs on every request, so an edited URL gains nothing.
    """
    from app.services import training_demo_service as training

    raw = (request.args.get("training") or "").strip().lower()
    if raw in _FALSE:
        return use(EXCLUDE)
    if raw not in _TRUE:
        _refuse("training must be 0 or 1.", "invalid_request", 400)
    areas = (area, *more_areas)
    if (
        not training_project_id()
        or not current_user.is_authenticated
        or not any(training.may_use_area(current_user.user_id, a) for a in areas)
    ):
        _refuse("You are not a participant of an active training session for this area.", "forbidden", 403)
    return use(ONLY)


QUEUES = ("standard", "own")
_QUEUE_KEY = "digitva.training_queue"


def resolve_queue() -> str | None:
    """Read ``?queue=`` on the training side (call after ``resolve``): the
    coding queue every training pool, count, random allocation and pick list
    of this request uses (docs/policy/training-session-types.md, "Coding in a
    self-coding session"). ``standard`` (the default) is the caller's standard
    training set; ``own`` their own interviews, only for a self-coding
    trainee (403 ``forbidden`` otherwise). 400 ``invalid_request`` for
    another value. Ignored on the real side, which keeps its codes."""
    if current() != ONLY:
        return None
    from app.services import training_demo_service as training

    raw = (request.args.get("queue") or "standard").strip().lower()
    if raw not in QUEUES:
        _refuse("queue must be standard or own.", "invalid_request", 400)
    if raw == "own" and not training.training_self_coding_ids(current_user.user_id):
        _refuse("Coding your own interviews needs a self-coding training session.", "forbidden", 403)
    request.environ[_QUEUE_KEY] = raw
    return raw


def queue() -> str | None:
    """The training coding queue of this request (``standard`` unless
    ``resolve_queue`` set ``own``), or None off the training side."""
    if current() != ONLY:
        return None
    return request.environ.get(_QUEUE_KEY, "standard")


def conditions(project_col) -> list:
    """WHERE conditions on a project id column for the current scope."""
    scope, project_id = current(), training_project_id()
    if scope in (None, ALL) or project_id is None:
        return []
    return [project_col == project_id] if scope == ONLY else [project_col.is_distinct_from(project_id)]


def form_conditions(form_id_col) -> list:
    """The same on a form id column (a submission's ``va_form_id``)."""
    from app.models import VaForms

    inner = conditions(VaForms.project_id)
    if not inner:
        return []
    return [form_id_col.in_(sa.select(VaForms.form_id).where(*inner))]


def on_training_side() -> bool:
    """Whether the current scope is the training side (the allocation side a
    request reads and writes; every other scope is the real side)."""
    return current() == ONLY


def is_training_sid(va_sid: str) -> bool:
    """Whether the submission belongs to the training project."""
    from app import db
    from app.models import VaForms, VaSubmissions

    tid = training_project_id()
    return tid is not None and bool(db.session.scalar(
        sa.select(sa.exists().where(
            VaSubmissions.va_sid == va_sid,
            VaSubmissions.va_form_id == VaForms.form_id,
            VaForms.project_id == tid,
        ))
    ))


def keeps_project(project_id) -> bool:
    """Whether a row of *project_id* is inside the current scope."""
    scope, tid = current(), training_project_id()
    if scope in (None, ALL) or tid is None:
        return True
    return (project_id == tid) == (scope == ONLY)


def filter_form_ids(form_ids):
    """*form_ids* narrowed to the current scope (unchanged when none is set)."""
    from app import db
    from app.models import VaForms

    inner = conditions(VaForms.project_id)
    if not inner or not form_ids:
        return form_ids
    return set(db.session.scalars(sa.select(VaForms.form_id).where(VaForms.form_id.in_(form_ids), *inner)))


def sid_allowed(va_sid: str) -> bool:
    """Whether acting on the submission stays inside the current scope, i.e.
    does not cross the training/real line. An unknown sid passes (the caller's own 404)."""
    from app import db
    from app.models import VaForms, VaSubmissions

    scope, tid = current(), training_project_id()
    if scope in (None, ALL) or tid is None:
        return True
    crossing = VaForms.project_id.is_distinct_from(tid) if scope == ONLY else VaForms.project_id == tid
    return not db.session.scalar(
        sa.select(sa.exists().where(
            VaSubmissions.va_sid == va_sid,
            VaSubmissions.va_form_id == VaForms.form_id,
            crossing,
        ))
    )
