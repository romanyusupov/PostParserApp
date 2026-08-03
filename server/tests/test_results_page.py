import pathlib
import re
import tempfile
import unittest

from server.postparser_web import create_app
from server.postparser_web.google_sheets_export import (
    GoogleSheetsConfigurationError,
    GoogleSheetsExportError,
)
from server.postparser_web.results_store import ResultsStore


class UnusedRunner:
    def run_group(self, group_id):
        raise AssertionError("Парсеры не должны запускаться в этих тестах")


class BrokenResultsStore:
    def list_runs(self, limit=50):
        raise RuntimeError("private database details")

    def get_run(self, run_id):
        raise RuntimeError("private database details")

    def get_posts(self, group_id=None, network=None):
        raise RuntimeError("private database details")


class MockExporter:
    def __init__(self, error=None):
        self.error = error
        self.run_ids = []

    def export_run(self, run_id):
        self.run_ids.append(run_id)
        if self.error is not None:
            raise self.error
        return {
            "url": "https://docs.google.com/spreadsheets/d/test-sheet/edit"
        }


def make_post(external_id="post_1"):
    return {
        "source": "vk",
        "external_id": external_id,
        "url": "https://example.test/post",
        "published_at": "2026-08-01T12:00:00+00:00",
        "text": "Текст публикации",
        "first_paragraph": "Текст публикации",
        "post_type": "Фото",
        "video_description": "Отдельное описание видео",
        "advertising_type": "Партнёрская публикация",
        "views": 10,
        "likes": 5,
        "comments": 2,
    }


class ResultsPageTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_path = pathlib.Path(self.temporary_directory.name)
        self.results_store = ResultsStore(
            temporary_path / "results.sqlite3"
        )
        self.exporter = MockExporter()
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": temporary_path / "settings.sqlite3",
                "RESULTS_STORE": self.results_store,
                "PARSE_RUNNER": UnusedRunner(),
                "GOOGLE_SHEETS_EXPORTER": self.exporter,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def get_script(self):
        response = self.client.get("/static/results.js")
        try:
            self.assertEqual(response.status_code, 200)
            return response.get_data(as_text=True)
        finally:
            response.close()

    def get_stylesheet(self):
        response = self.client.get("/static/results.css")
        try:
            self.assertEqual(response.status_code, 200)
            return response.get_data(as_text=True)
        finally:
            response.close()

    def test_results_page_returns_ok(self):
        response = self.client.get("/results")

        self.assertEqual(response.status_code, 200)

    def test_results_page_contains_title_and_tables(self):
        page = self.client.get("/results").get_data(as_text=True)

        self.assertIn("Результаты парсинга", page)
        self.assertIn("Группа", page)
        self.assertIn("Просмотры", page)
        self.assertIn("/static/results.js", page)
        self.assertIn("/static/results.css", page)
        self.assertIn("/static/results_logic.js", page)

    def test_publication_column_and_sort_buttons_are_accessible(self):
        page = self.client.get("/results").get_data(as_text=True)

        self.assertIn("Публикация", page)
        for field in ("views", "likes", "comments"):
            self.assertIn(f'data-sort-field="{field}"', page)
            self.assertIn(f'data-sort-header="{field}"', page)
        self.assertEqual(page.count('aria-sort="none"'), 3)
        self.assertIn("Сортировать по просмотрам по убыванию", page)

    def test_runs_api_returns_runs(self):
        run_id = self.results_store.create_run("group_1", "Группа", "vk")
        self.results_store.finish_run(run_id, 3)

        response = self.client.get("/api/v1/results/runs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["runs"][0]["id"], run_id)
        self.assertEqual(response.get_json()["runs"][0]["count"], 3)

    def test_posts_api_returns_only_selected_run_posts(self):
        selected_run = self.results_store.create_run(
            "group_1", "Группа", "vk"
        )
        other_run = self.results_store.create_run(
            "group_1", "Группа", "vk"
        )
        self.results_store.save_posts(selected_run, [make_post("selected")])
        self.results_store.save_posts(other_run, [make_post("other")])

        response = self.client.get(
            f"/api/v1/results/runs/{selected_run}/posts"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [post["external_id"] for post in response.get_json()["posts"]],
            ["selected"],
        )
        self.assertEqual(
            response.get_json()["posts"][0]["advertising_type"],
            "Партнёрская публикация",
        )
        self.assertEqual(
            response.get_json()["posts"][0]["video_description"],
            "Отдельное описание видео",
        )

    def test_advertising_type_column_and_empty_fallback_are_rendered(self):
        page = self.client.get("/results").get_data(as_text=True)
        script = self.get_script()

        self.assertIn("Тип рекламы", page)
        self.assertIn("post.advertising_type || \"—\"", script)
        self.assertIn("\"advertising-type-cell\"", script)

    def test_video_description_uses_safe_independent_expansion(self):
        page = self.client.get("/results").get_data(as_text=True)
        script = self.get_script()

        self.assertIn("Описание видео", page)
        self.assertIn("post.video_description", script)
        self.assertIn("appendExpandableTextCell(", script)
        self.assertIn(
            'appendExpandableTextCell(row, post.text, "post-text")',
            script,
        )
        self.assertIn('"video-description-cell"', script)
        self.assertGreaterEqual(script.count("appendExpandableTextCell("), 3)
        self.assertIn(
            "content.textContent = expanded ? collapsed.text : text;",
            script,
        )
        self.assertNotIn("innerHTML", script)

    def test_results_columns_are_in_required_order(self):
        page = self.client.get("/results").get_data(as_text=True)
        posts_section = page.index('id="postsSection"')
        headings = (
            "Дата",
            "Публикация",
            "Текст",
            "Тип",
            "Описание видео",
            "Тип рекламы",
            "Просмотры",
            "Лайки",
            "Комментарии",
        )

        positions = [page.index(heading, posts_section) for heading in headings]

        self.assertEqual(positions, sorted(positions))

    def test_results_layout_is_wider_and_keeps_safe_word_wrapping(self):
        stylesheet = self.get_stylesheet()
        page = self.client.get("/results").get_data(as_text=True)

        width_match = re.search(
            r"\.posts-table\s*\{[^}]*min-width:\s*(\d+)px;",
            stylesheet,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(width_match)
        self.assertGreaterEqual(int(width_match.group(1)), 1180)
        self.assertLessEqual(int(width_match.group(1)), 1250)
        self.assertNotIn("min-width: 1440px;", stylesheet)
        self.assertIn("width: min(1480px, calc(100% - 24px));", stylesheet)
        self.assertIn("width: 64px;", stylesheet)
        self.assertIn("height: 64px;", stylesheet)
        self.assertIn("padding: 12px 10px;", stylesheet)
        self.assertIn("font-size: 14px;", stylesheet)
        self.assertIn("overflow-wrap: break-word;", stylesheet)
        self.assertIn("word-break: normal;", stylesheet)
        self.assertIn("overflow-x: auto;", stylesheet)
        self.assertIn('class="posts-table"', page)
        for column_class in (
            "date-column",
            "publication-column",
            "text-column",
            "post-type-column",
            "video-description-column",
            "advertising-type-column",
            "views-column",
            "likes-column",
            "comments-column",
        ):
            self.assertIn(f'class="{column_class}"', page)

    def test_empty_data_has_empty_api_and_page_states(self):
        runs_response = self.client.get("/api/v1/results/runs")
        page = self.client.get("/results").get_data(as_text=True)
        script = self.get_script()

        self.assertEqual(
            runs_response.get_json(),
            {"success": True, "runs": []},
        )
        self.assertIn("Запусков пока нет.", page)
        self.assertIn("В этом запуске нет публикаций.", page)
        self.assertIn("runsEmptyState.hidden = runs.length !== 0;", script)
        self.assertIn(
            "postsEmptyState.hidden = displayedPosts.length !== 0;",
            script,
        )

    def test_existing_run_without_posts_returns_empty_list(self):
        run_id = self.results_store.create_run("group_1", "Группа", "vk")

        response = self.client.get(
            f"/api/v1/results/runs/{run_id}/posts"
        )

        self.assertEqual(
            response.get_json(),
            {"success": True, "posts": []},
        )

    def test_unknown_run_returns_not_found(self):
        response = self.client.get("/api/v1/results/runs/999999/posts")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Запуск не найден"},
        )

    def test_store_error_returns_generic_server_error(self):
        self.app.extensions["results_store"] = BrokenResultsStore()

        response = self.client.get("/api/v1/results/runs")
        response_text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Внутренняя ошибка сервера"},
        )
        self.assertNotIn("Traceback", response_text)
        self.assertNotIn("private database details", response_text)

    def test_posts_store_error_returns_server_error(self):
        self.app.extensions["results_store"] = BrokenResultsStore()

        response = self.client.get("/api/v1/results/runs/1/posts")

        self.assertEqual(response.status_code, 500)

    def test_results_script_does_not_use_inner_html(self):
        script = self.get_script()

        self.assertNotIn("innerHTML", script)
        self.assertIn("element.textContent = text;", script)
        self.assertIn('const runsApiUrl = "/api/v1/results/runs";', script)

    def test_publication_link_and_image_use_safe_dom_methods(self):
        script = self.get_script()

        self.assertIn(
            'const link = createElement("a", "", "Открыть");',
            script,
        )
        self.assertIn('link.target = "_blank";', script)
        self.assertIn('link.rel = "noopener noreferrer";', script)
        self.assertIn('image.loading = "lazy";', script)
        self.assertIn('image.addEventListener("error"', script)
        self.assertIn("resultsLogic.safeHttpUrl(post.url)", script)
        self.assertIn("resultsLogic.safeHttpUrl(post.image_url)", script)

    def test_empty_publication_values_and_text_use_neutral_dash(self):
        script = self.get_script()

        self.assertIn('createElement("span", "empty-value", "—")', script)
        self.assertIn("if (!text.trim())", script)
        self.assertIn("preview.appendChild(emptyValue())", script)
        self.assertIn("linkContainer.appendChild(emptyValue())", script)

    def test_long_text_uses_safe_expand_and_collapse_controls(self):
        script = self.get_script()

        self.assertIn("resultsLogic.collapsedText(", script)
        self.assertIn('"Показать полностью"', script)
        self.assertIn('"Свернуть"', script)
        self.assertIn('toggle.setAttribute("aria-expanded"', script)
        self.assertIn("content.textContent = expanded ? collapsed.text : text;", script)

    def test_sorting_is_client_side_and_updates_accessibility(self):
        script = self.get_script()

        self.assertIn("resultsLogic.nextSortState(", script)
        self.assertIn("resultsLogic.sortPosts(", script)
        self.assertIn('header.setAttribute("aria-sort", direction);', script)
        self.assertIn('direction === "descending"', script)
        self.assertIn('direction === "ascending"', script)
        self.assertIn('button.addEventListener("click"', script)

    def test_unavailable_metrics_are_not_rendered_as_zero(self):
        script_text = self.get_script()

        self.assertIn('value === null', script_text)
        self.assertIn('value === undefined', script_text)
        self.assertIn('value === ""', script_text)
        self.assertNotIn('Number.isFinite(metric) ? String(metric) : "0"', script_text)

    def test_google_sheets_export_button_is_in_page(self):
        page = self.client.get("/results").get_data(as_text=True)

        self.assertIn('id="exportGoogleSheetsButton"', page)
        self.assertIn("Экспортировать в Google Sheets", page)
        self.assertIn("hidden", page)

    def test_results_script_calls_google_sheets_export_api(self):
        script = self.get_script()

        self.assertIn('"/export/google-sheets"', script)
        self.assertIn('method: "POST"', script)
        self.assertIn("exportGoogleSheetsButton.disabled = true;", script)
        self.assertIn("Открыть Google Sheets", script)

    def test_successful_google_sheets_export_returns_url(self):
        response = self.client.post(
            "/api/v1/results/runs/42/export/google-sheets"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.exporter.run_ids, [42])
        self.assertEqual(
            response.get_json(),
            {
                "success": True,
                "url": "https://docs.google.com/spreadsheets/d/test-sheet/edit",
            },
        )

    def test_google_sheets_configuration_error_returns_503(self):
        self.exporter.error = GoogleSheetsConfigurationError("not configured")

        response = self.client.post(
            "/api/v1/results/runs/1/export/google-sheets"
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {
                "success": False,
                "error": "Экспорт Google Sheets не настроен",
            },
        )

    def test_google_sheets_export_error_returns_502(self):
        self.exporter.error = GoogleSheetsExportError("client details")

        response = self.client.post(
            "/api/v1/results/runs/1/export/google-sheets"
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.get_json(),
            {
                "success": False,
                "error": "Не удалось экспортировать результаты",
            },
        )

    def test_missing_export_run_returns_404(self):
        self.exporter.error = GoogleSheetsExportError("Запуск не найден.")

        response = self.client.post(
            "/api/v1/results/runs/999/export/google-sheets"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Запуск не найден"},
        )

    def test_internal_export_error_returns_safe_500(self):
        self.exporter.error = RuntimeError("private traceback details")

        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.post(
                "/api/v1/results/runs/1/export/google-sheets"
            )

        response_text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Внутренняя ошибка сервера"},
        )
        self.assertNotIn("Traceback", response_text)
        self.assertNotIn("private traceback details", response_text)


if __name__ == "__main__":
    unittest.main()
