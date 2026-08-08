import json
import os
import secrets
import urllib.parse
import urllib.error
import urllib.request
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request

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
INSTAGRAM_REDIRECT_URI = "https://tg-parser.proactivum.ru/instagram/callback"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_LONG_TOKEN_URL = "https://graph.instagram.com/access_token"
INSTAGRAM_PROFILE_URL = "https://graph.instagram.com/v22.0/me"
INSTAGRAM_ACCOUNT_ID_ENVIRONMENT_VARIABLE = (
    "POSTPARSER_INSTAGRAM_ACCOUNT_ID"
)


instagram_oauth_bp = Blueprint("instagram_oauth", __name__)


class InstagramOAuthError(Exception):
    """Безопасная ошибка Instagram OAuth без секретных данных."""


class InstagramOAuthTransportError(InstagramOAuthError):
    def __init__(
        self,
        *,
        status: Any = "unknown",
        error_code: Any = "unknown",
        error_type: Any = "transport_error",
        safe_message: Any = "Meta request failed",
    ):
        super().__init__("Instagram OAuth Meta request failed.")
        self.status = _safe_log_identifier(status)
        self.error_code = _safe_log_identifier(error_code)
        self.error_type = _safe_log_identifier(error_type)
        self.safe_message = _safe_log_message(safe_message)


class InstagramOAuthTransportResponse:
    def __init__(self, payload: dict[str, Any], status: Any):
        self.payload = payload
        self.status = _safe_log_identifier(status)


def _safe_log_identifier(value: Any, fallback: str = "unknown") -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return fallback
    if not all(character.isalnum() or character in "_.-" for character in normalized):
        return fallback
    return normalized[:100]


def _safe_log_message(value: Any) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized[:300] or "Meta request failed"


def _redacted_meta_message(
    value: Any,
    parameters: dict[str, Any],
) -> str:
    message = _safe_log_message(value)
    for name in (
        "code",
        "access_token",
        "refresh_token",
        "client_secret",
        "state",
    ):
        secret_value = str(parameters.get(name) or "")
        if secret_value:
            message = message.replace(secret_value, "[REDACTED]")
    lowered = message.casefold()
    if any(
        marker in lowered
        for marker in (
            "access_token=",
            "refresh_token=",
            "client_secret=",
            "code=",
            "state=",
            "cookie=",
        )
    ):
        return "Meta rejected the OAuth request"
    return message


def _meta_error_details(
    payload: Any,
    parameters: dict[str, Any],
) -> tuple[str, str, str]:
    if not isinstance(payload, dict):
        return "unknown", "invalid_response", "Meta returned an invalid response"

    nested_error = payload.get("error")
    error = nested_error if isinstance(nested_error, dict) else payload
    error_code = _safe_log_identifier(
        error.get("code", error.get("error_code"))
    )
    error_type = _safe_log_identifier(
        error.get("type", error.get("error_type")),
        "meta_error",
    )
    message = error.get("message", error.get("error_message"))
    return (
        error_code,
        error_type,
        _redacted_meta_message(message, parameters),
    )


def _log_oauth_stage(
    stage: str,
    *,
    status: Any,
    error_code: Any,
    error_type: Any,
    message: Any,
    failed: bool = False,
) -> None:
    logger_method = current_app.logger.warning if failed else current_app.logger.info
    logger_method(
        "Instagram OAuth stage=%s status=%s error_code=%s error_type=%s message=%s",
        _safe_log_identifier(stage),
        _safe_log_identifier(status),
        _safe_log_identifier(error_code, "none"),
        _safe_log_identifier(error_type, "none"),
        _safe_log_message(message),
    )


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
    if configuration["redirect_uri"] != INSTAGRAM_REDIRECT_URI:
        raise InstagramOAuthError("Instagram OAuth не настроен.")

    return configuration


def build_instagram_authorization_url(
    configuration: dict[str, str],
    oauth_state: str,
) -> str:
    return INSTAGRAM_AUTHORIZATION_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": configuration["app_id"],
            "redirect_uri": configuration["redirect_uri"],
            "response_type": "code",
            "scope": ",".join(INSTAGRAM_OAUTH_SCOPES),
            "state": oauth_state,
        }
    )


