import pathlib
import tempfile
import unittest

from server.postparser_web import create_app
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


def make_post(external_id="post_1"):
    return {
        "source": "vk",
        "external_id": external_id,
        "url": "https://example.test/post",
        "published_at": "2026-08-01T12:00:00+00:00",
        "text": "Текст публикации",
        "first_paragraph": "Текст публикации",
        "post_type": "Фото",
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
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": temporary_path / "settings.sqlite3",
                "RESULTS_STORE": self.results_store,
                "PARSE_RUNNER": UnusedRunner(),
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
        self.assertIn("postsEmptyState.hidden = posts.length !== 0;", script)

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


if __name__ == "__main__":
    unittest.main()
