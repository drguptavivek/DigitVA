import uuid

from flask import g, redirect, request, session, url_for

from app.services import training_demo_service


def register_training_demo_onboarding(app):
    @app.before_request
    def training_demo_onboarding():
        """Send a trainee with a pending training session to its training page, once.

        The page is the Expo ``/app/training`` while the export is present,
        else the Flask welcome page. Browser page loads only: never the API,
        htmx fragments, static files, auth pages, the welcome flow itself or
        the Expo shell under ``/app/`` (``/app/`` is never redirected to a
        Flask page; the Expo home sends a pending trainee itself). Cheap:
        nothing runs unless the feature is configured, and the answer is cached
        in the login session. docs/policy/training-demo-project.md.
        """
        if not app.config.get("DIGITVA_TRAINING_PROJECT_ID"):
            return None
        if (
            request.method != "GET"
            or request.headers.get("HX-Request")
            or request.is_json
            or request.path.startswith(
                ("/static", "/api/", "/admin/api/", "/app/", "/demo", "/vaauth", "/profile", "/health", "/help")
            )
            or not request.endpoint
            # The Expo shell is a role home (login lands there); its assets are not pages.
            or request.endpoint == "expo_client.expo_asset"
        ):
            return None
        user_id = session.get("_user_id")
        if not user_id or g.get("bearer_auth"):
            return None
        raw_uid = user_id.rpartition(":")[0] or user_id
        try:
            uid = uuid.UUID(raw_uid)
        except (TypeError, ValueError):
            return None
        if training_demo_service.should_redirect_to_welcome(uid):
            from app.routes.expo_client import export_ready

            return redirect("/app/training" if export_ready() else url_for("training_demo.welcome"))
        return None
