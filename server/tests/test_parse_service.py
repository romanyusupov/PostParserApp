import unittest
from unittest import mock

from server.postparser_web.parse_service import (
    ParseConfigurationError,
    ParseGroupNotFoundError,
    ParseService,
    ParserExecutionError,
    UnsupportedNetworkError,
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


class FakeSettingsStore:
    def __init__(self, groups):
        self.groups = groups
        self.load_calls = 0

    def load(self):
        self.load_calls += 1
        return {
            "revision": 1,
            "settings": {
                "groups": self.groups,
                "savedAt": "",
            },
        }


class FakeParser:
    def __init__(self, posts=None, error=None):
        self.posts = list(posts or [])
        self.error = error
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
