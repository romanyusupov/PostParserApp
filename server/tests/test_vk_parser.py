import datetime
import json
import unittest
import urllib.parse

from server.postparser_web.vk_parser import (
    VkApiError,
    VkConfigurationError,
    VkParser,
    VkParserError,
    normalize_vk_post,
)


OWNER_ID = -123456
TOKEN = "test-token-that-must-stay-secret"


def utc_timestamp(year, month, day, hour=0, minute=0, second=0):
    return int(
        datetime.datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=datetime.timezone.utc,
        ).timestamp()
    )


def make_post(post_id, timestamp=None, **values):
    post = {
        "owner_id": OWNER_ID,
        "id": post_id,
        "date": timestamp or utc_timestamp(2026, 7, 15, 12),
        "text": f"Публикация {post_id}",
        "attachments": [],
    }
    post.update(values)
    return post


def wall_response(items):
    return {"response": {"count": len(items), "items": items}}


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, timeout):
        parsed = urllib.parse.urlparse(url)
        method = parsed.path.rsplit("/", 1)[-1]
        parameters = {
            key: values[-1]
            for key, values in urllib.parse.parse_qs(
                parsed.query,
                keep_blank_values=True,
            ).items()
        }
        self.calls.append(
            {
                "method": method,
                "parameters": parameters,
                "timeout": timeout,
            }
        )

        if not self.responses:
            raise AssertionError("Не подготовлен ответ транспорта")

        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response

        if isinstance(response, (bytes, str)):
            return response

        return json.dumps(response, ensure_ascii=False).encode("utf-8")


class ObjectTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, url, timeout):
        self.calls.append((url, timeout))
        return json.dumps(self.response).encode("utf-8")


class VkParserConfigurationTestCase(unittest.TestCase):
    def test_empty_token_is_rejected(self):
        for token in (None, "", "   "):
            with self.subTest(token=token):
                with self.assertRaises(VkConfigurationError):
                    VkParser(token)

    def test_transport_object_with_request_method_is_supported(self):
        transport = ObjectTransport(wall_response([]))
        parser = VkParser(TOKEN, transport=transport)

        result = parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        self.assertEqual(result, [])
        self.assertEqual(len(transport.calls), 1)


class VkOwnerResolutionTestCase(unittest.TestCase):
    def test_negative_numeric_owner_id_does_not_call_resolve(self):
        transport = FakeTransport()
        parser = VkParser(TOKEN, transport=transport)

        self.assertEqual(parser.resolve_owner_id("-123456"), OWNER_ID)
        self.assertEqual(transport.calls, [])

    def test_short_name_is_resolved_through_vk_api(self):
        transport = FakeTransport(
            {"response": {"type": "group", "object_id": 123456}}
        )
        parser = VkParser(TOKEN, transport=transport)

        owner_id = parser.resolve_owner_id("proactivum")

        self.assertEqual(owner_id, OWNER_ID)
        self.assertEqual(
            transport.calls[0]["method"],
            "utils.resolveScreenName",
        )
        self.assertEqual(
            transport.calls[0]["parameters"]["screen_name"],
            "proactivum",
        )

    def test_supported_vk_urls_are_resolved(self):
        variants = (
            "https://vk.com/proactivum",
            "https://vk.ru/proactivum",
            "vk.com/proactivum",
            "vk.ru/proactivum",
        )

        for value in variants:
            with self.subTest(value=value):
                transport = FakeTransport(
                    {
                        "response": {
                            "type": "page",
                            "object_id": 123456,
                        }
                    }
                )
                parser = VkParser(TOKEN, transport=transport)

                self.assertEqual(parser.resolve_owner_id(value), OWNER_ID)
                self.assertEqual(
                    transport.calls[0]["parameters"]["screen_name"],
                    "proactivum",
                )

    def test_unknown_screen_name_is_rejected(self):
        parser = VkParser(
            TOKEN,
            transport=FakeTransport({"response": []}),
        )

        with self.assertRaisesRegex(
            VkParserError,
            "Не удалось определить сообщество",
        ):
            parser.resolve_owner_id("unknown-community")

    def test_non_vk_url_is_rejected(self):
        parser = VkParser(TOKEN, transport=FakeTransport())

        with self.assertRaisesRegex(VkParserError, "неподдерживаемый"):
            parser.resolve_owner_id("https://example.com/community")


