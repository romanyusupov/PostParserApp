import pathlib
import tempfile
import unittest

from server.postparser_web import create_app
from server.postparser_web.results_store import ResultsStore


class UnusedRunner:
    def run_group(self, group_id):
        raise AssertionError("Реальный запуск парсинга запрещён в этих тестах")


class BrokenResultsStore:
    def get_run(self, run_id):
        raise RuntimeError("private database details")

    def list_runs(self, limit=50):
        raise RuntimeError("private database details")


class RunRoutesTestCase(unittest.TestCase):
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

    def test_existing_run_returns_ok(self):
        run_id = self.results_store.create_run(
            "group_1",
            "Тестовая группа",
            "vk",
        )

        response = self.client.get(f"/api/v1/runs/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(response.get_json()["run"]["id"], run_id)

    def test_run_response_contains_status(self):
        run_id = self.results_store.create_run("group_1", "Группа", "vk")

        response = self.client.get(f"/api/v1/runs/{run_id}")

        self.assertEqual(response.get_json()["run"]["status"], "running")

    def test_run_response_contains_count(self):
        run_id = self.results_store.create_run("group_1", "Группа", "vk")
        self.results_store.finish_run(run_id, 12)

        response = self.client.get(f"/api/v1/runs/{run_id}")

        self.assertEqual(response.get_json()["run"]["count"], 12)

    def test_missing_run_returns_not_found(self):
        response = self.client.get("/api/v1/runs/999999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Запуск не найден"},
        )

    def test_runs_list_returns_ok(self):
        response = self.client.get("/api/v1/runs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"success": True, "runs": []},
        )

    def test_runs_list_is_limited_to_fifty(self):
        for index in range(55):
            self.results_store.create_run(
                f"group_{index}",
                f"Группа {index}",
                "vk",
            )

        response = self.client.get("/api/v1/runs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["runs"]), 50)

    def test_runs_list_is_sorted_newest_first(self):
        run_ids = [
            self.results_store.create_run(
                f"group_{index}",
                f"Группа {index}",
                "vk",
            )
            for index in range(3)
        ]

        response = self.client.get("/api/v1/runs")

        self.assertEqual(
            [run["id"] for run in response.get_json()["runs"]],
            list(reversed(run_ids)),
        )

    def test_internal_error_returns_server_error(self):
        self.app.extensions["results_store"] = BrokenResultsStore()

        response = self.client.get("/api/v1/runs/1")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Внутренняя ошибка сервера"},
        )

    def test_internal_error_response_has_no_traceback(self):
        self.app.extensions["results_store"] = BrokenResultsStore()

        response = self.client.get("/api/v1/runs")
        response_text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("Traceback", response_text)
        self.assertNotIn("private database details", response_text)


if __name__ == "__main__":
    unittest.main()
