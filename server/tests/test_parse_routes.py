import pathlib
import tempfile
import unittest

from server.postparser_web import create_app
from server.postparser_web.parse_runner import (
    ParseRunnerConfigurationError,
    ParseRunnerGroupNotFoundError,
)
from server.postparser_web.parse_service import ParserExecutionError


class MockRunner:
    def __init__(self):
        self.calls = []
        self.error = None
        self.result = {
            "run_id": 1,
            "group_id": "group_1",
            "group_name": "Тест",
            "network": "vk",
            "count": 10,
            "status": "completed",
            "posts": [{"external_id": "must-not-be-returned"}],
        }

    def run_group(self, group_id, owner_id="admin"):
        self.calls.append(group_id)
        if self.error is not None:
            raise self.error

        result = dict(self.result)
        result["group_id"] = group_id
        return result


class ParseRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = (
            pathlib.Path(self.temporary_directory.name)
            / "settings.sqlite3"
        )
        self.runner = MockRunner()
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": database_path,
                "PARSE_RUNNER": self.runner,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def post(self, payload=None, **kwargs):
        if payload is not None:
            kwargs["json"] = payload
        return self.client.post("/api/v1/parse", **kwargs)

    def test_successful_post_returns_ok(self):
        response = self.post({"groupId": "group_1"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    def test_group_id_is_passed_to_runner(self):
        self.post({"groupId": " group_1 "})

        self.assertEqual(self.runner.calls, ["group_1"])

    def test_response_contains_run_id(self):
        response = self.post({"groupId": "group_1"})

        self.assertEqual(response.get_json()["runId"], 1)

    def test_response_contains_count(self):
        response = self.post({"groupId": "group_1"})

        self.assertEqual(response.get_json()["count"], 10)

    def test_response_does_not_contain_posts(self):
        response = self.post({"groupId": "group_1"})

        self.assertNotIn("posts", response.get_json())
        self.assertEqual(response.get_json()["status"], "completed")

    def test_non_json_request_returns_bad_request(self):
        response = self.post(data="groupId=group_1")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Ожидается JSON"},
        )

    def test_empty_json_returns_bad_request(self):
        response = self.post({})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    def test_missing_group_id_returns_bad_request(self):
        response = self.post({"anotherField": "value"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("groupId", response.get_json()["error"])

    def test_unknown_group_returns_not_found(self):
        self.runner.error = ParseRunnerGroupNotFoundError("missing")

        response = self.post({"groupId": "missing"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Группа не найдена"},
        )

    def test_parser_error_returns_bad_gateway(self):
        self.runner.error = ParserExecutionError("parser failed")

        response = self.post({"groupId": "group_1"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"], "Ошибка парсера")

    def test_configuration_error_returns_service_unavailable(self):
        self.runner.error = ParseRunnerConfigurationError("not configured")

        response = self.post({"groupId": "group_1"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["error"],
            "Ошибка конфигурации парсера",
        )

    def test_internal_error_returns_server_error(self):
        self.runner.error = RuntimeError("internal private details")

        response = self.post({"groupId": "group_1"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Внутренняя ошибка сервера"},
        )

    def test_internal_error_response_has_no_traceback(self):
        self.runner.error = RuntimeError("internal private details")

        response = self.post({"groupId": "group_1"})
        response_text = response.get_data(as_text=True)

        self.assertNotIn("Traceback", response_text)
        self.assertNotIn("internal private details", response_text)

    def test_mock_runner_is_installed_in_app_extensions(self):
        self.assertIs(self.app.extensions["parse_runner"], self.runner)


if __name__ == "__main__":
    unittest.main()
