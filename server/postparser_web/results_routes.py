from flask import Blueprint, current_app, jsonify, render_template


results_bp = Blueprint("results", __name__)


def _internal_error_response():
    return jsonify(
        {
            "success": False,
            "error": "Внутренняя ошибка сервера",
        }
    ), 500


@results_bp.get("/results")
def results_page():
    return render_template(
        "results.html",
        active_section="results",
    )


@results_bp.get("/api/v1/results/runs")
def list_result_runs():
    try:
        runs = current_app.extensions["results_store"].list_runs(
            limit=50
        )
    except Exception:
        current_app.logger.exception(
            "Не удалось загрузить запуски для страницы результатов."
        )
        return _internal_error_response()

    return jsonify(
        {
            "success": True,
            "runs": runs,
        }
    )


@results_bp.get("/api/v1/results/runs/<int:run_id>/posts")
def list_run_posts(run_id):
    results_store = current_app.extensions["results_store"]

    try:
        run = results_store.get_run(run_id)
        if run is None:
            return jsonify(
                {
                    "success": False,
                    "error": "Запуск не найден",
                }
            ), 404

        posts = results_store.get_posts(
            group_id=run["group_id"],
            network=run["network"],
        )
        run_posts = [
            post
            for post in posts
            if post.get("run_id") == run_id
        ]
    except Exception:
        current_app.logger.exception(
            "Не удалось загрузить публикации запуска."
        )
        return _internal_error_response()

    return jsonify(
        {
            "success": True,
            "posts": run_posts,
        }
    )
