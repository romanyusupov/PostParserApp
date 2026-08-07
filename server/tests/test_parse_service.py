import os
import pathlib
import unittest
from unittest import mock

from server.postparser_web.parse_service import (
    ParseConfigurationError,
    ParseGroupNotFoundError,
    ParseService,
    ParserExecutionError,
    UnsupportedNetworkError,
    _create_instagram_parser,
    _create_telegram_parser,
)
from server.postparser_web.vk_parser import VkParserError


def make_group(
    group_id="group_1",
    name="Тестовая группа",
    network="vk",
    url="https://example.test/group",
    date_start="2026-07-01",
    date_end="2026-07-31",
    advertising_types=None,
):
    return {
        "id": group_id,
        "name": name,
        "network": network,
        "url": url,
        "dateStart": date_start,
        "dateEnd": date_end,
        "advertisingTypes": list(advertising_types or []),
    }


class FakeSettingsStore:
    def __init__(self, groups):
        self.groups = groups
        self.load_calls = 0

    def load(self, owner_id="admin"):
        self.load_calls += 1
        return {
            "revision": 1,
            "settings": {
                "groups": self.groups,
                "savedAt": "",
            },
        }


class FakeParser:
    def __init__(self, posts=None, error=None, warning=""):
        self.posts = list(posts or [])
        self.error = error
        self.warning = warning
        self.fetch_calls = []

    def fetch_posts(self, group_url, date_start, date_end):
        self.fetch_calls.append((group_url, date_start, date_end))
        if self.error is not None:
            raise self.error
        return self.posts


class RecordingFactory:
    def __init__(self, parser):
        self.parser = parser
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.parser


def make_service(group, selected_network=None, parser=None):
    selected_network = selected_network or group["network"]
    parser = parser or FakeParser(
        posts=[{"source": selected_network, "external_id": "post_1"}]
    )
    factories = {
        "vk": RecordingFactory(FakeParser()),
        "instagram": RecordingFactory(FakeParser()),
        "telegram": RecordingFactory(FakeParser()),
    }
    factories[selected_network] = RecordingFactory(parser)
    service = ParseService(
        FakeSettingsStore([group]),
        parser_factories=factories,
        allowed_instagram_account=(
            group["url"] if group["network"] == "instagram" else ""
        ),
    )
    return service, parser, factories


class ParseServiceSelectionTestCase(unittest.TestCase):
    def test_vk_group_calls_vk_parser(self):
        group = make_group(network="vk", url="https://vk.com/test")
        service, parser, factories = make_service(group)

        service.parse_group("group_1")

        self.assertEqual(factories["vk"].calls, 1)
        self.assertEqual(len(parser.fetch_calls), 1)

    def test_instagram_group_calls_instagram_parser(self):
        group = make_group(network="instagram", url="instagram_account")
        service, parser, factories = make_service(group)

        service.parse_group("group_1")

        self.assertEqual(factories["instagram"].calls, 1)
        self.assertEqual(len(parser.fetch_calls), 1)

    def test_instagram_rejects_arbitrary_account_server_side(self):
        group = make_group(network="instagram", url="arbitrary-account")
        parser = FakeParser()
        service = ParseService(
            FakeSettingsStore([group]),
            parser_factories={"instagram": RecordingFactory(parser)},
            allowed_instagram_account="connected-torsunov-account",
        )

        with self.assertRaisesRegex(
            ParseConfigurationError,
            "только подключённый Business аккаунт",
        ):
            service.parse_group("group_1")

        self.assertEqual(parser.fetch_calls, [])

    def test_telegram_group_calls_telegram_parser(self):
        group = make_group(network="telegram", url="https://t.me/test")
        service, parser, factories = make_service(group)

        service.parse_group("group_1")

        self.assertEqual(factories["telegram"].calls, 1)
        self.assertEqual(len(parser.fetch_calls), 1)

    def test_dates_are_passed_to_parser(self):
        group = make_group(
            date_start="2026-06-01",
            date_end="2026-06-30",
        )
        service, parser, _ = make_service(group)

        service.parse_group("group_1")

        self.assertEqual(
            parser.fetch_calls[0][1:],
            ("2026-06-01", "2026-06-30"),
        )

    def test_url_is_passed_to_parser(self):
        group = make_group(url="https://vk.com/saved_group")
        service, parser, _ = make_service(group)

        service.parse_group("group_1")

        self.assertEqual(
            parser.fetch_calls[0][0],
            "https://vk.com/saved_group",
        )

    def test_only_selected_network_factory_is_called(self):
        group = make_group(network="telegram")
        service, _, factories = make_service(group)

        service.parse_group("group_1")

        self.assertEqual(
            {network: factory.calls for network, factory in factories.items()},
            {"vk": 0, "instagram": 0, "telegram": 1},
        )


