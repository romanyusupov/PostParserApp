import os
import pathlib
import tempfile
import unittest
from unittest import mock

from server.postparser_web import create_app
from server.postparser_web.vk_parser import (
    VkApiError,
    VkConfigurationError,
    VkParserError,
)


TOKEN_ENVIRONMENT_VARIABLE = "POSTPARSER_VK_ACCESS_TOKEN"
TEST_TOKEN = "test-vk-token-never-returned"


def make_group(
    group_id="group_1",
    name="Тестовая VK-группа",
    network="vk",
    url="https://vk.com/test_group",
    date_start="2026-07-01",
    date_end="2026-07-31",
):
    return {
        "id": group_id,
        "name": name,
        "network": network,
        "url": url,
        "dateStart": date_start,
        "dateEnd": date_end,
        "advertisingTypes": [],
    }


class FakeVkParser:
    def __init__(self):
        self.posts = [
            {
                "source": "vk",
                "external_id": "-123_456",
                "url": "https://vk.com/wall-123_456",
                "published_at": "2026-07-10T12:00:00+00:00",
                "text": "Тестовая публикация",
                "first_paragraph": "Тестовая публикация",
                "post_type": "Текст",
                "image_url": "",
                "video_description": "",
                "views": 1,
                "likes": 2,
                "comments": 3,
            }
        ]
        self.fetch_calls = []
        self.error = None

    def fetch_posts(self, group_url, date_start, date_end):
        self.fetch_calls.append(
            (group_url, date_start, date_end)
        )

        if self.error is not None:
            raise self.error

        return self.posts


class BrokenSettingsStore:
    def load(self):
        raise RuntimeError("секретный текст ошибки хранилища")


class VkRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = (
            pathlib.Path(self.temporary_directory.name)
            / "settings.sqlite3"
        )
        self.parser = FakeVkParser()
        self.received_tokens = []
        self.factory_error = None

        def parser_factory(access_token):
            self.received_tokens.append(access_token)

            if self.factory_error is not None:
                raise self.factory_error

            return self.parser

        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": database_path,
                "VK_PARSER_FACTORY": parser_factory,
            }
        )
        self.client = self.app.test_client()
        self.store = self.app.extensions["settings_store"]
        self.token_patch = mock.patch.dict(
            os.environ,
            {TOKEN_ENVIRONMENT_VARIABLE: TEST_TOKEN},
        )
        self.token_patch.start()

    def tearDown(self):
        self.token_patch.stop()
        self.temporary_directory.cleanup()

    def save_groups(self, groups):
        current_revision = self.store.load()["revision"]
        self.store.save(
            {
                "groups": groups,
                "savedAt": "",
            },
            expected_revision=current_revision,
        )

    def post(self, payload=None):
        if payload is None:
            payload = {"groupId": "group_1"}

        return self.client.post(
            "/api/v1/vk/parse",
            json=payload,
        )

    def test_valid_vk_request_returns_success_response(self):
        self.save_groups([make_group()])

        response = self.post()
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            data,
            {
                "success": True,
                "mode": "shadow",
                "groupId": "group_1",
                "groupName": "Тестовая VK-группа",
                "source": "vk",
                "count": 1,
                "posts": self.parser.posts,
            },
        )

    def test_response_contains_count_and_posts(self):
        self.save_groups([make_group()])
        self.parser.posts = [{"external_id": "one"}, {"external_id": "two"}]

        data = self.post().get_json()

        self.assertEqual(data["count"], 2)
        self.assertEqual(data["posts"], self.parser.posts)

    def test_requested_group_id_is_returned_exactly(self):
        self.save_groups(
            [make_group(group_id="exact_group_id")]
        )

        response = self.post({"groupId": "exact_group_id"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["groupId"],
            "exact_group_id",
        )

    def test_parser_receives_saved_url_and_dates(self):
        self.save_groups(
            [
                make_group(
                    url="https://vk.ru/saved_group",
                    date_start="2026-06-01",
                    date_end="2026-06-30",
                )
            ]
        )

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.parser.fetch_calls,
            [
                (
                    "https://vk.ru/saved_group",
                    "2026-06-01",
                    "2026-06-30",
                )
            ],
        )

    def test_factory_receives_token_from_environment(self):
        self.save_groups([make_group()])

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.received_tokens, [TEST_TOKEN])

    def test_missing_json_returns_bad_request(self):
        response = self.client.post("/api/v1/vk/parse")

        self.assertEqual(response.status_code, 400)

    def test_invalid_json_returns_bad_request(self):
        response = self.client.post(
            "/api/v1/vk/parse",
            data="{invalid",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_missing_group_id_returns_bad_request(self):
        response = self.post({})

        self.assertEqual(response.status_code, 400)

    def test_empty_group_id_returns_bad_request(self):
        for group_id in ("", "   "):
            with self.subTest(group_id=group_id):
                response = self.post({"groupId": group_id})

                self.assertEqual(response.status_code, 400)

    def test_unknown_group_returns_not_found(self):
        self.save_groups([make_group()])

        response = self.post({"groupId": "unknown"})

        self.assertEqual(response.status_code, 404)

    def test_non_vk_group_returns_bad_request(self):
        for network in ("telegram", "instagram"):
            with self.subTest(network=network):
                self.save_groups(
                    [make_group(network=network)]
                )

                response = self.post()

                self.assertEqual(response.status_code, 400)
                self.assertIn("только для VK", response.get_json()["error"])

    def test_missing_group_url_returns_bad_request(self):
        self.save_groups([make_group(url="")])

        response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertIn("URL", response.get_json()["error"])

    def test_missing_start_date_returns_bad_request(self):
        self.save_groups([make_group(date_start="")])

        response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertIn("дата начала", response.get_json()["error"])

    def test_missing_end_date_returns_bad_request(self):
        self.save_groups([make_group(date_end="")])

        response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertIn("дата окончания", response.get_json()["error"])

    def test_missing_token_returns_service_unavailable(self):
        self.save_groups([make_group()])

        with mock.patch.dict(
            os.environ,
            {TOKEN_ENVIRONMENT_VARIABLE: ""},
        ):
            response = self.post()

        self.assertEqual(response.status_code, 503)
        self.assertIn("не настроено", response.get_json()["error"])

    def test_configuration_error_returns_service_unavailable(self):
        self.save_groups([make_group()])
        self.factory_error = VkConfigurationError(
            "внутренняя ошибка конфигурации"
        )

        response = self.post()

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(
            "внутренняя ошибка конфигурации",
            response.get_data(as_text=True),
        )

    def test_vk_api_error_returns_bad_gateway(self):
        self.save_groups([make_group()])
        self.parser.error = VkApiError(5, "Ошибка авторизации VK")

        response = self.post()

        self.assertEqual(response.status_code, 502)
        self.assertIn("5", response.get_json()["error"])

    def test_vk_parser_error_returns_bad_gateway(self):
        self.save_groups([make_group()])
        self.parser.error = VkParserError(
            "VK вернул некорректный ответ."
        )

        response = self.post()

        self.assertEqual(response.status_code, 502)
        self.assertIn("некорректный ответ", response.get_json()["error"])

    def test_internal_error_returns_generic_server_error(self):
        self.save_groups([make_group()])
        self.parser.error = RuntimeError(
            "внутренний секретный текст"
        )

        response = self.post()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {
                "success": False,
                "error": "Внутренняя ошибка сервера.",
            },
        )
        self.assertNotIn(
            "внутренний секретный текст",
            response.get_data(as_text=True),
        )

    def test_settings_store_error_returns_generic_server_error(self):
        self.app.extensions["settings_store"] = BrokenSettingsStore()

        response = self.post()

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(
            "секретный текст ошибки хранилища",
            response.get_data(as_text=True),
        )

    def test_token_is_not_written_to_internal_error_log(self):
        self.save_groups([make_group()])
        self.parser.error = RuntimeError(
            f"Внутренняя ошибка с токеном {TEST_TOKEN}"
        )

        with self.assertLogs(self.app.logger, level="ERROR") as logs:
            response = self.post()

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(TEST_TOKEN, "\n".join(logs.output))

    def test_token_is_never_returned_in_json(self):
        self.save_groups([make_group()])
        self.parser.posts = [
            {
                "text": f"Ошибочный результат с токеном {TEST_TOKEN}"
            }
        ]

        success_response = self.post()

        self.assertEqual(success_response.status_code, 200)
        self.assertNotIn(
            TEST_TOKEN,
            success_response.get_data(as_text=True),
        )

        self.parser.error = VkParserError(
            f"Ошибка с токеном {TEST_TOKEN}"
        )

        error_response = self.post()

        self.assertEqual(error_response.status_code, 502)
        self.assertNotIn(
            TEST_TOKEN,
            error_response.get_data(as_text=True),
        )


if __name__ == "__main__":
    unittest.main()
