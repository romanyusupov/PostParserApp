import secrets

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from server.postparser_web.authentication import (
    authenticate_code,
    clear_login_failures,
    ensure_csrf_token,
    login_rate_limited,
    record_login_failure,
    validate_csrf_token,
)


auth_bp = Blueprint("authentication", __name__)


@auth_bp.get("/")
def login_page():
    if current_app.config.get("AUTHENTICATION_DISABLED") or session.get(
        "principal"
    ):
        return redirect(url_for("settings_page.settings_page"))
    return render_template("login.html", login_error="")


@auth_bp.post("/login")
def login():
    if not current_app.secret_key:
        return render_template(
            "login.html",
            login_error="Вход временно недоступен.",
        ), 503

    if not validate_csrf_token():
        return render_template(
            "login.html",
            login_error="Сессия входа устарела. Обновите страницу.",
        ), 403
    if login_rate_limited():
        return render_template(
            "login.html",
            login_error="Слишком много попыток. Повторите вход позднее.",
        ), 429

    principal = authenticate_code(
        current_app.extensions["access_store"],
        request.form.get("access_code", ""),
    )
    if principal is None:
        record_login_failure()
        return render_template(
            "login.html",
            login_error="Неверный код доступа.",
        ), 401

    clear_login_failures()
    session.clear()
    session["session_id"] = secrets.token_urlsafe(32)
    session["principal"] = principal
    ensure_csrf_token()
    return redirect(url_for("settings_page.settings_page"))


@auth_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("authentication.login_page"))
