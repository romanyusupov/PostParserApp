import datetime
import pathlib
import sqlite3
import tempfile
import unittest

from server.postparser_web.results_store import (
    ResultsStore,
    ResultsStoreError,
)


def make_post(
    source="vk",
    external_id="post_1",
    text="Тестовая публикация",
    **values,
):
    post = {
        "source": source,
        "external_id": external_id,
        "url": f"https://example.test/{source}/{external_id}",
        "published_at": "2026-07-15T12:00:00+00:00",
        "text": text,
        "first_paragraph": text,
        "post_type": "Текст",
        "image_url": "",
        "video_url": "",
        "views": 10,
        "likes": 5,
        "comments": 2,
        "saved": 1,
        "shares": 3,
        "forwards": 4,
    }
    post.update(values)
    return post


class ResultsStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            pathlib.Path(self.temporary_directory.name)
            / "parse_results.sqlite3"
        )
        self.store = ResultsStore(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _load_run(self, run_id):
        connection = sqlite3.connect(self.database_path)
        try:
            return connection.execute(
                """
                SELECT group_id, group_name, network,
                       started_at, finished_at, count
                FROM parse_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        finally:
            connection.close()

    def test_run_is_created(self):
        run_id = self.store.create_run(
            "group_1",
            "Тестовая группа",
            "vk",
        )

        row = self._load_run(run_id)

        self.assertGreater(run_id, 0)
        self.assertEqual(row[:3], ("group_1", "Тестовая группа", "vk"))
        self.assertTrue(row[3])
        self.assertEqual(row[4:], ("", 0))
        self.assertIsNotNone(datetime.datetime.fromisoformat(row[3]).tzinfo)

    def test_run_is_finished(self):
        run_id = self.store.create_run("group_1", "Группа", "vk")

        result = self.store.finish_run(run_id, 7)
        row = self._load_run(run_id)

        self.assertEqual(result["count"], 7)
        self.assertEqual(row[5], 7)
        self.assertTrue(row[4])
        self.assertIsNotNone(datetime.datetime.fromisoformat(row[4]).tzinfo)

    def test_posts_are_saved(self):
        run_id = self.store.create_run("group_1", "Группа", "vk")

        inserted = self.store.save_posts(
            run_id,
            (make_post("vk", "one"), make_post("vk", "two")),
        )

        self.assertEqual(inserted, 2)
        self.assertEqual(len(self.store.get_posts()), 2)

    def test_posts_are_returned_and_can_be_filtered(self):
        vk_run = self.store.create_run("vk_group", "VK", "vk")
        tg_run = self.store.create_run("tg_group", "Telegram", "telegram")
        self.store.save_posts(vk_run, [make_post("vk", "vk_post")])
        self.store.save_posts(
            tg_run,
            [make_post("telegram", "tg_post")],
        )

        vk_posts = self.store.get_posts(group_id="vk_group", network="vk")

        self.assertEqual(len(vk_posts), 1)
        self.assertEqual(vk_posts[0]["external_id"], "vk_post")
        self.assertEqual(vk_posts[0]["group_id"], "vk_group")
        self.assertEqual(vk_posts[0]["network"], "vk")

    def test_cyrillic_is_preserved(self):
        run_id = self.store.create_run(
            "group_1",
            "Олег Торсунов",
            "telegram",
        )
        text = "Первый абзац\n\nПродолжение публикации"
        self.store.save_posts(
            run_id,
            [make_post("telegram", "one", text=text)],
        )

        post = self.store.get_posts()[0]
        database_text = self.database_path.read_bytes().decode(
            "utf-8",
            errors="ignore",
        )

        self.assertEqual(post["text"], text)
        self.assertEqual(post["group_name"], "Олег Торсунов")
        self.assertIn("Продолжение публикации", database_text)

    def test_empty_metrics_become_zero(self):
        run_id = self.store.create_run("group_1", "Группа", "instagram")
        post = make_post(
            "instagram",
            "one",
            views=None,
            likes="",
            comments="invalid",
            saved=None,
            shares=False,
            forwards=None,
        )

        self.store.save_posts(run_id, [post])
        saved_post = self.store.get_posts()[0]

        self.assertEqual(
            {
                field: saved_post[field]
                for field in (
                    "views",
                    "likes",
                    "comments",
                    "saved",
                    "shares",
                    "forwards",
                )
            },
            {
                "views": 0,
                "likes": 0,
                "comments": 0,
                "saved": 0,
                "shares": 0,
                "forwards": 0,
            },
        )

    def test_missing_text_fields_become_empty_strings(self):
        run_id = self.store.create_run("group_1", "Группа", "telegram")

        self.store.save_posts(run_id, [{}])
        saved_post = self.store.get_posts()[0]

        self.assertEqual(
            {
                field: saved_post[field]
                for field in (
                    "source",
                    "external_id",
                    "url",
                    "published_at",
                    "text",
                    "first_paragraph",
                    "post_type",
                    "image_url",
                    "video_url",
                )
            },
            {
                "source": "",
                "external_id": "",
                "url": "",
                "published_at": "",
                "text": "",
                "first_paragraph": "",
                "post_type": "",
                "image_url": "",
                "video_url": "",
            },
        )

    def test_same_external_id_from_different_sources_is_kept(self):
        run_id = self.store.create_run("group_1", "Группа", "mixed")

        self.store.save_posts(
            run_id,
            (
                make_post("vk", "same_id"),
                make_post("telegram", "same_id"),
            ),
        )

        self.assertEqual(
            {post["source"] for post in self.store.get_posts()},
            {"vk", "telegram"},
        )

    def test_failed_transaction_leaves_no_partial_posts(self):
        run_id = self.store.create_run("group_1", "Группа", "vk")

        with self.assertRaises(ResultsStoreError):
            self.store.save_posts(
                run_id,
                [make_post("vk", "valid"), "broken post"],
            )

        self.assertEqual(self.store.get_posts(), [])

    def test_duplicate_is_not_created_within_run_and_source(self):
        run_id = self.store.create_run("group_1", "Группа", "vk")
        duplicate = make_post("vk", "same_id")

        first_inserted = self.store.save_posts(run_id, [duplicate, duplicate])
        second_inserted = self.store.save_posts(run_id, [duplicate])

        self.assertEqual(first_inserted, 1)
        self.assertEqual(second_inserted, 0)
        self.assertEqual(len(self.store.get_posts()), 1)

    def test_unknown_fields_with_secrets_are_not_stored(self):
        run_id = self.store.create_run("group_1", "Группа", "vk")
        post = make_post("vk", "one")
        post["access_token"] = "fake-secret-that-must-not-be-stored"

        self.store.save_posts(run_id, [post])

        self.assertNotIn(
            b"fake-secret-that-must-not-be-stored",
            self.database_path.read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
