from flask import Blueprint, current_app, jsonify

from server.postparser_web.legacy_proxy import proxy_current_request


health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    if current_app.config.get("LEGACY_PROXY_BASE_URL"):
        return proxy_current_request("/health")
    return jsonify({"status": "ok"})


@health_bp.get("/api/v1/health")
def application_health():
    return jsonify(
        {
            "status": "ok",
            "service": current_app.config.get(
                "POSTPARSER_SERVICE_NAME",
                "postparser-shadow",
            ),
        }
    )
