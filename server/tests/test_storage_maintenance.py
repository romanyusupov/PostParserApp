import datetime
import os
import pathlib
import tempfile
import unittest

from server.postparser_web.storage_maintenance import StorageRetentionService


class FakeResultsStore:
    def __init__(self, image_urls=()):
        self.image_urls = set(image_urls)
        self.prune_group_calls = []
        self.prune_all_calls = []
        self.maintenance_calls = 0

    def prune_group_runs(self, group_id, keep):
        self.prune_group_calls.append((group_id, keep))
        return 2

    def prune_all_group_runs(self, keep):
        self.prune_all_calls.append(keep)
        return 4

    def list_image_urls(self):
        return set(self.image_urls)

    def maintain_database(self):
        self.maintenance_calls += 1


class StorageRetentionServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.media_directory = pathlib.Path(self.temporary_directory.name)
        self.now = datetime.datetime(
            2026,
            8,
            4,
            12,
            0,
            tzinfo=datetime.timezone.utc,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _photo(self, character, age_days):
        path = self.media_directory / (character * 64 + ".jpg")
        path.write_bytes(b"photo")
        modified = self.now - datetime.timedelta(days=age_days)
        os.utime(path, (modified.timestamp(), modified.timestamp()))
        return path

    def _service(self, image_urls=()):
        store = FakeResultsStore(image_urls)
        service = StorageRetentionService(
            store,
            self.media_directory,
            runs_per_group=3,
            media_grace_days=7,
            now_factory=lambda: self.now,
        )
        return store, service

    def test_old_unreferenced_photo_is_deleted(self):
        old_unreferenced = self._photo("a", 8)
        old_referenced = self._photo("b", 8)
        fresh_unreferenced = self._photo("c", 6)
        unrelated = self.media_directory / "notes.txt"
        unrelated.write_text("keep", encoding="utf-8")
        store, service = self._service(
            [f"https://parser.test/media/telegram/{old_referenced.name}"]
        )

        deleted = service.remove_unreferenced_media()

        self.assertEqual(deleted, 1)
        self.assertFalse(old_unreferenced.exists())
        self.assertTrue(old_referenced.exists())
        self.assertTrue(fresh_unreferenced.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(len(store.list_image_urls()), 1)

    def test_relative_telegram_photo_url_is_recognized(self):
        referenced = self._photo("d", 30)
        _, service = self._service(
            [f"/media/telegram/{referenced.name}"]
        )

        self.assertEqual(service.remove_unreferenced_media(), 0)
        self.assertTrue(referenced.exists())

    def test_cleanup_group_prunes_only_requested_group(self):
        store, service = self._service()

        result = service.cleanup_group("group_1")

        self.assertEqual(store.prune_group_calls, [("group_1", 3)])
        self.assertEqual(result, {"deleted_runs": 2, "deleted_media": 0})

    def test_maintenance_prunes_media_and_compacts_database(self):
        old_unreferenced = self._photo("e", 10)
        store, service = self._service()

        result = service.maintain_all()

        self.assertEqual(store.prune_all_calls, [3])
        self.assertEqual(store.maintenance_calls, 1)
        self.assertFalse(old_unreferenced.exists())
        self.assertEqual(result, {"deleted_runs": 4, "deleted_media": 1})


if __name__ == "__main__":
    unittest.main()
