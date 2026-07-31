import pathlib
import tempfile
import unittest

from server.postparser_web import create_app


def make_group(
    group_id="group_1",
    name="Тестовая группа",
    network="vk",
):
    date_start = ""
    date_end = ""

    if network in {"tg", "telegram", "ig", "instagram"}:
        date_start = "2026-07-01"
        date_end = "2026-07-31"

    return {
        "id": group_id,
        "name": name,
        "network": network,
        "url": "https://example.com/group",
        "dateStart": date_start,
        "dateEnd": date_end,
        "advertisingTypes": [
            {
                "type": "Прямая реклама",
                "postWords": ["реклама"],
                "videoWords": ["видео"],
            }
        ],
    }


def make_settings(groups=None):
    if groups is None:
        groups = [make_group()]

    return {
        "groups": groups,
        "savedAt": "",
    }


class BrokenSettingsStore:
    def load(self):
        raise RuntimeError("внутренний текст ошибки хранилища")


class SettingsRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = (
            pathlib.Path(self.temporary_directory.name)
            / "settings.sqlite3"
        )
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": database_path,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def put(self, revision, settings):
        return self.client.put(
            "/api/v1/settings",
            json={
                "revision": revision,
                "settings": settings,
            },
        )

    def test_get_new_database_returns_revision_zero(self):
        response = self.client.get("/api/v1/settings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "success": True,
                "mode": "shadow",
                "revision": 0,
                "settings": {
                    "groups": [],
                    "savedAt": "",
                },
            },
        )

    def test_put_valid_settings_returns_revision_one(self):
        response = self.put(0, make_settings())
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "shadow")
        self.assertEqual(data["revision"], 1)
        self.assertTrue(data["settings"]["savedAt"])

    def test_get_returns_saved_settings(self):
        saved_response = self.put(
            0,
            make_settings(
                [
                    make_group(
                        name="Сохранённая группа"
                    )
                ]
            ),
        )

        response = self.client.get("/api/v1/settings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["settings"],
            saved_response.get_json()["settings"],
        )

    def test_second_put_increases_revision(self):
        first = self.put(0, make_settings())
        second = self.put(
            first.get_json()["revision"],
            make_settings(
                [make_group(name="Вторая версия")]
            ),
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["revision"], 2)

    def test_stale_revision_returns_conflict(self):
        self.put(0, make_settings())

        response = self.put(
            0,
            make_settings(
                [make_group(name="Устаревшая версия")]
            ),
        )
        data = response.get_json()

        self.assertEqual(response.status_code, 409)
        self.assertFalse(data["success"])
        self.assertEqual(data["currentRevision"], 1)

    def test_empty_or_invalid_groups_return_bad_request(self):
        for groups in ([], "не список"):
            with self.subTest(groups=groups):
                response = self.put(
                    0,
                    {
                        "groups": groups,
                        "savedAt": "",
                    },
                )

                self.assertEqual(response.status_code, 400)

    def test_missing_revision_returns_bad_request(self):
        response = self.client.put(
            "/api/v1/settings",
            json={"settings": make_settings()},
        )

        self.assertEqual(response.status_code, 400)

    def test_string_revision_returns_bad_request(self):
        response = self.put("0", make_settings())

        self.assertEqual(response.status_code, 400)

    def test_settings_are_saved_after_tg_and_ig_normalization(self):
        settings = make_settings(
            [
                make_group(
                    group_id="telegram_group",
                    name="Telegram",
                    network="tg",
                ),
                make_group(
                    group_id="instagram_group",
                    name="Instagram",
                    network="ig",
                ),
            ]
        )

        response = self.put(0, settings)
        networks = [
            group["network"]
            for group in response.get_json()["settings"]["groups"]
        ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            networks,
            ["telegram", "instagram"],
        )

    def test_cyrillic_is_preserved(self):
        response = self.put(
            0,
            make_settings(
                [
                    make_group(
                        name="Олег Торсунов — кириллица"
                    )
                ]
            ),
        )

        loaded = self.client.get(
            "/api/v1/settings"
        ).get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            loaded["settings"]["groups"][0]["name"],
            "Олег Торсунов — кириллица",
        )

    def test_store_error_returns_generic_internal_error(self):
        self.app.extensions["settings_store"] = (
            BrokenSettingsStore()
        )

        response = self.client.get("/api/v1/settings")
        response_text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {
                "success": False,
                "error": "Внутренняя ошибка сервера.",
            },
        )
        self.assertNotIn(
            "внутренний текст ошибки хранилища",
            response_text,
        )


if __name__ == "__main__":
    unittest.main()
