import os
import pathlib
import tempfile
import unittest
from unittest import mock

from server.postparser_web import create_app


class HealthRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_directory = pathlib.Path(self.temporary_directory.name)

        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": (
                    self.data_directory / "settings.sqlite3"
                ),
                "RESULTS_DATABASE_PATH": (
                    self.data_directory / "results.sqlite3"
                ),
                "PARSE_RUNNER": object(),
                "GOOGLE_SHEETS_EXPORTER": object(),
            }
        )
        self.client = self.app.test_client()

    def _data_snapshot(self):
        return {
            path.relative_to(self.data_directory): (
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in self.data_directory.rglob("*")
            if path.is_file()
        }

    def test_health_returns_exact_json_response(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_health_works_without_secrets_or_external_clients(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)

    def test_repeated_health_requests_do_not_write_data(self):
        before = self._data_snapshot()

        for _ in range(3):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)

        self.assertEqual(self._data_snapshot(), before)

    def test_favicon_is_available_as_static_icon(self):
        response = self.client.get("/static/favicon.ico")
        self.addCleanup(response.close)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            response.mimetype,
            {"image/x-icon", "image/vnd.microsoft.icon"},
        )
        self.assertGreater(len(response.data), 0)

    def test_every_page_template_references_the_shared_favicon(self):
        templates_directory = (
            pathlib.Path(__file__).parents[1]
            / "postparser_web"
            / "templates"
        )

        for template_name in (
            "login.html",
            "admin_access.html",
            "settings.html",
            "results.html",
        ):
            with self.subTest(template=template_name):
                template = (templates_directory / template_name).read_text(
                    encoding="utf-8"
                )
                self.assertIn(
                    "url_for('static', filename='favicon.ico')",
                    template,
                )


if __name__ == "__main__":
    unittest.main()
