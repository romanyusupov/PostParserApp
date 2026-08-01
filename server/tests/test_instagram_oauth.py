import importlib
import os
import pathlib
import sys
import types
import unittest
import urllib.parse
from unittest import mock


MODULE_NAME = "server.telegram_api"
EXPECTED_SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_insights",
]
FORBIDDEN_SCOPES = [
    "instagram_business_content_publish",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
]


def make_telethon_modules():
    telethon = types.ModuleType("telethon")
    telethon.__path__ = []
    telethon.TelegramClient = type("TelegramClient", (), {})

    telethon_tl = types.ModuleType("telethon.tl")
    telethon_tl.__path__ = []
    telethon_custom = types.ModuleType("telethon.tl.custom")
    telethon_custom.__path__ = []
    telethon_message = types.ModuleType(
        "telethon.tl.custom.message"
    )
    telethon_message.Message = type("Message", (), {})

    telethon.tl = telethon_tl
    telethon_tl.custom = telethon_custom
    telethon_custom.message = telethon_message

    return {
        "telethon": telethon,
        "telethon.tl": telethon_tl,
        "telethon.tl.custom": telethon_custom,
        "telethon.tl.custom.message": telethon_message,
    }


class InstagramOAuthTestCase(unittest.TestCase):
    def load_telegram_api(self):
        sys.modules.pop(MODULE_NAME, None)

        environment = {
            "INSTAGRAM_APP_ID": "test-instagram-app-id",
            "INSTAGRAM_APP_SECRET": "test-instagram-app-secret",
            "INSTAGRAM_REDIRECT_URI": (
                "https://example.test/instagram/callback"
            ),
        }

        with (
            mock.patch.dict(os.environ, environment),
            mock.patch.dict(sys.modules, make_telethon_modules()),
            mock.patch.object(pathlib.Path, "mkdir"),
        ):
            module = importlib.import_module(MODULE_NAME)

        sys.modules.pop(MODULE_NAME, None)
        return module

    def test_connect_url_contains_only_expected_instagram_scopes(self):
        telegram_api = self.load_telegram_api()

        response = telegram_api.app.test_client().get(
            "/instagram/connect"
        )
        authorization_url = response.get_json()[
            "authorization_url"
        ]
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(authorization_url).query
        )
        scopes = query["scope"][0].split(",")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(telegram_api.INSTAGRAM_SCOPES, EXPECTED_SCOPES)
        self.assertEqual(scopes, EXPECTED_SCOPES)

        for scope in EXPECTED_SCOPES:
            with self.subTest(required_scope=scope):
                self.assertIn(scope, authorization_url)

        for scope in FORBIDDEN_SCOPES:
            with self.subTest(forbidden_scope=scope):
                self.assertNotIn(scope, authorization_url)


if __name__ == "__main__":
    unittest.main()
