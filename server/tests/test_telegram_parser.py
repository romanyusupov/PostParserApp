import datetime
import unittest
from types import SimpleNamespace
from unittest import mock

from server.postparser_web.telegram_parser import (
    TelegramConfigurationError,
    TelegramParser,
    TelegramParserError,
    normalize_telegram_channel,
    normalize_telegram_post,
)


API_HASH = "test-api-hash-that-must-stay-secret"
SESSION_STRING = "test-session-that-must-stay-secret"


def make_message(
    message_id=1,
    timestamp="2026-07-15T12:00:00+00:00",
    text="Тестовая публикация",
    **values,
):
    message = SimpleNamespace(
        id=message_id,
        date=datetime.datetime.fromisoformat(timestamp),
        message=text,
        raw_text=text,
        photo=None,
        video=None,
        views=None,
        forwards=None,
        likes=None,
        comments=None,
        reactions=None,
        replies=None,
    )
    for name, value in values.items():
        setattr(message, name, value)
    return message


class FakeClient:
    def __init__(self, messages=(), error=None):
        self.messages = list(messages)
        self.error = error
        self.connected = False
        self.disconnected = False
        self.entity_requests = []
        self.media_requests = []

    async def connect(self):
        self.connected = True
        if self.error:
            raise self.error

    async def is_user_authorized(self):
        return True

    async def get_entity(self, channel):
        self.entity_requests.append(channel)
        return SimpleNamespace(username=channel)

    async def iter_messages(self, entity):
        for message in self.messages:
            yield message

    async def get_media_url(self, message, media_type):
        self.media_requests.append((message.id, media_type))
        return f"https://media.test/{message.id}/{media_type}"

    async def disconnect(self):
        self.disconnected = True


class FakeClientFactory:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def __call__(self, api_id, api_hash, session_string):
        self.calls.append((api_id, api_hash, session_string))
        return self.client


def make_parser(messages=(), error=None):
    client = FakeClient(messages, error)
    factory = FakeClientFactory(client)
    parser = TelegramParser(
        12345,
        API_HASH,
        SESSION_STRING,
        client_factory=factory,
    )
    return parser, client, factory


class TelegramParserConfigurationTestCase(unittest.TestCase):
    def test_empty_api_id_is_rejected(self):
        for api_id in (None, "", "   ", 0):
            with self.subTest(api_id=api_id):
                with self.assertRaises(TelegramConfigurationError):
                    TelegramParser(api_id, API_HASH)

    def test_empty_api_hash_is_rejected(self):
        for api_hash in (None, "", "   "):
            with self.subTest(api_hash=api_hash):
                with self.assertRaises(TelegramConfigurationError):
                    TelegramParser(12345, api_hash)


class TelegramChannelTestCase(unittest.TestCase):
    def test_channel_username_is_accepted(self):
        self.assertEqual(
            normalize_telegram_channel("channel_name"),
            "channel_name",
        )

    def test_t_me_link_is_converted_to_username(self):
        for value in (
            "https://t.me/channel_name",
            "http://t.me/channel_name/",
            "t.me/channel_name",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_telegram_channel(value),
                    "channel_name",
                )


class TelegramPostNormalizationTestCase(unittest.TestCase):
    def test_text_is_preserved(self):
        text = "Полный текст\n\n" + "Продолжение " * 100

        result = normalize_telegram_post(
            make_message(text=text),
            "channel_name",
        )

        self.assertEqual(result["text"], text)

    def test_first_nonempty_paragraph_is_selected(self):
        result = normalize_telegram_post(
            make_message(
                text="\n Первый абзац\nпродолжение\n\nВторой абзац"
            ),
            "channel_name",
        )

        self.assertEqual(
            result["first_paragraph"],
            "Первый абзац\nпродолжение",
        )

    def test_photo_is_detected(self):
        result = normalize_telegram_post(
            make_message(photo=object()),
            "channel_name",
            image_url="https://media.test/photo",
        )

        self.assertEqual(result["post_type"], "Фото")
        self.assertEqual(result["image_url"], "https://media.test/photo")

    def test_video_has_priority(self):
        result = normalize_telegram_post(
            make_message(photo=object(), video=object()),
            "channel_name",
            video_url="https://media.test/video",
        )

        self.assertEqual(result["post_type"], "Видео")
        self.assertEqual(result["video_url"], "https://media.test/video")

    def test_views_are_read(self):
        result = normalize_telegram_post(
            make_message(views=321),
            "channel_name",
        )

        self.assertEqual(result["views"], 321)

    def test_forwards_are_read(self):
        result = normalize_telegram_post(
            make_message(forwards=17),
            "channel_name",
        )

        self.assertEqual(result["forwards"], 17)

    def test_missing_metrics_are_zero(self):
        result = normalize_telegram_post(
            make_message(),
            "channel_name",
        )

        self.assertEqual(
            {
                name: result[name]
                for name in ("views", "likes", "comments", "forwards")
            },
            {"views": 0, "likes": 0, "comments": 0, "forwards": 0},
        )


