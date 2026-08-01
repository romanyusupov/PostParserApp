import os
import urllib.parse

from flask import Blueprint, current_app, jsonify

from server.postparser_web.google_sheets_export import (
    GoogleSheetsConfigurationError,
    GoogleSheetsExportError,
)


results_export_bp = Blueprint("results_export", __name__)


def _error_response(message, status_code):
    return jsonify(
        {
            "success": False,
            "error": message,
        }
    ), status_code


def _is_google_sheets_url(value):
    if not isinstance(value, str):
        return False

    parsed_url = urllib.parse.urlparse(value)
    return (
        parsed_url.scheme == "https"
        and parsed_url.hostname == "docs.google.com"
        and parsed_url.path.startswith("/spreadsheets/")
    )


def _export_url(result):
    result_url = result.get("url") if isinstance(result, dict) else None
    if _is_google_sheets_url(result_url):
        return result_url

    spreadsheet_id = (
        current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID")
        or os.environ.get("POSTPARSER_GOOGLE_SPREADSHEET_ID", "")
    )
    spreadsheet_id = str(spreadsheet_id).strip()
    if not spreadsheet_id:
        raise GoogleSheetsConfigurationError(
            "Google Spreadsheet ID не настроен."
        )

    encoded_id = urllib.parse.quote(spreadsheet_id, safe="")
    return f"https://docs.google.com/spreadsheets/d/{encoded_id}/edit"


@results_export_bp.post(
    "/api/v1/results/runs/<int:run_id>/export/google-sheets"
)
def export_run_to_google_sheets(run_id):
    try:
        exporter = current_app.extensions["google_sheets_exporter"]
        if exporter is None:
            raise GoogleSheetsConfigurationError(
                "Экспорт Google Sheets не настроен."
            )

        result = exporter.export_run(run_id)
        url = _export_url(result)
    except GoogleSheetsConfigurationError:
        return _error_response(
            "Экспорт Google Sheets не настроен",
            503,
        )
    except GoogleSheetsExportError as error:
        if str(error).rstrip(".") == "Запуск не найден":
            return _error_response("Запуск не найден", 404)
        return _error_response(
            "Не удалось экспортировать результаты",
            502,
        )
    except Exception:
        current_app.logger.error(
            "Внутренняя ошибка API экспорта Google Sheets."
        )
        return _error_response("Внутренняя ошибка сервера", 500)

    return jsonify(
        {
            "success": True,
            "url": url,
        }
    )
