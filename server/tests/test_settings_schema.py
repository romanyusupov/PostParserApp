import copy
import unittest

from server.postparser_web.settings_schema import (
    SettingsValidationError,
    prepare_settings,
    validate_settings,
)


def make_valid_settings(network="vk"):
    date_start = ""
    date_end = ""

    if network in {"telegram", "instagram"}:
        date_start = "2026-07-01"
        date_end = "2026-07-31"

    return {
        "groups": [
            {
                "id": "group_1",
                "name": "Тестовая группа",
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
        ],
        "savedAt": "",
    }


class PrepareSettingsTestCase(unittest.TestCase):
    def test_normalizes_tg_ig_and_vk(self):
        settings = {
            "groups": [
                {
                    "id": "tg",
                    "name": "Telegram",
                    "network": "tg",
                    "url": "telegram",
                    "advertisingTypes": [],
                },
                {
                    "id": "ig",
                    "name": "Instagram",
                    "network": "ig",
                    "url": "instagram",
                    "advertisingTypes": [],
                },
                {
                    "id": "vk",
                    "name": "VK",
                    "network": "vk",
                    "url": "vk",
                    "advertisingTypes": [],
                },
            ]
        }

        prepared = prepare_settings(settings)

        self.assertEqual(
            [group["network"] for group in prepared["groups"]],
            ["telegram", "instagram", "vk"],
        )

    def test_cleans_whitespace(self):
        settings = make_valid_settings()
        group = settings["groups"][0]
        group["id"] = "  group_1  "
        group["name"] = "  Тестовая   группа  "
        group["url"] = "  https://example.com/group  "
        group["advertisingTypes"][0]["type"] = (
            "  Прямая   реклама  "
        )
        group["advertisingTypes"][0]["postWords"] = [
            "  рекламная   фраза  "
        ]

        prepared = prepare_settings(settings)
        prepared_group = prepared["groups"][0]

        self.assertEqual(prepared_group["id"], "group_1")
        self.assertEqual(
            prepared_group["name"],
            "Тестовая группа",
        )
        self.assertEqual(
            prepared_group["url"],
            "https://example.com/group",
        )
        self.assertEqual(
            prepared_group["advertisingTypes"][0]["type"],
            "Прямая реклама",
        )
        self.assertEqual(
            prepared_group["advertisingTypes"][0]["postWords"],
            ["рекламная фраза"],
        )

    def test_removes_duplicate_words(self):
        settings = make_valid_settings()
        advertising_type = (
            settings["groups"][0]["advertisingTypes"][0]
        )
        advertising_type["postWords"] = [
            "Ёлка",
            "елка",
            "РЕКЛАМА",
            "реклама",
        ]
        advertising_type["videoWords"] = [
            "Видео",
            "видео",
        ]

        prepared = prepare_settings(settings)
        prepared_type = (
            prepared["groups"][0]["advertisingTypes"][0]
        )

        self.assertEqual(
            prepared_type["postWords"],
            ["Ёлка", "РЕКЛАМА"],
        )
        self.assertEqual(
            prepared_type["videoWords"],
            ["Видео"],
        )

    def test_does_not_modify_source_dictionary(self):
        settings = make_valid_settings()
        settings["groups"][0]["name"] = "  Исходная   группа  "
        settings["groups"][0]["advertisingTypes"][0][
            "postWords"
        ] = ["Ёлка", "елка"]
        original = copy.deepcopy(settings)

        prepared = prepare_settings(settings)

        self.assertEqual(settings, original)
        self.assertIsNot(prepared, settings)
        self.assertIsNot(
            prepared["groups"],
            settings["groups"],
        )


class ValidateSettingsTestCase(unittest.TestCase):
    def test_valid_settings_pass_validation(self):
        for network in ("vk", "telegram", "instagram"):
            with self.subTest(network=network):
                validate_settings(
                    make_valid_settings(network)
                )

    def test_empty_groups_are_valid_for_a_new_or_cleared_user(self):
        validate_settings({"groups": [], "savedAt": ""})

    def test_rejects_duplicate_group_names(self):
        settings = make_valid_settings()
        duplicate = copy.deepcopy(settings["groups"][0])
        duplicate["id"] = "group_2"
        duplicate["name"] = "тестовая группа"
        settings["groups"].append(duplicate)

        with self.assertRaisesRegex(
            SettingsValidationError,
            "повторяется",
        ):
            validate_settings(settings)

    def test_rejects_invalid_date(self):
        settings = make_valid_settings()
        settings["groups"][0]["dateStart"] = "2026-02-30"

        with self.assertRaisesRegex(
            SettingsValidationError,
            "YYYY-MM-DD",
        ):
            validate_settings(settings)

    def test_rejects_reverse_date_range(self):
        settings = make_valid_settings()
        settings["groups"][0]["dateStart"] = "2026-08-01"
        settings["groups"][0]["dateEnd"] = "2026-07-31"

        with self.assertRaisesRegex(
            SettingsValidationError,
            "не может быть позже",
        ):
            validate_settings(settings)

    def test_requires_both_dates_for_telegram_and_instagram(self):
        for network in ("telegram", "instagram"):
            for missing_field in ("dateStart", "dateEnd"):
                with self.subTest(
                    network=network,
                    missing_field=missing_field,
                ):
                    settings = make_valid_settings(network)
                    settings["groups"][0][missing_field] = ""

                    with self.assertRaisesRegex(
                        SettingsValidationError,
                        "дату начала и дату окончания",
                    ):
                        validate_settings(settings)

    def test_rejects_duplicate_advertising_types(self):
        settings = make_valid_settings()
        settings["groups"][0]["advertisingTypes"].append(
            {
                "type": "прямая реклама",
                "postWords": [],
                "videoWords": [],
            }
        )

        with self.assertRaisesRegex(
            SettingsValidationError,
            "повторяется",
        ):
            validate_settings(settings)

    def test_rejects_invalid_post_words_and_video_words(self):
        for field_name, invalid_value in (
            ("postWords", "не список"),
            ("postWords", ["строка", 123]),
            ("videoWords", "не список"),
            ("videoWords", ["строка", None]),
        ):
            with self.subTest(
                field_name=field_name,
                invalid_value=invalid_value,
            ):
                settings = make_valid_settings()
                settings["groups"][0]["advertisingTypes"][0][
                    field_name
                ] = invalid_value

                with self.assertRaises(
                    SettingsValidationError
                ):
                    validate_settings(settings)


if __name__ == "__main__":
    unittest.main()