class TelegramFetchPostsTestCase(unittest.TestCase):
    def test_username_is_passed_to_client(self):
        parser, client, _ = make_parser()

        parser.fetch_posts("channel_name", "2026-07-01", "2026-07-31")

        self.assertEqual(client.entity_requests, ["channel_name"])

    def test_t_me_link_is_normalized_before_client_call(self):
        parser, client, _ = make_parser()

        parser.fetch_posts(
            "https://t.me/channel_name",
            "2026-07-01",
            "2026-07-31",
        )

        self.assertEqual(client.entity_requests, ["channel_name"])

    def test_dates_are_filtered_inclusively(self):
        parser, _, _ = make_parser(
            (
                make_message(1, "2026-06-30T23:59:59+00:00"),
                make_message(2, "2026-07-01T00:00:00+00:00"),
                make_message(3, "2026-07-31T23:59:59+00:00"),
                make_message(4, "2026-08-01T00:00:00+00:00"),
            )
        )

        result = parser.fetch_posts(
            "channel_name",
            "2026-07-01",
            "2026-07-31",
        )

        self.assertEqual(
            [post["external_id"] for post in result],
            ["3", "2"],
        )

    def test_reverse_date_range_is_rejected(self):
        parser, client, _ = make_parser()

        with self.assertRaisesRegex(TelegramParserError, "не может быть позже"):
            parser.fetch_posts(
                "channel_name",
                "2026-08-01",
                "2026-07-31",
            )

        self.assertFalse(client.connected)

    def test_posts_are_sorted_newest_first(self):
        parser, _, _ = make_parser(
            (
                make_message(1, "2026-07-01T12:00:00+00:00"),
                make_message(3, "2026-07-03T12:00:00+00:00"),
                make_message(2, "2026-07-02T12:00:00+00:00"),
            )
        )

        result = parser.fetch_posts(
            "channel_name",
            "2026-07-01",
            "2026-07-31",
        )

        self.assertEqual(
            [post["external_id"] for post in result],
            ["3", "2", "1"],
        )

    def test_duplicate_message_ids_are_removed(self):
        parser, _, _ = make_parser(
            (make_message(1), make_message(1), make_message(2))
        )

        result = parser.fetch_posts(
            "channel_name",
            "2026-07-01",
            "2026-07-31",
        )

        self.assertEqual(
            [post["external_id"] for post in result],
            ["1", "2"],
        )

    def test_media_urls_are_resolved_without_downloading_files(self):
        parser, client, _ = make_parser(
            (
                make_message(1, photo=object()),
                make_message(2, video=object()),
            )
        )

        result = parser.fetch_posts(
            "channel_name",
            "2026-07-01",
            "2026-07-31",
        )

        posts = {post["external_id"]: post for post in result}
        self.assertEqual(
            posts["1"]["image_url"],
            "https://media.test/1/photo",
        )
        self.assertEqual(
            posts["2"]["video_url"],
            "https://media.test/2/video",
        )
        self.assertEqual(client.media_requests, [(1, "photo"), (2, "video")])

    def test_client_error_is_converted_to_parser_error(self):
        parser, client, _ = make_parser(error=RuntimeError("client failed"))

        with self.assertRaises(TelegramParserError) as context:
            parser.fetch_posts(
                "channel_name",
                "2026-07-01",
                "2026-07-31",
            )

        self.assertIn("Telegram", str(context.exception))
        self.assertTrue(client.disconnected)

    def test_secrets_are_not_exposed_in_exception(self):
        parser, _, _ = make_parser(
            error=RuntimeError(f"{API_HASH} {SESSION_STRING}")
        )

        with self.assertRaises(TelegramParserError) as context:
            parser.fetch_posts(
                "channel_name",
                "2026-07-01",
                "2026-07-31",
            )

        self.assertNotIn(API_HASH, str(context.exception))
        self.assertNotIn(SESSION_STRING, str(context.exception))

    def test_no_real_telegram_client_is_created(self):
        parser, _, factory = make_parser((make_message(1),))

        with mock.patch(
            "server.postparser_web.telegram_parser._default_client_factory"
        ) as real_factory:
            result = parser.fetch_posts(
                "channel_name",
                "2026-07-01",
                "2026-07-31",
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(len(factory.calls), 1)
        real_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
