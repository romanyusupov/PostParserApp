import hmac
import os
import secrets
import threading
import time
from functools import wraps
from typing import Any

from flask import current_app, g, jsonify, redirect, request, session, url_for


ADMIN_OWNER_ID = "admin"
ADMIN_NAME = "Администратор"
ADMIN_PASSWORD_ENVIRONMENT_VARIABLE = "POSTPARSER_ADMIN_PASSWORD"
SESSION_SECRET_ENVIRONMENT_VARIABLE = "POSTPARSER_SESSION_SECRET"
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 8

PUBLIC_ENDPOINTS = {
    "health.health",
    "media.telegram_photo",
    "authentication.login_page",
    "authentication.login",
    "instagram_oauth.instagram_connect",
    "instagram_oauth.instagram_callback",
}


def admin_principal() -> dict[str, str]:
    return {
        "owner_id": ADMIN_OWNER_ID,
        "name": ADMIN_NAME,
        "role": "admin",
    }


def current_principal() -> dict[str, str]:
    principal = getattr(g, "principal", None)
    if not isinstance(principal, dict):
        raise RuntimeError("Контекст аутентификации недоступен.")
    return principal


def current_owner_id() -> str:
    return current_principal()["owner_id"]


def current_user_name() -> str:
    return current_principal()["name"]


def is_admin() -> bool:
    return current_principal().get("role") == "admin"


def _stored_principal() -> dict[str, str] | None:
    value = session.get("principal")
    if not isinstance(value, dict):
        return None
    owner_id = str(value.get("owner_id") or "").strip()
    name = str(value.get("name") or "").strip()
    role = str(value.get("role") or "").strip()
    if not owner_id or not name or role not in {"admin", "user"}:
        return None
    if role == "admin" and owner_id != ADMIN_OWNER_ID:
        return None
    return {"owner_id": owner_id, "name": name, "role": role}


def _unauthorized_response():
    if request.path.startswith("/api/"):
        return jsonify(
            {"success": False, "error": "Требуется код доступа."}
        ), 401
    return redirect(url_for("authentication.login_page"))


def install_authentication(app) -> None:
    if not app.secret_key:
        app.config["SECRET_KEY"] = os.environ.get(
            SESSION_SECRET_ENVIRONMENT_VARIABLE,
            "",
        )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.extensions["login_failures"] = {}
    app.extensions["login_failures_lock"] = threading.Lock()

    if not app.config.get("TESTING") and not app.config.get(
        "AUTHENTICATION_DISABLED"
    ):
        admin_password = os.environ.get(
            ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
            "",
        )
        session_secret = os.environ.get(
            SESSION_SECRET_ENVIRONMENT_VARIABLE,
            "",
        )
        if not admin_password or len(session_secret) < 32:
            raise RuntimeError(
                "Production-аутентификация не настроена."
            )

    @app.before_request
    def load_authenticated_principal():
        if app.config.get("AUTHENTICATION_DISABLED"):
            g.principal = admin_principal()
            return None

        if request.endpoint == "static" or request.endpoint in PUBLIC_ENDPOINTS:
            return None

        principal = _stored_principal()
        if principal is None:
            return _unauthorized_response()
        if principal["role"] == "user":
            principal = app.extensions["access_store"].active_principal(
                principal["owner_id"]
            )
            if principal is None:
                session.clear()
                return _unauthorized_response()
        g.principal = principal

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not validate_csrf_token():
                if request.path.startswith("/api/"):
                    return jsonify(
                        {"success": False, "error": "Недействительный CSRF-токен."}
                    ), 403
                return "Недействительный CSRF-токен.", 403
        return None

    @app.context_processor
    def authentication_template_context():
        principal = current_principal() if hasattr(g, "principal") else None
        csrf_token = ""
        if app.secret_key and not app.config.get("AUTHENTICATION_DISABLED"):
            csrf_token = ensure_csrf_token()
        return {
            "authenticated_user": principal,
            "authenticated_is_admin": bool(
                principal and principal.get("role") == "admin"
            ),
            "csrf_token": csrf_token,
        }


def ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf_token() -> bool:
    expected = session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token") or request.form.get(
        "csrf_token"
    )
    return bool(
        isinstance(expected, str)
        and isinstance(supplied, str)
        and hmac.compare_digest(expected, supplied)
    )


def login_rate_limited() -> bool:
    key = request.remote_addr or "unknown"
    now = time.monotonic()
    failures = current_app.extensions["login_failures"]
    lock = current_app.extensions["login_failures_lock"]
    with lock:
        recent = [
            timestamp
            for timestamp in failures.get(key, [])
            if now - timestamp < LOGIN_WINDOW_SECONDS
        ]
        failures[key] = recent
        return len(recent) >= LOGIN_MAX_FAILURES


def record_login_failure() -> None:
    key = request.remote_addr or "unknown"
    failures = current_app.extensions["login_failures"]
    lock = current_app.extensions["login_failures_lock"]
    with lock:
        failures.setdefault(key, []).append(time.monotonic())


def clear_login_failures() -> None:
    key = request.remote_addr or "unknown"
    failures = current_app.extensions["login_failures"]
    lock = current_app.extensions["login_failures_lock"]
    with lock:
        failures.pop(key, None)


def authenticate_code(access_store: Any, access_code: Any):
    normalized_code = str(access_code or "")
    admin_password = os.environ.get(
        ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
        "",
    )
    if admin_password and hmac.compare_digest(
        normalized_code,
        admin_password,
    ):
        return admin_principal()
    return access_store.authenticate(normalized_code)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            if request.path.startswith("/api/"):
                return jsonify(
                    {"success": False, "error": "Доступ запрещён."}
                ), 403
            return redirect(url_for("settings_page.settings_page"))
        return view(*args, **kwargs)

    return wrapped