class VkPaginationTestCase(unittest.TestCase):
    def test_date_range_is_inclusive_in_utc(self):
        posts = [
            make_post(1, utc_timestamp(2026, 7, 1)),
            make_post(2, utc_timestamp(2026, 7, 2, 23, 59, 59)),
            make_post(3, utc_timestamp(2026, 6, 30, 23, 59, 59)),
            make_post(4, utc_timestamp(2026, 7, 3)),
        ]
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(wall_response(posts)),
        )

        result = parser.fetch_posts("-123456", "2026-07-01", "2026-07-02")

        self.assertEqual(
            [post["external_id"] for post in result],
            [f"{OWNER_ID}_2", f"{OWNER_ID}_1"],
        )

    def test_datetime_date_arguments_are_accepted(self):
        post = make_post(1, utc_timestamp(2026, 7, 1, 12))
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(wall_response([post])),
        )

        result = parser.fetch_posts(
            "-123456",
            datetime.date(2026, 7, 1),
            datetime.date(2026, 7, 1),
        )

        self.assertEqual(len(result), 1)

    def test_reverse_date_range_is_rejected(self):
        parser = VkParser(TOKEN, transport=FakeTransport())

        with self.assertRaisesRegex(VkParserError, "не может быть позже"):
            parser.fetch_posts("-123456", "2026-07-02", "2026-07-01")

    def test_two_pages_are_loaded_without_skipping_offset(self):
        first_page = [make_post(post_id) for post_id in range(1, 101)]
        second_page = [make_post(101)]
        transport = FakeTransport(
            wall_response(first_page),
            wall_response(second_page),
        )
        parser = VkParser(TOKEN, transport=transport)

        result = parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        self.assertEqual(len(result), 101)
        self.assertEqual(
            [call["parameters"]["offset"] for call in transport.calls],
            ["0", "100"],
        )

    def test_offset_is_incremented_only_once_per_page(self):
        first_page = [make_post(post_id) for post_id in range(1, 101)]
        transport = FakeTransport(
            wall_response(first_page),
            wall_response([]),
        )
        parser = VkParser(TOKEN, transport=transport)

        parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        wall_offsets = [
            call["parameters"]["offset"]
            for call in transport.calls
            if call["method"] == "wall.get"
        ]
        self.assertEqual(wall_offsets, ["0", "100"])

    def test_pagination_log_contains_only_safe_page_metadata(self):
        page = [
            make_post(1, utc_timestamp(2026, 7, 20, 12)),
            make_post(2, utc_timestamp(2026, 7, 10, 12)),
        ]
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(wall_response(page)),
        )

        with self.assertLogs(
            "server.postparser_web.vk_parser",
            level="INFO",
        ) as captured:
            parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        log_text = "\n".join(captured.output)
        self.assertIn("offset=0", log_text)
        self.assertIn("items=2", log_text)
        self.assertIn("response_count=2", log_text)
        self.assertIn("oldest_date=2026-07-10", log_text)
        self.assertNotIn(TOKEN, log_text)

    def test_loading_stops_after_posts_older_than_start_date(self):
        old_page = [
            make_post(post_id, utc_timestamp(2026, 6, 30, 12))
            for post_id in range(1, 101)
        ]
        transport = FakeTransport(
            wall_response(old_page),
            wall_response([make_post(101)]),
        )
        parser = VkParser(TOKEN, transport=transport)

        result = parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        self.assertEqual(result, [])
        self.assertEqual(len(transport.calls), 1)

    def test_repeated_pinned_post_is_not_duplicated(self):
        pinned = make_post(999, is_pinned=1)
        first_page = [pinned] + [
            make_post(post_id) for post_id in range(1, 100)
        ]
        second_page = [pinned, make_post(100)]
        transport = FakeTransport(
            wall_response(first_page),
            wall_response(second_page),
        )
        parser = VkParser(TOKEN, transport=transport)

        result = parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")
        identifiers = [post["external_id"] for post in result]

        self.assertEqual(identifiers.count(f"{OWNER_ID}_999"), 1)
        self.assertEqual(len(result), 101)

    def test_duplicate_posts_are_removed(self):
        duplicate = make_post(1)
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(
                wall_response([duplicate, duplicate.copy()])
            ),
        )

        result = parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        self.assertEqual(len(result), 1)

    def test_result_is_sorted_from_newest_to_oldest(self):
        posts = [
            make_post(1, utc_timestamp(2026, 7, 10)),
            make_post(2, utc_timestamp(2026, 7, 20)),
            make_post(3, utc_timestamp(2026, 7, 15)),
        ]
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(wall_response(posts)),
        )

        result = parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        self.assertEqual(
            [post["external_id"] for post in result],
            [f"{OWNER_ID}_2", f"{OWNER_ID}_3", f"{OWNER_ID}_1"],
        )


