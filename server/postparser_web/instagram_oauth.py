import json
import os
import secrets
import urllib.parse
import urllib.request
from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, request

from server.postparser_web.authentication import admin_required

from server.postparser_web.instagram_token_store import (
    InstagramTokenStorageError,
    save_instagram_access_token,
)


INSTAGRAM_APP_ID_ENVIRONMENT_VARIABLE = "INSTAGRAM_APP_ID"
INSTAGRAM_APP_SECRET_ENVIRONMENT_VARIABLE = "INSTAGRAM_APP_SECRET"
INSTAGRAM_REDIRECT_URI_ENVIRONMENT_VARIABLE = "INSTAGRAM_REDIRECT_URI"
INSTAGRAM_OAUTH_SCOPES = (
    "instagram_business_basic",
    "instagram_business_manage_insights",
)
INSTAGRAM_AUTHORIZATION_URL = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_LONG_TOKEN_URL = "https://graph.instagram.com/access_token"
INSTAGRAM_OAUTH_STATE_COOKIE = "postparser_instagram_oauth_state"


instagram_oauth_bp = Blueprint("instagram_oauth", __name__)


class InstagramOAuthError(Exception):
    """Безопасная ошибка Instagram OAuth без секретных данных."""


def _oauth_configuration(require_secret: bool = False) -> dict[str, str]:
    configuration = {
        "app_id": os.environ.get(
            INSTAGRAM_APP_ID_ENVIRONMENT_VARIABLE,
            "",
        ).strip(),
        "app_secret": os.environ.get(
            INSTAGRAM_APP_SECRET_ENVIRONMENT_VARIABLE,
            "",
        ).strip(),
        "redirect_uri": os.environ.get(
            INSTAGRAM_REDIRECT_URI_ENVIRONMENT_VARIABLE,
            "",
        ).strip(),
    }
    required_names = ["app_id", "redirect_uri"]
    if require_secret:
        required_names.append("app_secret")

    if any(not configuration[name] for name in required_names):
        raise InstagramOAuthError("Instagram OAuth не настроен.")

    return configuration


def _default_oauth_transport(
    url: str,
    *,
    method: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    encoded_parameters = urllib.parse.urlencode(parameters)
    data = None
    request_url = url
    headers = {"Accept": "application/json"}

    if method == "POST":
        data = encoded_parameters.encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        request_url += "?" + encoded_parameters

    oauth_request = urllib.request.Request(
        request_url,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(oauth_request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise InstagramOAuthError(
            "Instagram OAuth вернул некорректный ответ."
        )

    return payload


def _oauth_transport():
    return current_app.config.get(
        "INSTAGRAM_OAUTH_TRANSPORT",
        _default_oauth_transport,
    )


def _token_storage_path():
    return current_app.config.get("INSTAGRAM_TOKEN_ENV_PATH")


def _safe_error_response(message: str, status_code: int):
    return jsonify({"success": False, "error": message}), status_code


@instagram_oauth_bp.get("/instagram/connect")
@admin_required
def instagram_connect():
    try:
        configuration = _oauth_configuration()
    except InstagramOAuthError:
        return _safe_error_response("Instagram OAuth не настроен.", 503)

    state = secrets.token_urlsafe(32)
    authorization_url = INSTAGRAM_AUTHORIZATION_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": configuration["app_id"],
            "redirect_uri": configuration["redirect_uri"],
            "response_type": "code",
            "scope": ",".join(INSTAGRAM_OAUTH_SCOPES),
            "state": state,
        }
    )
    response = redirect(authorization_url)
    response.set_cookie(
        INSTAGRAM_OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/instagram/callback",
    )
    return response


@instagram_oauth_bp.get("/instagram/callback")
def instagram_callback():
    if request.args.get("error"):
        current_app.logger.warning("Instagram OAuth was declined.")
        return _safe_error_response("Instagram OAuth не завершён.", 400)

    code = request.args.get("code", "").strip()
    state = request.args.get("state", "").strip()
    expected_state = request.cookies.get(
        INSTAGRAM_OAUTH_STATE_COOKIE,
        "",
    )

    if (
        not code
        or not state
        or not expected_state
        or not secrets.compare_digest(state, expected_state)
    ):
        current_app.logger.warning("Instagram OAuth state validation failed.")
        return _safe_error_response("Некорректный Instagram OAuth callback.", 400)

    try:
        configuration = _oauth_configuration(require_secret=True)
        transport = _oauth_transport()
        short_token_payload = transport(
            INSTAGRAM_TOKEN_URL,
            method="POST",
            parameters={
                "client_id": configuration["app_id"],
                "client_secret": configuration["app_secret"],
                "grant_type": "authorization_code",
                "redirect_uri": configuration["redirect_uri"],
                "code": code,
            },
        )
        short_token = str(
            short_token_payload.get("access_token", "")
        ).strip()
        if not short_token:
            raise InstagramOAuthError(
                "Instagram OAuth не вернул access token."
            )

        long_token_payload = transport(
            INSTAGRAM_LONG_TOKEN_URL,
            method="GET",
            parameters={
                "grant_type": "ig_exchange_token",
                "client_secret": configuration["app_secret"],
                "access_token": short_token,
            },
        )
        access_token = str(
            long_token_payload.get("access_token", short_token)
        ).strip()
        save_instagram_access_token(
            access_token,
            path=_token_storage_path(),
        )
    except (InstagramOAuthError, InstagramTokenStorageError):
        current_app.logger.warning("Instagram OAuth could not be completed.")
        return _safe_error_response("Не удалось завершить Instagram OAuth.", 502)
    except Exception:
        current_app.logger.warning("Instagram OAuth request failed.")
        return _safe_error_response("Не удалось завершить Instagram OAuth.", 502)

    response = jsonify(
        {
            "success": True,
            "message": "Instagram подключён.",
        }
    )
    response.delete_cookie(
        INSTAGRAM_OAUTH_STATE_COOKIE,
        path="/instagram/callback",
    )
    return response