class InstagramParserFactoryTestCase(unittest.TestCase):
    def test_environment_access_token_is_accepted(self):
        with (
            mock.patch.dict(
                os.environ,
                {"POSTPARSER_INSTAGRAM_ACCESS_TOKEN": "environment-token"},
                clear=True,
            ),
            mock.patch(
                "server.postparser_web.parse_service.InstagramParser"
            ) as parser_class,
        ):
            parser = _create_instagram_parser()

        self.assertIs(parser, parser_class.return_value)
        parser_class.assert_called_once_with("environment-token")

    def test_oauth_token_storage_is_accepted(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch(
                "server.postparser_web.parse_service."
                "load_instagram_access_token",
                return_value="stored-oauth-token",
            ),
            mock.patch(
                "server.postparser_web.parse_service.InstagramParser"
            ) as parser_class,
        ):
            parser = _create_instagram_parser()

        self.assertIs(parser, parser_class.return_value)
        parser_class.assert_called_once_with("stored-oauth-token")


class TelegramParserFactoryTestCase(unittest.TestCase):
    def test_file_session_configuration_is_accepted(self):
        environment = {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "secret-hash",
            "TELEGRAM_SESSION_NAME": "C:\\private\\telegram.session",
        }

        with (
            mock.patch.dict("os.environ", environment, clear=True),
            mock.patch(
                "server.postparser_web.parse_service.TelegramParser"
            ) as parser_class,
        ):
            parser = _create_telegram_parser()

        self.assertIs(parser, parser_class.return_value)
        parser_class.assert_called_once_with(
            "12345",
            "secret-hash",
            session_string=None,
            session_name="C:\\private\\telegram.session",
            media_directory=mock.ANY,
            public_base_url="",
        )

    def test_session_string_has_priority_over_file_session(self):
        environment = {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "secret-hash",
            "TELEGRAM_SESSION_STRING": "secret-session",
            "TELEGRAM_SESSION_NAME": "C:\\private\\telegram.session",
        }

        with (
            mock.patch.dict("os.environ", environment, clear=True),
            mock.patch(
                "server.postparser_web.parse_service.TelegramParser"
            ) as parser_class,
        ):
            _create_telegram_parser()

        parser_class.assert_called_once_with(
            "12345",
            "secret-hash",
            session_string="secret-session",
            session_name=None,
            media_directory=mock.ANY,
            public_base_url="",
        )

    def test_telegram_media_configuration_is_passed_from_environment(self):
        environment = {
            "POSTPARSER_DATA_DIR": "C:\\private\\data",
            "POSTPARSER_PUBLIC_BASE_URL": "https://parser.example.test/",
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "secret-hash",
            "TELEGRAM_SESSION_NAME": "C:\\private\\telegram.session",
        }

        with (
            mock.patch.dict("os.environ", environment, clear=True),
            mock.patch(
                "server.postparser_web.parse_service.TelegramParser"
            ) as parser_class,
        ):
            _create_telegram_parser()

        self.assertEqual(
            parser_class.call_args.kwargs["media_directory"],
            mock.ANY,
        )
        self.assertEqual(
            parser_class.call_args.kwargs["media_directory"],
            pathlib.Path(environment["POSTPARSER_DATA_DIR"])
            / "media"
            / "telegram",
        )
        self.assertEqual(
            parser_class.call_args.kwargs["public_base_url"],
            "https://parser.example.test/",
        )

    def test_missing_sessions_are_rejected(self):
        environment = {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "secret-hash",
        }

        with mock.patch.dict("os.environ", environment, clear=True):
            with self.assertRaisesRegex(
                ParseConfigurationError,
                "Telegram-подключение не настроено",
            ):
                _create_telegram_parser()