def instagram_setup_link_is_ready(setup_token: Any) -> bool:
    """Проверяет setup-ссылку без записи state и обращения к Meta."""
    route_available = any(
        rule.endpoint == "instagram_oauth.instagram_connect"
        and "GET" in rule.methods
        for rule in current_app.url_map.iter_rules()
    )
    if not route_available:
        return False
    if not _invitation_store().is_setup_token_valid(setup_token):
        return False

    try:
        configuration = _oauth_configuration()
    except InstagramOAuthError:
        return False

    preview_state = secrets.token_urlsafe(32)
    authorization_url = build_instagram_authorization_url(
        configuration,
        preview_state,
    )
    parsed = urllib.parse.urlparse(authorization_url)
    parameters = urllib.parse.parse_qs(parsed.query)
    return (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == INSTAGRAM_AUTHORIZATION_URL
        and parameters.get("client_id") == [configuration["app_id"]]
        and parameters.get("redirect_uri") == [INSTAGRAM_REDIRECT_URI]
        and parameters.get("response_type") == ["code"]
        and parameters.get("scope") == [",".join(INSTAGRAM_OAUTH_SCOPES)]
        and parameters.get("state") == [preview_state]
    )


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
    try:
        with urllib.request.urlopen(oauth_request, timeout=30) as response:
            status = getattr(response, "status", 200)
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise InstagramOAuthTransportError(
                    status=status,
                    error_type="invalid_json",
                    safe_message="Meta returned an invalid JSON response",
                ) from None
    except urllib.error.HTTPError as error:
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            error_payload = {}
        error_code, error_type, safe_message = _meta_error_details(
            error_payload,
            parameters,
        )
        raise InstagramOAuthTransportError(
            status=error.code,
            error_code=error_code,
            error_type=error_type,
            safe_message=safe_message,
        ) from None

    if not isinstance(payload, dict):
        raise InstagramOAuthTransportError(
            status=status,
            error_type="invalid_response",
            safe_message="Meta returned an invalid response",
        )

    return InstagramOAuthTransportResponse(payload, status)


def _oauth_transport():
    return current_app.config.get(
        "INSTAGRAM_OAUTH_TRANSPORT",
        _default_oauth_transport,
    )


