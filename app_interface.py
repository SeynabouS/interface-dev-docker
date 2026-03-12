from flask import jsonify, request

from app import app as app


RESILIENCE_EXACT_PATHS = {
    "/resilience",
    "/upload_resilience",
    "/resilience_layers",
    "/resilience_layers_support",
    "/resilience_runs_history",
    "/resilience_runs_delete",
    "/resilience_runs_reset",
    "/delete_resilience_layer",
    "/alea_view_batch_stream",
}
RESILIENCE_PREFIX_PATHS = (
    "/resilience_layer_data/",
    "/resilience_dependencies/",
    "/download_resilience_layer/",
)


def _is_resilience_path(path: str) -> bool:
    if path in RESILIENCE_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in RESILIENCE_PREFIX_PATHS)


@app.before_request
def isolate_interface_application():
    if not _is_resilience_path(request.path):
        return None

    return jsonify(
        {
            "status": "error",
            "message": "Route indisponible sur l'application Interface Analyse.",
        }
    ), 404