class ParseServiceErrorTestCase(unittest.TestCase):
    def test_unknown_group_raises_clear_error(self):
        service = ParseService(
            FakeSettingsStore([]),
            parser_factories={},
        )

        with self.assertRaisesRegex(
            ParseGroupNotFoundError,
            "missing_group",
        ):
            service.parse_group("missing_group")

    def test_unknown_network_raises_clear_error(self):
        group = make_group(network="unknown-network")
        service = ParseService(
            FakeSettingsStore([group]),
            parser_factories={},
        )

        with self.assertRaisesRegex(
            UnsupportedNetworkError,
            "unknown-network",
        ):
            service.parse_group("group_1")

    def test_missing_factory_raises_configuration_error(self):
        group = make_group(network="vk")
        service = ParseService(
            FakeSettingsStore([group]),
            parser_factories={"vk": None},
        )

        with self.assertRaisesRegex(ParseConfigurationError, "Фабрика"):
            service.parse_group("group_1")

    def test_parser_error_is_exposed_as_service_error(self):
        source_error = VkParserError("ожидаемая ошибка VK")
        parser = FakeParser(error=source_error)
        group = make_group(network="vk")
        service, _, _ = make_service(group, parser=parser)

        with self.assertRaises(ParserExecutionError) as context:
            service.parse_group("group_1")

        self.assertIn("ожидаемая ошибка VK", str(context.exception))
        self.assertIs(context.exception.__cause__, source_error)


