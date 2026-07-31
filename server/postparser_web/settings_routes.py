import datetime

from flask import Blueprint, current_app, jsonify, request

from server.postparser_web.settings_schema import (
    SettingsValidationError,
    prepare_settings,
    validate_settings,
)
from server.postparser_web.settings_store import RevisionConflict


settings_blueprint = Blueprint(
    "settings",
    __name__,
)


def _success_response(stored_document):
    return {
        "success": True,
        "mode": "shadow",
        "revision": stored_document["revision"],
        "settings": stored_document["settings"],
    }


def _internal_error_response():
    return jsonify(
        {
            "success": False,
            "error": "Внутренняя ошибка сервера.",
        }
    ), 500


@settings_blueprint.get("/api/v1/settings")
def get_settings():
    try:
        stored_document = current_app.extensions[
            "settings_store"
        ].load()
    except Exception:
        current_app.logger.exception(
            "Не удалось загрузить настройки."
        )
        return _internal_error_response()

    return jsonify(_success_response(stored_document))


@settings_blueprint.put("/api/v1/settings")
def put_settings():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(
            {
                "success": False,
                "error": "Тело запроса должно быть JSON-словарём.",
            }
        ), 400

    revision = payload.get("revision")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
    ):
        return jsonify(
            {
                "success": False,
                "error": (
                    "Поле revision должно быть целым "
                    "неотрицательным числом."
                ),
            }
        ), 400

    settings = payload.get("settings")
    if not isinstance(settings, dict):
        return jsonify(
            {
                "success": False,
                "error": "Поле settings должно быть словарём.",
            }
        ), 400

    try:
        prepared_settings = prepare_settings(settings)
        validate_settings(prepared_settings)
        prepared_settings["savedAt"] = (
            datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
        )

        stored_document = current_app.extensions[
            "settings_store"
        ].save(
            prepared_settings,
            expected_revision=revision,
        )
    except SettingsValidationError as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400
    except RevisionConflict as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
                "currentRevision": error.current_revision,
            }
        ), 409
    except Exception:
        current_app.logger.exception(
            "Не удалось сохранить настройки."
        )
        return _internal_error_response()

    return jsonify(_success_response(stored_document))
