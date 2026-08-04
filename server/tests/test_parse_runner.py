import pathlib
import sqlite3
import tempfile
import unittest

from server.postparser_web.parse_runner import (
    ParseRunnerGroupNotFoundError,
    ParseRunnerService,
)
from server.postparser_web.results_store import ResultsStore


POSTS = [
    {
        "source": "vk",
        "external_id": "post_1",
        "url": "https://vk.com/wall-1_1",
        "published_at": "2026-07-15T12:00:00+00:00",
        "text": "Тестовая публикация",
    },
    {
        "source": "vk",
        "external_id": "post_2",
        "url": "https://vk.com/wall-1_2",
        "published_at": "2026-07-14T12:00:00+00:00",
        "text": "Вторая публикация",
    },
]


def make_group(
    group_id="group_1",
    name="Тестовая группа",
    network="vk",
):
    return {
        "id": group_id,
        "name": name,
        "network": network,
        "url": "https://vk.com/test",
        "dateStart": "2026-07-01",
        "dateEnd": "2026-07-31",
    }


class FakeSettingsStore:
    def __init__(self, groups):
        self.groups = groups
        self.calls = []

    def load(self):
        self.calls.append("load")
        return {
            "revision": 1,
            "settings": {"groups": self.groups, "savedAt": ""},
        }


class FakeParseService:
    def __init__(self, result=None, error=None, events=None):
        self.result = result or {
            "group_id": "group_1",
            "group_name": "Тестовая группа",
            "network": "vk",
            "count": len(POSTS),
            "posts": POSTS,
        }
        self.error = error
        self.calls = []
        self.events = events

    def parse_group(self, group_id):
        self.calls.append(group_id)
        if self.events is not None:
            self.events.append("parse_group")
        if self.error is not None:
            raise self.error
        return self.result


class RecordingResultsStore:
    def __init__(self, events=None):
        self.events = events
        self.create_calls = []
        self.save_calls = []
        self.finish_calls = []
        self.fail_calls = []

    def _event(self, name):
        if self.events is not None:
            self.events.append(name)

    def create_run(self, group_id, group_name, network):
        self._event("create_run")
        self.create_calls.append((group_id, group_name, network))
        return 42

    def save_posts(self, run_id, posts):
        self._event("save_posts")
        self.save_calls.append((run_id, posts))
        return len(posts)

    def finish_run(self, run_id, count, warning=""):
        self._event("finish_run")
        self.finish_calls.append((run_id, count, warning))

    def fail_run(self, run_id, count):
        self._event("fail_run")
        self.fail_calls.append((run_id, count))


class FinishFailingResultsStore(ResultsStore):
    def finish_run(self, run_id, count, warning=""):
        raise RuntimeError("finish failed")


class FakeStorageRetention:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def cleanup_group(self, group_id):
        self.calls.append(group_id)
        if self.error is not None:
            raise self.error
        return {"deleted_runs": 0, "deleted_media": 0}


class ParseRunnerServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.group = make_group()
        self.settings_store = FakeSettingsStore([self.group])
        self.parse_service = FakeParseService()
        self.results_store = RecordingResultsStore()
        self.runner = ParseRunnerService(
            self.settings_store,
            self.parse_service,
            self.results_store,
        )

    def test_successful_run_uses_required_order(self):
        events = []
        runner = ParseRunnerService(
            FakeSettingsStore([self.group]),
            FakeParseService(events=events),
            RecordingResultsStore(events=events),
        )

        runner.run_group("group_1")

        self.assertEqual(
            events,
            ["create_run", "parse_group", "save_posts", "finish_run"],
        )

    def test_group_metadata_is_passed_to_create_run(self):
        self.runner.run_group("group_1")

        self.assertEqual(
            self.results_store.create_calls,
            [("group_1", "Тестовая группа", "vk")],
        )

    def test_posts_are_saved_for_created_run(self):
        self.runner.run_group("group_1")

        self.assertEqual(
            self.results_store.save_calls,
            [(42, POSTS)],
        )

    def test_run_is_finished_with_post_count(self):
        self.runner.run_group("group_1")

        self.assertEqual(self.results_store.finish_calls, [(42, 2, "")])
        self.assertEqual(self.results_store.fail_calls, [])

    def test_result_has_unified_format(self):
        result = self.runner.run_group("group_1")

        self.assertEqual(
            result,
            {
                "run_id": 42,
                "group_id": "group_1",
                "group_name": "Тестовая группа",
                "network": "vk",
                "count": 2,
                "posts": POSTS,
            },
        )

    def test_successful_run_triggers_storage_retention(self):
        retention = FakeStorageRetention()
        runner = ParseRunnerService(
            self.settings_store,
            self.parse_service,
            self.results_store,
            storage_retention=retention,
        )

        runner.run_group("group_1")

        self.assertEqual(retention.calls, ["group_1"])

    def test_storage_retention_error_does_not_fail_completed_run(self):
        retention = FakeStorageRetention(RuntimeError("cleanup failed"))
        runner = ParseRunnerService(
            self.settings_store,
            self.parse_service,
            self.results_store,
            storage_retention=retention,
        )

        with self.assertLogs(
            "server.postparser_web.storage_maintenance",
            level="ERROR",
        ):
            result = runner.run_group("group_1")

        self.assertEqual(result["run_id"], 42)
        self.assertEqual(self.results_store.fail_calls, [])

    def test_parser_error_marks_run_as_failed(self):
        source_error = RuntimeError("parser failed")
        parse_service = FakeParseService(error=source_error)
        runner = ParseRunnerService(
            self.settings_store,
            parse_service,
            self.results_store,
        )

        with self.assertRaises(RuntimeError) as context:
            runner.run_group("group_1")

        self.assertIs(context.exception, source_error)
        self.assertEqual(self.results_store.fail_calls, [(42, 0)])
        self.assertEqual(self.results_store.finish_calls, [])

    def test_failed_run_does_not_trigger_storage_retention(self):
        retention = FakeStorageRetention()
        runner = ParseRunnerService(
            self.settings_store,
            FakeParseService(error=RuntimeError("parser failed")),
            self.results_store,
            storage_retention=retention,
        )

        with self.assertRaises(RuntimeError):
            runner.run_group("group_1")

        self.assertEqual(retention.calls, [])

    def test_insights_warning_completes_run_and_preserves_posts(self):
        warning = (
            "Instagram Insights unavailable: missing "
            "instagram_business_manage_insights"
        )
        posts = [
            {
                "source": "instagram",
                "external_id": "media_1",
                "url": "https://instagram.com/p/media_1/",
                "published_at": "2026-07-15T12:00:00+00:00",
                "text": "Публикация без Insights",
                "views": None,
                "reach": None,
                "saved": None,
                "shares": None,
            }
        ]
        parse_service = FakeParseService(
            result={
                "group_id": "group_1",
                "group_name": "Instagram",
                "network": "instagram",
                "count": 1,
                "posts": posts,
                "warning": warning,
            }
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            store = ResultsStore(
                pathlib.Path(temporary_directory) / "results.sqlite3"
            )
            runner = ParseRunnerService(
                FakeSettingsStore([make_group(network="instagram")]),
                parse_service,
                store,
            )

            result = runner.run_group("group_1")
            run = store.get_run(result["run_id"])
            saved_posts = store.get_posts(group_id="group_1")

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["warning"], warning)
        self.assertEqual(len(saved_posts), 1)
        self.assertEqual(saved_posts[0]["views"], "")

    def test_unknown_group_does_not_create_run(self):
        runner = ParseRunnerService(
            FakeSettingsStore([]),
            self.parse_service,
            self.results_store,
        )

        with self.assertRaises(ParseRunnerGroupNotFoundError):
            runner.run_group("missing")

        self.assertEqual(self.results_store.create_calls, [])

    def test_saved_posts_survive_finish_error_and_run_becomes_failed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = (
                pathlib.Path(temporary_directory) / "results.sqlite3"
            )
            results_store = FinishFailingResultsStore(database_path)
            runner = ParseRunnerService(
                self.settings_store,
                self.parse_service,
                results_store,
            )

            with self.assertRaisesRegex(RuntimeError, "finish failed"):
                runner.run_group("group_1")

            posts = results_store.get_posts(group_id="group_1")
            connection = sqlite3.connect(database_path)
            try:
                run = connection.execute(
                    "SELECT status, count FROM parse_runs"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(len(posts), 2)
        self.assertEqual(run, ("failed", 2))


if __name__ == "__main__":
    unittest.main()
