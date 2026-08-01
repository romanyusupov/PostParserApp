from flask import Blueprint, current_app, jsonify


run_bp = Blueprint("runs", __name__)


def _internal_error_response():
    return jsonify(
        {
            "success": False,
            "error": "Внутренняя ошибка сервера",
        }
    ), 500


@run_bp.get("/api/v1/runs/<int:run_id>")
def get_run(run_id):
    try:
        run = current_app.extensions["results_store"].get_run(run_id)
    except Exception:
        current_app.logger.exception(
            "Не удалось загрузить запуск парсинга."
        )
        return _internal_error_response()

    if run is None:
        return jsonify(
            {
                "success": False,
                "error": "Запуск не найден",
            }
        ), 404

    return jsonify(
        {
            "success": True,
            "run": run,
        }
    )


@run_bp.get("/api/v1/runs")
def list_runs():
    try:
        runs = current_app.extensions["results_store"].list_runs(
            limit=50
        )
    except Exception:
        current_app.logger.exception(
            "Не удалось загрузить список запусков парсинга."
        )
        return _internal_error_response()

    return jsonify(
        {
            "success": True,
            "runs": runs[:50],
        }
    )
