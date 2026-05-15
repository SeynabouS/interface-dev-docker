from flask import jsonify, redirect, request, session, url_for

from app import app as app


AUTH_EXACT_PATHS = {
    "/healthz",
    "/login",
    "/logout",
    "/forgot",
}
AUTH_PREFIX_PATHS = (
    "/reset/",
    "/static/",
    "/image/",
)

RESILIENCE_EXACT_PATHS = {
    "/resilience",
    "/resilience_admin_users",
    "/resilience_help_content",
    "/resilience_help_document",
    "/resilience_help_document_preview",
    "/resilience_help_document_download",
    "/upload_resilience",
    "/upload_resilience_analysis_layer",
    "/resilience_layers",
    "/resilience_layers_support",
    "/resilience_impact_matrix",
    "/resilience_analysis_layers",
    "/resilience_analysis_layer_clear",
    "/resilience_runs_history",
    "/resilience_runs_delete",
    "/resilience_runs_reset",
    "/delete_resilience_layer",
    "/alea_view_batch_stream",
}
RESILIENCE_PREFIX_PATHS = (
    "/resilience_admin_users/",
    "/resilience_help_document/",
    "/resilience_help_document_preview/",
    "/resilience_help_document_download/",
    "/resilience_layer_data/",
    "/resilience_dependencies/",
    "/download_resilience_layer/",
)

def _is_resilience_path(path: str) -> bool:
    if path in RESILIENCE_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in RESILIENCE_PREFIX_PATHS)


def _is_allowed_on_resilience_app(path: str) -> bool:
    if path in AUTH_EXACT_PATHS or path in RESILIENCE_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in AUTH_PREFIX_PATHS):
        return True
    if any(path.startswith(prefix) for prefix in RESILIENCE_PREFIX_PATHS):
        return True
    return False


@app.before_request
def isolate_resilience_application():
    if request.path == "/":
        return redirect("/resilience", code=302)

    if _is_resilience_path(request.path) and "user_id" not in session:
        return redirect(url_for("login"), code=302)

    if _is_allowed_on_resilience_app(request.path):
        return None

    return jsonify(
        {
            "status": "error",
            "message": "Route indisponible sur l'application Résilience.",
        }
    ), 404
