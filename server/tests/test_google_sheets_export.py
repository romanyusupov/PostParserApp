import datetime
import os
import pathlib
import stat
import tempfile
import unittest
from unittest import mock

from server.postparser_web.google_sheets_export import (
    EXPORT_HEADERS,
    GoogleSheetsConfigurationError,
    GoogleSheetsExporter,
    GoogleSheetsExportError,
    build_export_row,
)
from server.postparser_web.results_store import ResultsStore


SPREADSHEET_ID = "spreadsheet-id-for-tests"
GROUP_NAME = "ВК Олег Торсунов"
EXPORTED_AT = datetime.datetime(
    2026,
    8,
    4,
    10,
    30,
    tzinfo=datetime.timezone.utc,
)


class MockClient:
    def __init__(self, existing_sheets=None, error=None):
        self.error = error
        self.existing_sheets = set(existing_sheets or [])
        self.created_sheets = []
        self.cleared_sheets = []
        self.written_values = []
        self.sheet_values = {}
        self.operations = []

    def _raise_if_needed(self):
        if self.error is not None:
            raise self.error

    def ensure_sheet(self, spreadsheet_id, sheet_name):
        self._raise_if_needed()
        self.operations.append(("ensure", spreadsheet_id, sheet_name))
        if sheet_name in self.existing_sheets:
            return False

        self.existing_sheets.add(sheet_name)
        self.created_sheets.append((spreadsheet_id, sheet_name))
        return True

    def clear_sheet(self, spreadsheet_id, sheet_name):
        self._raise_if_needed()
        self.operations.append(("clear", spreadsheet_id, sheet_name))
        self.cleared_sheets.append((spreadsheet_id, sheet_name))
        self.sheet_values[sheet_name] = []

    def write_values(self, spreadsheet_id, sheet_name, rows):
        self._raise_if_needed()
        copied_rows = [list(row) for row in rows]
        self.operations.append(("write", spreadsheet_id, sheet_name))
        self.written_values.append(
            (spreadsheet_id, sheet_name, copied_rows)
        )
        self.sheet_values[sheet_name] = copied_rows


def make_post(external_id="post_1", **values):
    post = {
        "source": "vk",
        "external_id": external_id,
        "url": "https://example.test/post",
        "published_at": "2026-08-01T12:00:00+00:00",
        "text": "Полный текст публикации",
        "first_paragraph": "Первый абзац",
        "post_type": "Фото",
        "video_description": "Описание видео",
        "advertising_type": "Партнёрская публикация",
        "image_url": "https://example.test/image.jpg",
        "views": 10,
        "likes": 5,
        "comments": 2,
    }
    post.update(values)
    return post


class GoogleSheetsExporterTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.temporary_path = pathlib.Path(self.temporary_directory.name)
        self.results_store = ResultsStore(
            self.temporary_path / "results.sqlite3"
        )
        self.credentials_path = self.temporary_path / "service-account.json"
        self.credentials_path.write_text(
            '{"private_key":"fake-private-key"}',
            encoding="utf-8",
        )
        os.chmod(self.credentials_path, 0o600)
        self.client = MockClient()

    def create_run(self, group_name=GROUP_NAME, posts=None):
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
            credentials_path=self.credentials_path,
            results_store=self.results_store,
            now_factory=lambda: EXPORTED_AT,
        )

    def test_missing_spreadsheet_id_is_rejected(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GoogleSheetsConfigurationError):
                GoogleSheetsExporter(
                    credentials_path=self.credentials_path,
                )

    def test_missing_credentials_are_rejected(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GoogleSheetsConfigurationError):
                GoogleSheetsExporter(spreadsheet_id=SPREADSHEET_ID)

    def test_configuration_is_loaded_from_environment(self):
        environment = {
            "GOOGLE_SPREADSHEET_ID": SPREADSHEET_ID,
            "GOOGLE_SHEETS_CREDENTIALS_PATH": str(self.credentials_path),
        }
        run_id = self.create_run()

        with mock.patch.dict(os.environ, environment, clear=True):
            exporter = GoogleSheetsExporter(
                client_factory=lambda: self.client,
                results_store=self.results_store,
                now_factory=lambda: EXPORTED_AT,
            )
            exporter.export_run(run_id)

        self.assertEqual(self.client.operations[0][1], SPREADSHEET_ID)

    @unittest.skipIf(os.name == "nt", "POSIX permissions are checked on VPS")
    def test_credentials_file_must_have_mode_0600(self):
        os.chmod(self.credentials_path, 0o644)

        with self.assertRaises(GoogleSheetsConfigurationError):
            self.create_exporter()

    def test_new_sheet_is_created_with_exact_group_name(self):
        run_id = self.create_run()

        result = self.create_exporter().export_run(run_id)

        self.assertEqual(result["sheet_name"], GROUP_NAME)
        self.assertEqual(
            self.client.created_sheets,
            [(SPREADSHEET_ID, GROUP_NAME)],
        )
        self.assertEqual(self.client.cleared_sheets, [])

    def test_existing_sheet_is_cleared_before_write(self):
        client = MockClient(existing_sheets={GROUP_NAME})
        run_id = self.create_run(posts=[make_post()])

        self.create_exporter(client).export_run(run_id)

        self.assertEqual(
            [operation[0] for operation in client.operations],
            ["ensure", "clear", "write"],
        )
        self.assertEqual(
            client.cleared_sheets,
            [(SPREADSHEET_ID, GROUP_NAME)],
        )

    def test_information_rows_and_headers_are_written(self):
        run_id = self.create_run()

        self.create_exporter().export_run(run_id)

        rows = self.client.written_values[0][2]
        self.assertEqual(rows[0], ["Группа", GROUP_NAME])
        self.assertEqual(rows[1], ["Дата экспорта", EXPORTED_AT.isoformat()])
        self.assertEqual(rows[2], ["Run", run_id])
        self.assertEqual(rows[3], [])
        self.assertEqual(rows[4], list(EXPORT_HEADERS))
        self.assertEqual(
            rows[4],
            [
                "Ссылка",
                "Дата",
                "Первый абзац",
                "Картинка",
                "Просмотры",
                "Лайки",
                "Комментарии",
                "Тип поста",
                "Описание видео",
                "Тип рекламы",
            ],
        )

    def test_post_values_are_written_in_results_table_order(self):
        run_id = self.create_run(posts=[make_post()])

        self.create_exporter().export_run(run_id)

        row = self.client.written_values[0][2][5]
        self.assertEqual(
            row,
            [
                "https://example.test/post",
                "2026-08-01T12:00:00+00:00",
                "Первый абзац",
                "https://example.test/image.jpg",
                10,
                5,
                2,
                "Фото",
                "Описание видео",
                "Партнёрская публикация",
            ],
        )

    def test_missing_values_export_as_empty_cells(self):
        row = build_export_row(
            make_post(
                image_url=None,
                views=None,
                likes="",
                comments="invalid",
                video_description=None,
                advertising_type=None,
            )
        )
        self.assertEqual(row[3], "")
        self.assertEqual(row[4:7], ["", "", ""])
        self.assertEqual(row[8:], ["", ""])

    def test_repeated_export_replaces_data_without_duplicates(self):
        run_id = self.create_run(posts=[make_post()])
        exporter = self.create_exporter()

        exporter.export_run(run_id)
        exporter.export_run(run_id)

        self.assertEqual(len(self.client.created_sheets), 1)
        self.assertEqual(len(self.client.cleared_sheets), 1)
        self.assertEqual(len(self.client.sheet_values[GROUP_NAME]), 6)
        self.assertEqual(
            self.client.sheet_values[GROUP_NAME][5][0],
            "https://example.test/post",
        )

    def test_long_sheet_name_is_truncated(self):
        run_id = self.create_run(group_name="Я" * 150)

        result = self.create_exporter().export_run(run_id)

        self.assertEqual(len(result["sheet_name"]), 100)

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
            error=RuntimeError(
                f"token={secret}; spreadsheet={spreadsheet_id}"
            )
        )
        run_id = self.create_run()
        exporter = GoogleSheetsExporter(
            client_factory=lambda: client,
            spreadsheet_id=spreadsheet_id,
            credentials_path=self.credentials_path,
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
            credentials_path=self.credentials_path,
            results_store=self.results_store,
        )

        exporter.export_run(run_id)

        self.assertEqual(factory_calls, [True])
        self.assertEqual(len(self.client.written_values), 1)


if __name__ == "__main__":
    unittest.main()