def _oauth_stage_request(
    stage: str,
    transport: Any,
    url: str,
    *,
    method: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = transport(
            url,
            method=method,
            parameters=parameters,
        )
    except InstagramOAuthTransportError as error:
        _log_oauth_stage(
            stage,
            status=error.status,
            error_code=error.error_code,
            error_type=error.error_type,
            message=_redacted_meta_message(error.safe_message, parameters),
            failed=True,
        )
        raise InstagramOAuthError("Instagram OAuth Meta request failed.") from None
    except Exception:
        _log_oauth_stage(
            stage,
            status="unknown",
            error_code="unknown",
            error_type="transport_error",
            message="Meta request failed",
            failed=True,
        )
        raise InstagramOAuthError("Instagram OAuth Meta request failed.") from None

    if isinstance(result, InstagramOAuthTransportResponse):
        payload = result.payload
        status = result.status
    else:
        payload = result
        status = 200
    if not isinstance(payload, dict):
        _log_oauth_stage(
            stage,
            status=status,
            error_code="unknown",
            error_type="invalid_response",
            message="Meta returned an invalid response",
            failed=True,
        )
        raise InstagramOAuthError("Instagram OAuth Meta request failed.")

    _log_oauth_stage(
        stage,
        status=status,
        error_code="none",
        error_type="none",
        message="success",
    )
    return payload


def _token_storage_path():
    return current_app.config.get("INSTAGRAM_TOKEN_ENV_PATH")


def _invitation_store():
    return current_app.extensions["instagram_oauth_store"]


def _safe_page(title: str, message: str, status_code: int = 200):
    return render_template(
        "instagram_oauth_result.html",
        title=title,
        message=message,
    ), status_code


def _connected_account_is_allowed(profile: Any) -> bool:
    if not isinstance(profile, dict):
        return False
    allowed_account_id = os.environ.get(
        INSTAGRAM_ACCOUNT_ID_ENVIRONMENT_VARIABLE,
        "",
    ).strip()
    if not allowed_account_id:
        return False
    candidate_ids = {
        str(profile.get("id") or "").strip(),
        str(profile.get("user_id") or "").strip(),
    }
    if any(
        candidate
        and secrets.compare_digest(candidate, allowed_account_id)
        for candidate in candidate_ids
    ):
        return True

    if allowed_account_id.isdecimal():
        return False

    allowed_username = allowed_account_id.removeprefix("@").casefold()
    connected_username = str(profile.get("username") or "").strip()
    connected_username = connected_username.removeprefix("@").casefold()
    return bool(
        allowed_username
        and connected_username
        and secrets.compare_digest(connected_username, allowed_username)
    )


@instagram_oauth_bp.get("/instagram/connect")
def instagram_connect():
    setup_token = request.args.get("setup_token", "").strip()
    if not setup_token:
        return _safe_page(
            "Ссылка недействительна",
            "Запросите новую ссылку подключения у администратора.",
            403,
        )

    try:
        configuration = _oauth_configuration()
    except InstagramOAuthError:
        return _safe_page(
            "Instagram OAuth не настроен",
            "Обратитесь к администратору PostParser.",
            503,
        )

    oauth_state = _invitation_store().create_oauth_state(setup_token)
    if not oauth_state:
        return _safe_page(
            "Ссылка недействительна",
            "Ссылка уже использована или срок её действия истёк.",
            403,
        )

    authorization_url = build_instagram_authorization_url(
        configuration,
        oauth_state,
    )
    response = redirect(authorization_url)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@instagram_oauth_bp.get("/instagram/callback")
def instagram_callback():
    state = request.args.get("state", "").strip()
    invitation_id = _invitation_store().consume_state(state)
    if invitation_id is None:
        current_app.logger.warning("Instagram OAuth state validation failed.")
        return _safe_page(
            "Ссылка недействительна",
            "Проверка безопасности Instagram OAuth не пройдена.",
            403,
        )

    if request.args.get("error"):
        _invitation_store().release_invitation_claim(invitation_id)
        current_app.logger.warning("Instagram OAuth was declined.")
        return _safe_page(
            "Instagram не подключён",
            "Авторизация Instagram была отменена.",
            400,
        )

    code = request.args.get("code", "").strip()
    if not code:
        _invitation_store().release_invitation_claim(invitation_id)
        current_app.logger.warning("Instagram OAuth callback has no code.")
        return _safe_page(
            "Instagram не подключён",
            "Instagram не вернул код авторизации.",
            400,
        )

    try:
        configuration = _oauth_configuration(require_secret=True)
        transport = _oauth_transport()
        short_token_payload = _oauth_stage_request(
            "exchange_code_for_short_token",
            transport,
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
            _log_oauth_stage(
                "exchange_code_for_short_token",
                status=200,
                error_code="missing_access_token",
                error_type="invalid_response",
                message="Meta response did not contain an access token",
                failed=True,
            )
            raise InstagramOAuthError(
                "Instagram OAuth не вернул access token."
            )

        long_token_payload = _oauth_stage_request(
            "exchange_short_token_for_long_token",
            transport,
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
        profile = _oauth_stage_request(
            "fetch_instagram_account",
            transport,
            INSTAGRAM_PROFILE_URL,
            method="GET",
            parameters={
                "fields": "id,user_id,username,account_type",
                "access_token": access_token,
            },
        )
        if not _connected_account_is_allowed(profile):
            _log_oauth_stage(
                "validate_account",
                status="not_applicable",
                error_code="account_not_allowed",
                error_type="validation_error",
                message="Instagram account is not allowed",
                failed=True,
            )
            _invitation_store().release_invitation_claim(invitation_id)
            current_app.logger.warning(
                "Instagram OAuth connected account is not allowed."
            )
            return _safe_page(
                "Аккаунт не разрешён",
                "Эта ссылка предназначена для другого Instagram-аккаунта.",
                403,
            )
        _log_oauth_stage(
            "validate_account",
            status="not_applicable",
            error_code="none",
            error_type="none",
            message="success",
        )
        try:
            save_instagram_access_token(
                access_token,
                path=_token_storage_path(),
            )
            invitation_marked_used = _invitation_store().mark_invitation_used(
                invitation_id
            )
        except InstagramTokenStorageError:
            _log_oauth_stage(
                "save_token",
                status="not_applicable",
                error_code="storage_error",
                error_type="storage_error",
                message="Instagram token could not be saved",
                failed=True,
            )
            raise
        except Exception:
            _log_oauth_stage(
                "save_token",
                status="not_applicable",
                error_code="storage_error",
                error_type="storage_error",
                message="Instagram token could not be saved",
                failed=True,
            )
            raise
        if not invitation_marked_used:
            _log_oauth_stage(
                "save_token",
                status="not_applicable",
                error_code="invitation_update_failed",
                error_type="storage_error",
                message="OAuth invitation could not be completed",
                failed=True,
            )
            raise InstagramOAuthError(
                "Instagram OAuth invitation could not be completed."
            )
        _log_oauth_stage(
            "save_token",
            status="not_applicable",
            error_code="none",
            error_type="none",
            message="success",
        )
    except (InstagramOAuthError, InstagramTokenStorageError):
        _invitation_store().release_invitation_claim(invitation_id)
        current_app.logger.warning("Instagram OAuth could not be completed.")
        return _safe_page(
            "Instagram не подключён",
            "Не удалось завершить подключение Instagram.",
            502,
        )
    except Exception:
        _invitation_store().release_invitation_claim(invitation_id)
        current_app.logger.warning("Instagram OAuth request failed.")
        return _safe_page(
            "Instagram не подключён",
            "Не удалось завершить подключение Instagram.",
            502,
        )

    return _safe_page(
        "Instagram успешно подключён",
        "Эту страницу можно закрыть.",
    )