class ParseServiceResultTestCase(unittest.TestCase):
    def test_advertising_type_is_added_for_every_network(self):
        advertising_types = [
            {
                "type": "Партнёрская публикация",
                "postWords": ["промокод торсунов"],
                "videoWords": [],
            }
        ]

        for network in ("vk", "telegram", "instagram"):
            with self.subTest(network=network):
                parser = FakeParser(
                    posts=[
                        {
                            "source": network,
                            "external_id": "post_1",
                            "text": "Используйте промокод Торсунов сегодня",
                        }
                    ]
                )
                service, _, _ = make_service(
                    make_group(
                        network=network,
                        advertising_types=advertising_types,
                    ),
                    parser=parser,
                )

                result = service.parse_group("group_1")

                self.assertEqual(
                    result["posts"][0]["advertising_type"],
                    "Партнёрская публикация",
                )

    def test_post_without_advertising_match_gets_empty_type(self):
        parser = FakeParser(
            posts=[
                {
                    "source": "vk",
                    "external_id": "post_1",
                    "text": "Обычная публикация",
                }
            ]
        )
        group = make_group(
            advertising_types=[
                {
                    "type": "Реклама",
                    "postWords": ["промокод"],
                    "videoWords": [],
                }
            ]
        )
        service, _, _ = make_service(group, parser=parser)

        result = service.parse_group("group_1")

        self.assertEqual(result["posts"][0]["advertising_type"], "")

    def test_video_words_match_only_video_description(self):
        parser = FakeParser(
            posts=[
                {
                    "source": "vk",
                    "external_id": "post_1",
                    "text": "Обычная публикация",
                    "video_description": "Отправьте слово ДЕТАЛЬ в сообщении",
                }
            ]
        )
        service, _, _ = make_service(
            make_group(
                advertising_types=[
                    {
                        "type": "Деталь.Уважение к М",
                        "postWords": [],
                        "videoWords": ["деталь"],
                    }
                ]
            ),
            parser=parser,
        )

        result = service.parse_group("group_1")

        self.assertEqual(
            result["posts"][0]["advertising_type"],
            "Деталь.Уважение к М",
        )

    def test_video_words_are_not_searched_in_post_text(self):
        parser = FakeParser(
            posts=[
                {
                    "source": "vk",
                    "external_id": "post_1",
                    "text": "Отправьте слово ДЕТАЛЬ в сообщении",
                    "video_description": "Обычное описание видео",
                }
            ]
        )
        service, _, _ = make_service(
            make_group(
                advertising_types=[
                    {
                        "type": "Деталь.Уважение к М",
                        "postWords": [],
                        "videoWords": ["деталь"],
                    }
                ]
            ),
            parser=parser,
        )

        result = service.parse_group("group_1")

        self.assertEqual(result["posts"][0]["advertising_type"], "")

    def test_post_words_are_not_searched_in_video_description(self):
        parser = FakeParser(
            posts=[
                {
                    "source": "vk",
                    "external_id": "post_1",
                    "text": "Обычная публикация",
                    "video_description": "В описании есть промокод",
                }
            ]
        )
        service, _, _ = make_service(
            make_group(
                advertising_types=[
                    {
                        "type": "Реклама",
                        "postWords": ["промокод"],
                        "videoWords": [],
                    }
                ]
            ),
            parser=parser,
        )

        result = service.parse_group("group_1")

        self.assertEqual(result["posts"][0]["advertising_type"], "")

    def test_first_matching_advertising_rule_wins(self):
        parser = FakeParser(
            posts=[
                {
                    "source": "vk",
                    "external_id": "post_1",
                    "text": "Используйте промокод",
                    "video_description": "Отправьте слово деталь",
                }
            ]
        )
        service, _, _ = make_service(
            make_group(
                advertising_types=[
                    {
                        "type": "Первое правило",
                        "postWords": ["промокод"],
                        "videoWords": [],
                    },
                    {
                        "type": "Второе правило",
                        "postWords": [],
                        "videoWords": ["деталь"],
                    },
                ]
            ),
            parser=parser,
        )

        result = service.parse_group("group_1")

        self.assertEqual(
            result["posts"][0]["advertising_type"],
            "Первое правило",
        )

    def test_empty_video_description_is_safe(self):
        parser = FakeParser(
            posts=[
                {
                    "source": "vk",
                    "external_id": "post_1",
                    "text": "Обычная публикация",
                    "video_description": "",
                }
            ]
        )
        service, _, _ = make_service(
            make_group(
                advertising_types=[
                    {
                        "type": "Реклама",
                        "postWords": [],
                        "videoWords": ["деталь"],
                    }
                ]
            ),
            parser=parser,
        )

        result = service.parse_group("group_1")

        self.assertEqual(result["posts"][0]["advertising_type"], "")

    def test_safe_parser_warning_is_returned(self):
        warning = (
            "Instagram Insights unavailable: missing "
            "instagram_business_manage_insights"
        )
        parser = FakeParser(
            posts=[{"source": "instagram", "external_id": "media_1"}],
            warning=warning,
        )
        service, _, _ = make_service(
            make_group(network="instagram"),
            parser=parser,
        )

        result = service.parse_group("group_1")

        self.assertEqual(result["warning"], warning)

    def test_result_has_unified_format(self):
        posts = [
            {"source": "vk", "external_id": "post_1"},
            {"source": "vk", "external_id": "post_2"},
        ]
        parser = FakeParser(posts=posts)
        group = make_group(
            group_id="saved_group",
            name="Сохранённая группа",
            network="vk",
        )
        service, _, _ = make_service(group, parser=parser)

        result = service.parse_group("saved_group")

        self.assertEqual(
            result,
            {
                "group_id": "saved_group",
                "group_name": "Сохранённая группа",
                "network": "vk",
                "count": 2,
                "posts": posts,
            },
        )

    def test_no_real_api_parser_is_created(self):
        group = make_group(network="vk")
        service, _, _ = make_service(group)

        with (
            mock.patch(
                "server.postparser_web.parse_service._create_vk_parser"
            ) as real_vk,
            mock.patch(
                "server.postparser_web.parse_service._create_instagram_parser"
            ) as real_instagram,
            mock.patch(
                "server.postparser_web.parse_service._create_telegram_parser"
            ) as real_telegram,
        ):
            service.parse_group("group_1")

        real_vk.assert_not_called()
        real_instagram.assert_not_called()
        real_telegram.assert_not_called()


if __name__ == "__main__":
    unittest.main()
