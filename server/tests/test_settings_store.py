import pathlib
import sqlite3
import tempfile
import unittest

from server.postparser_web.settings_store import (
    RevisionConflict,
    SettingsStore,
)


class SettingsStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            pathlib.Path(self.temporary_directory.name)
            / "settings.sqlite3"
        )
        self.store = SettingsStore(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_first_load_returns_empty_settings_at_revision_zero(self):
        self.assertEqual(
            self.store.load(),
            {
                "revision": 0,
                "settings": {
                    "groups": [],
                    "savedAt": "",
                },
            },
        )

    def test_settings_round_trip_preserves_cyrillic(self):
        settings = {
            "groups": [
                {
                    "id": "group_1",
                    "name": "Олег Торсунов",
                    "network": "telegram",
                }
            ],
            "savedAt": "сейчас",
        }

        saved = self.store.save(settings, expected_revision=0)

        self.assertEqual(saved["settings"], settings)
        self.assertEqual(self.store.load()["settings"], settings)

        database_text = self.database_path.read_bytes().decode(
            "utf-8",
            errors="ignore",
        )
        self.assertIn("Олег Торсунов", database_text)

    def test_revision_increases_after_each_save(self):
        first = self.store.save(
            {"groups": [], "savedAt": "первое сохранение"},
            expected_revision=0,
        )
        second = self.store.save(
            {"groups": [], "savedAt": "второе сохранение"},
            expected_revision=first["revision"],
        )

        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(self.store.load()["revision"], 2)

    def test_stale_revision_raises_revision_conflict(self):
        self.store.save(
            {"groups": [], "savedAt": "актуальные настройки"},
            expected_revision=0,
        )

        with self.assertRaises(RevisionConflict) as context:
            self.store.save(
                {"groups": [], "savedAt": "устаревшие настройки"},
                expected_revision=0,
            )

        self.assertEqual(context.exception.expected_revision, 0)
        self.assertEqual(context.exception.current_revision, 1)

    def test_conflict_does_not_damage_previous_settings(self):
        current_settings = {
            "groups": [{"name": "Сохранённая группа"}],
            "savedAt": "до конфликта",
        }
        self.store.save(current_settings, expected_revision=0)

        with self.assertRaises(RevisionConflict):
            self.store.save(
                {
                    "groups": [{"name": "Не должна сохраниться"}],
                    "savedAt": "после конфликта",
                },
                expected_revision=0,
            )

        self.assertEqual(
            self.store.load(),
            {
                "revision": 1,
                "settings": current_settings,
            },
        )

    def test_two_store_instances_share_database(self):
        second_store = SettingsStore(self.database_path)
        settings = {
            "groups": [{"name": "Общие настройки"}],
            "savedAt": "",
        }

        saved = self.store.save(settings, expected_revision=0)

        self.assertEqual(
            second_store.load(),
            {
                "revision": saved["revision"],
                "settings": settings,
            },
        )

    def test_settings_are_isolated_by_owner_and_admin_keeps_legacy_key(self):
        admin_settings = {"groups": [], "savedAt": "admin"}
        user_settings = {"groups": [], "savedAt": "user"}

        self.store.save(admin_settings, 0, owner_id="admin")
        self.store.save(user_settings, 0, owner_id="user:1")

        self.assertEqual(self.store.load("admin")["settings"], admin_settings)
        self.assertEqual(self.store.load("user:1")["settings"], user_settings)
        self.assertEqual(self.store.load("user:2")["revision"], 0)

        connection = sqlite3.connect(self.database_path)
        try:
            keys = {
                row[0]
                for row in connection.execute(
                    "SELECT key FROM settings_documents"
                ).fetchall()
            }
        finally:
            connection.close()
        self.assertEqual(
            keys,
            {"parser_settings", "parser_settings:user:1"},
        )


if __name__ == "__main__":
    unittest.main()
