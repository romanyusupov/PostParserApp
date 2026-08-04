from flask import Blueprint, current_app, jsonify, request

from server.postparser_web.instagram_parser import (
    InstagramConfigurationError,
    InstagramParserError,
)
from server.postparser_web.parse_runner import (
    ParseRunnerConfigurationError,
    ParseRunnerGroupNotFoundError,
    ParseRunnerNetworkBlockedError,
)
from server.postparser_web.parse_service import (
    ParseConfigurationError,
    ParseGroupNotFoundError,
    ParserExecutionError,
    UnsupportedNetworkError,
)
from server.postparser_web.telegram_parser import (
    TelegramConfigurationError,
    TelegramParserError,
)
from server.postparser_web.vk_parser import (
    VkConfigurationError,
    VkParserError,
)


parse_bp = Blueprint("parse", __name__)


def _error_response(message, status_code):
    return jsonify(
        {
            "success": False,
            "error": message,
        }
    ), status_code


@parse_bp.post("/api/v1/parse")
def launch_parse():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return _error_response("Ожидается JSON", 400)

    group_id = payload.get("groupId")
    if not isinstance(group_id, str) or not group_id.strip():
        return _error_response("Не указан groupId", 400)

    try:
        result = current_app.extensions["parse_runner"].run_group(
            group_id.strip()
        )
        response_payload = {
            "success": True,
            "runId": result["run_id"],
            "groupId": result["group_id"],
            "groupName": result["group_name"],
            "network": result["network"],
            "count": result["count"],
            "status": "completed",
        }
    except (ParseRunnerGroupNotFoundError, ParseGroupNotFoundError):
        return _error_response("Группа не найдена", 404)
    except ParseRunnerNetworkBlockedError:
        return _error_response(
            "Parsing for this network is temporarily handled by the legacy service.",
            409,
        )
    except (
        ParseRunnerConfigurationError,
        ParseConfigurationError,
        UnsupportedNetworkError,
        VkConfigurationError,
        InstagramConfigurationError,
        TelegramConfigurationError,
    ):
        return _error_response("Ошибка конфигурации парсера", 503)
    except (
        ParserExecutionError,
        VkParserError,
        InstagramParserError,
        TelegramParserError,
    ):
        return _error_response("Ошибка парсера", 502)
    except Exception:
        current_app.logger.exception(
            "Не удалось выполнить запуск парсинга."
        )
        return _error_response("Внутренняя ошибка сервера", 500)

    return jsonify(response_payload)
