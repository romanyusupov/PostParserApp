import os
import urllib.parse

from flask import Blueprint, current_app, jsonify, render_template, request

from server.postparser_web.authentication import admin_required


admin_bp = Blueprint("admin", __name__)
PUBLIC_BASE_URL_ENVIRONMENT_VARIABLE = "POSTPARSER_PUBLIC_BASE_URL"


@admin_bp.get("/admin/access")
@admin_required
def access_page():
    return render_template("admin_access.html", active_section="access")


@admin_bp.get("/api/v1/admin/users")
@admin_required
def list_users():
    users = current_app.extensions["access_store"].list_users()
    return jsonify({"success": True, "users": users})


@admin_bp.post("/api/v1/admin/users")
@admin_required
def create_user():
    user = current_app.extensions["access_store"].create_user()
    return jsonify({"success": True, "user": user}), 201


@admin_bp.post("/api/v1/admin/instagram/oauth-invitations")
@admin_required
def create_instagram_oauth_invitation():
    invitation = current_app.extensions[
        "instagram_oauth_store"
    ].create_setup_invitation()
    public_base_url = os.environ.get(
        PUBLIC_BASE_URL_ENVIRONMENT_VARIABLE,
        "",
    ).strip().rstrip("/")
    if not public_base_url:
        public_base_url = request.url_root.rstrip("/")
    query = urllib.parse.urlencode(
        {"setup_token": invitation["setup_token"]}
    )
    setup_url = f"{public_base_url}/instagram/connect?{query}"
    return jsonify(
        {
            "success": True,
            "setup_url": setup_url,
            "expires_at": invitation["expires_at"],
        }
    ), 201


@admin_bp.patch("/api/v1/admin/users/<int:user_id>")
@admin_required
def update_user(user_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("active"), bool
    ):
        return jsonify(
            {"success": False, "error": "Некорректный статус пользователя."}
        ), 400
    user = current_app.extensions["access_store"].set_active(
        user_id,
        payload["active"],
    )
    if user is None:
        return jsonify(
            {"success": False, "error": "Пользователь не найден."}
        ), 404
    return jsonify({"success": True, "user": user})


@admin_bp.delete("/api/v1/admin/users/<int:user_id>")
@admin_required
def delete_user(user_id):
    deleted = current_app.extensions["access_store"].delete_user(user_id)
    if not deleted:
        return jsonify(
            {"success": False, "error": "Пользователь не найден."}
        ), 404
    return jsonify({"success": True})
