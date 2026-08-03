import os
import pathlib
import tempfile
import unittest
from unittest import mock

from server.postparser_web.google_sheets_export import (
    EXPORT_HEADERS,
    GoogleSheetsConfigurationError,
    GoogleSheetsExporter,
    GoogleSheetsExportError,
)
from server.postparser_web.results_store import ResultsStore


SPREADSHEET_ID = "spreadsheet-id-for-tests"
CREDENTIALS_JSON = '{"private_key":"fake-private-key"}'


class MockClient:
    def __init__(self, error=None):
        self.error = error
        self.created_sheets = []
        self.written_values = []

    def create_sheet(self, spreadsheet_id, sheet_name):
        if self.error is not None:
            raise self.error
        self.created_sheets.append((spreadsheet_id, sheet_name))

    def write_values(self, spreadsheet_id, sheet_name, rows):
        if self.error is not None:
            raise self.error
        self.written_values.append((spreadsheet_id, sheet_name, rows))


def make_post(external_id="post_1", **values):
    post = {
        "source": "vk",
        "external_id": external_id,
        "url": "https://example.test/post",
        "published_at": "2026-08-01T12:00:00+00:00",
        "text": "Полный текст публикации",
        "first_paragraph": "Первый абзац",
        "post_type": "Фото",
        "advertising_type": "Партнёрская публикация",
        "views": 10,
        "likes": 5,
        "comments": 2,
        "saved": 1,
        "shares": 3,
        "forwards": 0,
    }
    post.update(values)
    return post


class GoogleSheetsExporterTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.results_store = ResultsStore(
            pathlib.Path(self.temporary_directory.name) / "results.sqlite3"
        )
        self.client = MockClient()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_run(self, group_name="ОГТ", posts=None):
        run_id = self.results_store.create_run(
            "group_1",
            group_name,
            "vk",
        )
        self.results_store.save_posts(run_id, posts or [])
        self.results_store.finish_run(run_id, len(posts or []))
        return run_id

    def create_exporter(self, client=None):
        export_client = client or self.client
        return GoogleSheetsExporter(
            client_factory=lambda: export_client,
            spreadsheet_id=SPREADSHEET_ID,
            credentials_json=CREDENTIALS_JSON,
            results_store=self.results_store,
        )

    def test_missing_spreadsheet_id_is_rejected(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GoogleSheetsConfigurationError):
                GoogleSheetsExporter(credentials_json=CREDENTIALS_JSON)

    def test_missing_credentials_are_rejected(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GoogleSheetsConfigurationError):
                GoogleSheetsExporter(spreadsheet_id=SPREADSHEET_ID)

    def test_configuration_is_loaded_from_environment(self):
        environment = {
            "POSTPARSER_GOOGLE_SPREADSHEET_ID": SPREADSHEET_ID,
            "POSTPARSER_GOOGLE_SERVICE_ACCOUNT_JSON": CREDENTIALS_JSON,
        }
        run_id = self.create_run()

        with mock.patch.dict(os.environ, environment, clear=True):
            exporter = GoogleSheetsExporter(
                client_factory=lambda: self.client,
                results_store=self.results_store,
            )
            exporter.export_run(run_id)

        self.assertEqual(self.client.created_sheets[0][0], SPREADSHEET_ID)

    def test_export_creates_sheet(self):
        run_id = self.create_run()

        result = self.create_exporter().export_run(run_id)

        self.assertEqual(len(self.client.created_sheets), 1)
        self.assertEqual(self.client.created_sheets[0][1], result["sheet_name"])
        self.assertIn("VK ОГТ", result["sheet_name"])

    def test_headers_are_written_in_required_order(self):
        run_id = self.create_run()

        self.create_exporter().export_run(run_id)

        rows = self.client.written_values[0][2]
        self.assertEqual(rows[0], list(EXPORT_HEADERS))
        self.assertEqual(
            rows[0],
            [
                "Дата",
                "Сеть",
                "Группа",
                "Тип",
                "Тип рекламы",
                "Текст",
                "Первый абзац",
                "Ссылка",
                "Просмотры",
                "Лайки",
                "Комментарии",
                "Сохранения",
                "Репосты",
            ],
        )

    def test_post_values_are_written(self):
        run_id = self.create_run(posts=[make_post()])

        self.create_exporter().export_run(run_id)

        row = self.client.written_values[0][2][1]
        self.assertEqual(
            row,
            [
                "2026-08-01T12:00:00+00:00",
                "vk",
                "ОГТ",
                "Фото",
                "Партнёрская публикация",
                "Полный текст публикации",
                "Первый абзац",
                "https://example.test/post",
                10,
                5,
                2,
                1,
                3,
            ],
        )

    def test_missing_metrics_become_zero_and_forwards_are_supported(self):
        run_id = self.create_run(
            posts=[
                make_post(
                    views=None,
                    likes="",
                    comments="invalid",
                    saved=None,
                    shares=None,
                    forwards=7,
                )
            ]
        )

        self.create_exporter().export_run(run_id)

        row = self.client.written_values[0][2][1]
        self.assertEqual(row[8:], [0, 0, 0, 0, 7])

    def test_old_post_without_advertising_type_exports_empty_cell(self):
        run_id = self.create_run(
            posts=[make_post(advertising_type=None)]
        )

        self.create_exporter().export_run(run_id)

        row = self.client.written_values[0][2][1]
        self.assertEqual(row[4], "")

    def test_cyrillic_is_preserved(self):
        run_id = self.create_run(
            group_name="Русская группа",
            posts=[make_post(text="Кириллица без потерь")],
        )

        self.create_exporter().export_run(run_id)

        row = self.client.written_values[0][2][1]
        self.assertEqual(row[2], "Русская группа")
        self.assertEqual(row[5], "Кириллица без потерь")

    def test_long_sheet_name_is_truncated(self):
        run_id = self.create_run(group_name="Я" * 150)

        result = self.create_exporter().export_run(run_id)

        self.assertEqual(len(result["sheet_name"]), 100)
        self.assertEqual(len(self.client.created_sheets[0][1]), 100)

    def test_client_error_becomes_safe_export_error(self):
        client = MockClient(error=RuntimeError("Google client failed"))
        run_id = self.create_run()

        with self.assertLogs(
            "server.postparser_web.google_sheets_export",
            level="ERROR",
        ):
            with self.assertRaises(GoogleSheetsExportError):
                self.create_exporter(client).export_run(run_id)

    def test_secrets_are_absent_from_exception_and_log(self):
        secret = "very-secret-private-key"
        spreadsheet_id = "complete-private-spreadsheet-id"
        client = MockClient(
            error=GoogleSheetsExportError(
                f"token={secret}; spreadsheet={spreadsheet_id}"
            )
        )
        run_id = self.create_run()
        exporter = GoogleSheetsExporter(
            client_factory=lambda: client,
            spreadsheet_id=spreadsheet_id,
            credentials_json=f'{{"private_key":"{secret}"}}',
            results_store=self.results_store,
        )

        with self.assertLogs(
            "server.postparser_web.google_sheets_export",
            level="ERROR",
        ) as logs:
            with self.assertRaises(GoogleSheetsExportError) as caught:
                exporter.export_run(run_id)

        combined_output = str(caught.exception) + "\n" + "\n".join(logs.output)
        self.assertNotIn(secret, combined_output)
        self.assertNotIn(spreadsheet_id, combined_output)
        self.assertNotIn("token=", combined_output)

    def test_only_injected_client_is_used(self):
        run_id = self.create_run(posts=[make_post()])
        factory_calls = []

        def client_factory():
            factory_calls.append(True)
            return self.client

        exporter = GoogleSheetsExporter(
            client_factory=client_factory,
            spreadsheet_id=SPREADSHEET_ID,
            credentials_json=CREDENTIALS_JSON,
            results_store=self.results_store,
        )

        exporter.export_run(run_id)

        self.assertEqual(factory_calls, [True])
        self.assertEqual(len(self.client.written_values), 1)


if __name__ == "__main__":
    unittest.main()