class VkPostNormalizationTestCase(unittest.TestCase):
    def test_full_text_is_preserved(self):
        full_text = "Начало\n\n" + "Очень длинный текст " * 1000

        result = normalize_vk_post(make_post(1, text=full_text))

        self.assertEqual(result["text"], full_text)

    def test_first_nonempty_paragraph_is_selected(self):
        post = make_post(
            1,
            text="\n\n  Первый абзац  \nпродолжение\n\nВторой абзац",
        )

        result = normalize_vk_post(post)

        self.assertEqual(
            result["first_paragraph"],
            "Первый абзац\nпродолжение",
        )

    def test_single_photo_post_type(self):
        post = make_post(1, attachments=[self.photo_attachment("one")])

        self.assertEqual(
            normalize_vk_post(post)["post_type"],
            "Текст с картинкой",
        )

    def test_multiple_photos_post_type(self):
        post = make_post(
            1,
            attachments=[
                self.photo_attachment("one"),
                self.photo_attachment("two"),
            ],
        )

        self.assertEqual(
            normalize_vk_post(post)["post_type"],
            "Карусель и текст",
        )

    def test_video_has_priority_over_photos(self):
        post = make_post(
            1,
            attachments=[
                self.photo_attachment("one"),
                self.photo_attachment("two"),
                self.video_attachment("Описание"),
            ],
        )

        self.assertEqual(
            normalize_vk_post(post)["post_type"],
            "Видео и текст",
        )

    def test_text_without_attachments_post_type(self):
        self.assertEqual(
            normalize_vk_post(make_post(1))["post_type"],
            "Текст",
        )

    def test_largest_photo_is_selected(self):
        post = make_post(
            1,
            attachments=[
                {
                    "type": "photo",
                    "photo": {
                        "sizes": [
                            {
                                "url": "https://img/small.jpg",
                                "width": 100,
                                "height": 100,
                            },
                            {
                                "url": "https://img/large.jpg",
                                "width": 1200,
                                "height": 800,
                            },
                            {
                                "url": "https://img/medium.jpg",
                                "width": 600,
                                "height": 400,
                            },
                        ]
                    },
                }
            ],
        )

        self.assertEqual(
            normalize_vk_post(post)["image_url"],
            "https://img/large.jpg",
        )

    def test_first_video_description_is_extracted(self):
        post = make_post(
            1,
            attachments=[
                self.video_attachment("Первое описание"),
                self.video_attachment("Второе описание"),
            ],
        )

        self.assertEqual(
            normalize_vk_post(post)["video_description"],
            "Первое описание",
        )

    def test_metrics_are_extracted(self):
        post = make_post(
            1,
            views={"count": 150},
            likes={"count": "25"},
            comments={"count": 7},
        )

        result = normalize_vk_post(post)

        self.assertEqual(result["views"], 150)
        self.assertEqual(result["likes"], 25)
        self.assertEqual(result["comments"], 7)

    def test_missing_metrics_are_zero(self):
        result = normalize_vk_post(make_post(1))

        self.assertEqual(result["views"], 0)
        self.assertEqual(result["likes"], 0)
        self.assertEqual(result["comments"], 0)

    def test_repost_uses_only_own_text_and_attachments(self):
        own_photo = self.photo_attachment("own")
        post = make_post(
            1,
            text="Собственный текст",
            attachments=[own_photo],
            copy_history=[
                {
                    "text": "Текст оригинала",
                    "attachments": [
                        self.video_attachment("Видео оригинала")
                    ],
                }
            ],
        )

        result = normalize_vk_post(post)

        self.assertEqual(result["text"], "Собственный текст")
        self.assertEqual(result["post_type"], "Текст с картинкой")
        self.assertEqual(result["image_url"], "https://img/own.jpg")
        self.assertEqual(result["video_description"], "")

    @staticmethod
    def photo_attachment(name):
        return {
            "type": "photo",
            "photo": {
                "sizes": [
                    {
                        "url": f"https://img/{name}.jpg",
                        "width": 800,
                        "height": 600,
                    }
                ]
            },
        }

    @staticmethod
    def video_attachment(description):
        return {
            "type": "video",
            "video": {"description": description},
        }


class VkErrorHandlingTestCase(unittest.TestCase):
    def test_vk_error_is_converted_to_vk_api_error(self):
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(
                {
                    "error": {
                        "error_code": 5,
                        "error_msg": "User authorization failed",
                    }
                }
            ),
        )

        with self.assertRaises(VkApiError) as context:
            parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        self.assertIn("5", str(context.exception))
        self.assertIn("User authorization failed", str(context.exception))

    def test_network_failure_is_converted_to_parser_error(self):
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(OSError("network unavailable")),
        )

        with self.assertRaisesRegex(VkParserError, "Не удалось выполнить"):
            parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

    def test_invalid_json_is_converted_to_parser_error(self):
        parser = VkParser(
            TOKEN,
            transport=FakeTransport("not-json"),
        )

        with self.assertRaisesRegex(VkParserError, "некорректный JSON"):
            parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

    def test_token_is_not_exposed_in_exception(self):
        parser = VkParser(
            TOKEN,
            transport=FakeTransport(
                {
                    "error": {
                        "error_code": 5,
                        "error_msg": f"Токен {TOKEN} недействителен",
                    }
                }
            ),
        )

        with self.assertRaises(VkApiError) as context:
            parser.fetch_posts("-123456", "2026-07-01", "2026-07-31")

        self.assertNotIn(TOKEN, str(context.exception))


if __name__ == "__main__":
    unittest.main()
