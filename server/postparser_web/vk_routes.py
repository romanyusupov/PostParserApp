import os

from flask import Blueprint, current_app, jsonify, request

from server.postparser_web.vk_parser import (
    VkApiError,
    VkConfigurationError,
    VkParser,
    VkParserError,
)


VK_ACCESS_TOKEN_ENVIRONMENT_VARIABLE = "POSTPARSER_VK_ACCESS_TOKEN"

vk_blueprint = Blueprint(
    "vk",
    __name__,
)


def _error_response(message, status_code):
    return jsonify(
        {
            "success": False,
            "error": message,
        }
    ), status_code


def _safe_parser_error_message(error, access_token):
    message = str(error).strip()

    if access_token:
        message = message.replace(access_token, "[скрыто]")

    return message or "Не удалось выполнить VK-парсинг."


def _redact_access_token(value, access_token):
    if not access_token:
        return value

    if isinstance(value, str):
        return value.replace(access_token, "[скрыто]")

    if isinstance(value, (list, tuple)):
        return [
            _redact_access_token(item, access_token)
            for item in value
        ]

    if isinstance(value, dict):
        return {
            _redact_access_token(key, access_token):
                _redact_access_token(item, access_token)
            for key, item in value.items()
        }

    return value


def _find_group(stored_document, group_id):
    if not isinstance(stored_document, dict):
        return None

    settings = stored_document.get("settings")
    if not isinstance(settings, dict):
        return None

    groups = settings.get("groups")
    if not isinstance(groups, list):
        return None

    for group in groups:
        if isinstance(group, dict) and group.get("id") == group_id:
            return group

    return None


def _log_internal_error(error, access_token=""):
    if not access_token:
        access_token = os.environ.get(
            VK_ACCESS_TOKEN_ENVIRONMENT_VARIABLE,
            "",
        ).strip()

    safe_error = RuntimeError(
        _safe_parser_error_message(error, access_token)
    )
    current_app.logger.exception(
        "Не удалось выполнить shadow VK-парсинг.",
        exc_info=(
            RuntimeError,
            safe_error,
            error.__traceback__,
        ),
    )


@vk_blueprint.post("/api/v1/vk/parse")
def parse_vk_group():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return _error_response(
            "Тело запроса должно быть JSON-словарём.",
            400,
        )

    group_id = payload.get("groupId")
    if not isinstance(group_id, str) or not group_id.strip():
        return _error_response(
            "Поле groupId должно быть непустой строкой.",
            400,
        )

    try:
        stored_document = current_app.extensions[
            "settings_store"
        ].load()
    except Exception as error:
        _log_internal_error(error)
        return _error_response(
            "Внутренняя ошибка сервера.",
            500,
        )

    group = _find_group(stored_document, group_id)
    if group is None:
        return _error_response(
            "Группа с указанным groupId не найдена.",
            404,
        )

    if group.get("network") != "vk":
        return _error_response(
            "VK-парсинг доступен только для VK-групп.",
            400,
        )

    group_url = group.get("url")
    if not isinstance(group_url, str) or not group_url.strip():
        return _error_response(
            "Для VK-группы не указан URL.",
            400,
        )

    date_start = group.get("dateStart")
    if not isinstance(date_start, str) or not date_start.strip():
        return _error_response(
            "Для VK-группы не указана дата начала.",
            400,
        )

    date_end = group.get("dateEnd")
    if not isinstance(date_end, str) or not date_end.strip():
        return _error_response(
            "Для VK-группы не указана дата окончания.",
            400,
        )

    access_token = os.environ.get(
        VK_ACCESS_TOKEN_ENVIRONMENT_VARIABLE,
        "",
    ).strip()

    if not access_token:
        return _error_response(
            "VK-подключение не настроено.",
            503,
        )

    parser_factory = (
        current_app.config.get("VK_PARSER_FACTORY")
        or VkParser
    )

    try:
        parser = parser_factory(access_token)
        posts = parser.fetch_posts(
            group_url,
            date_start,
            date_end,
        )
    except VkConfigurationError:
        return _error_response(
            "VK-подключение не настроено.",
            503,
        )
    except VkApiError as error:
        return _error_response(
            _safe_parser_error_message(error, access_token),
            502,
        )
    except VkParserError as error:
        return _error_response(
            _safe_parser_error_message(error, access_token),
            502,
        )
    except Exception as error:
        _log_internal_error(error, access_token)
        return _error_response(
            "Внутренняя ошибка сервера.",
            500,
        )

    return jsonify(
        _redact_access_token(
            {
                "success": True,
                "mode": "shadow",
                "groupId": group_id,
                "groupName": str(group.get("name") or ""),
                "source": "vk",
                "count": len(posts),
                "posts": posts,
            },
            access_token,
        )
    )
