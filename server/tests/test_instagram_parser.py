import datetime
import io
import json
import unittest
import urllib.error
import urllib.parse
from unittest import mock

from server.postparser_web.instagram_parser import (
    INSIGHTS_UNAVAILABLE_WARNING,
    InstagramApiError,
    InstagramConfigurationError,
    InstagramParser,
    InstagramParserError,
    _default_transport,
    normalize_instagram_post,
)


TOKEN = "test-instagram-token-that-must-stay-secret"


def make_media(
    media_id="media_1",
    media_type="IMAGE",
    timestamp="2026-07-15T12:00:00+00:00",
    **values,
):
    media_item = {
        "id": media_id,
        "caption": "Тестовая публикация",
        "media_type": media_type,
        "media_url": f"https://img.test/{media_id}.jpg",
        "thumbnail_url": "",
        "permalink": f"https://instagram.com/p/{media_id}/",
        "timestamp": timestamp,
        "like_count": 5,
        "comments_count": 2,
    }
    media_item.update(values)
    return media_item


def insights_response(**metrics):
    return {
        "data": [
            {
                "name": name,
                "values": [{"value": value}],
            }
            for name, value in metrics.items()
        ]
    }


class FakeTransport:
    def __init__(self):
        self.responses = {}
        self.calls = []

    def add(self, path, *responses):
        self.responses.setdefault(path, []).extend(responses)
        return self

    def __call__(self, url, timeout):
        parsed = urllib.parse.urlparse(url)
        parameters = {
            key: values[-1]
            for key, values in urllib.parse.parse_qs(
                parsed.query,
                keep_blank_values=True,
            ).items()
        }
        self.calls.append(
            {
                "url": url,
                "path": parsed.path,
                "parameters": parameters,
                "timeout": timeout,
            }
        )

        responses = self.responses.get(parsed.path, [])
        if not responses:
            raise AssertionError(
                f"Не подготовлен ответ для {parsed.path}"
            )

        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response

        if isinstance(response, (bytes, str)):
            return response

        return json.dumps(response, ensure_ascii=False).encode("utf-8")


def make_parser_for_posts(*pages):
    transport = FakeTransport().add(
        "/v22.0/me/media",
        *pages,
    )

    media_ids = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        for media_item in page.get("data", []):
            media_id = str(media_item.get("id") or "")
            if media_id and media_id not in media_ids:
                media_ids.append(media_id)

    for media_id in media_ids:
        transport.add(
            f"/v22.0/{media_id}/insights",
            insights_response(),
        )

    return InstagramParser(TOKEN, transport=transport), transport


class InstagramParserConfigurationTestCase(unittest.TestCase):
    def test_empty_token_is_rejected(self):
        for token in (None, "", "   "):
            with self.subTest(token=token):
                with self.assertRaises(InstagramConfigurationError):
                    InstagramParser(token)


class InstagramPostNormalizationTestCase(unittest.TestCase):
    def test_image_is_converted_to_photo(self):
        result = normalize_instagram_post(make_media(media_type="IMAGE"))

        self.assertEqual(result["post_type"], "Фото")
        self.assertEqual(result["video_description"], "")

    def test_carousel_is_converted_to_carousel(self):
        result = normalize_instagram_post(
            make_media(media_type="CAROUSEL_ALBUM")
        )

        self.assertEqual(result["post_type"], "Карусель")

    def test_video_is_converted_to_video(self):
        result = normalize_instagram_post(make_media(media_type="VIDEO"))

        self.assertEqual(result["post_type"], "Видео")

    def test_caption_is_preserved_without_truncation(self):
        caption = "Начало\n\n" + "Очень длинный текст " * 1000

        result = normalize_instagram_post(
            make_media(caption=caption)
        )

        self.assertEqual(result["text"], caption)

    def test_first_nonempty_paragraph_is_selected(self):
        result = normalize_instagram_post(
            make_media(
                caption=(
                    "\n\n Первый абзац \nпродолжение"
                    "\n\nВторой абзац"
                )
            )
        )

        self.assertEqual(
            result["first_paragraph"],
            "Первый абзац\nпродолжение",
        )

    def test_empty_caption_has_empty_first_paragraph(self):
        result = normalize_instagram_post(make_media(caption=""))

        self.assertEqual(result["first_paragraph"], "")

    def test_media_urls_are_selected_by_type(self):
        cases = (
            (
                make_media(
                    media_type="IMAGE",
                    media_url="https://img.test/image.jpg",
                ),
                "",
                "https://img.test/image.jpg",
            ),
            (
                make_media(
                    media_type="VIDEO",
                    media_url="https://img.test/video.mp4",
                    thumbnail_url="https://img.test/video.jpg",
                ),
                "",
                "https://img.test/video.jpg",
            ),
            (
                make_media(media_type="CAROUSEL_ALBUM"),
                "https://img.test/first-child.jpg",
                "https://img.test/first-child.jpg",
            ),
        )

        for media_item, carousel_url, expected in cases:
            with self.subTest(media_type=media_item["media_type"]):
                result = normalize_instagram_post(
                    media_item,
                    carousel_image_url=carousel_url,
                )
                self.assertEqual(result["image_url"], expected)


class InstagramInsightsTestCase(unittest.TestCase):
    def test_http_5xx_is_not_converted_to_api_permission_error(self):
        http_error = urllib.error.HTTPError(
            "https://graph.instagram.com/v22.0/me/media",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"error":{"code":10,"message":"permission"}}'),
        )

        try:
            with (
                mock.patch(
                    "urllib.request.urlopen",
                    side_effect=http_error,
                ),
                self.assertRaises(urllib.error.HTTPError),
            ):
                _default_transport(
                    "https://graph.instagram.com/v22.0/me/media",
                    5,
                )
        finally:
            http_error.close()

    def test_insight_metrics_are_read(self):
        transport = FakeTransport().add(
            "/v22.0/media_1/insights",
            insights_response(
                views=100,
                reach=80,
                saved=7,
                shares=3,
            ),
        )
        parser = InstagramParser(TOKEN, transport=transport)

        result = parser.fetch_insights("media_1")

        self.assertEqual(
            result,
            {
                "views": 100,
                "reach": 80,
                "saved": 7,
                "shares": 3,
            },
        )
        self.assertEqual(
            transport.calls[0]["parameters"]["metric"],
            "views,reach,saved,shares",
        )

    def test_missing_insight_metrics_remain_unavailable(self):
        transport = FakeTransport().add(
            "/v22.0/media_1/insights",
            insights_response(reach=12),
        )
        parser = InstagramParser(TOKEN, transport=transport)

        result = parser.fetch_insights("media_1")

        self.assertEqual(
            result,
            {
                "views": None,
                "reach": 12,
                "saved": None,
                "shares": None,
            },
        )

    def test_api_error_is_converted_to_instagram_api_error(self):
        transport = FakeTransport().add(
            "/v22.0/media_1/insights",
            {
                "error": {
                    "message": "Unsupported metric",
                    "code": 123,
                }
            },
        )
        parser = InstagramParser(TOKEN, transport=transport)

        with self.assertRaises(InstagramApiError) as context:
            parser.fetch_insights("media_1")

        self.assertIn("123", str(context.exception))
        self.assertIn("Unsupported metric", str(context.exception))

    def test_token_is_not_exposed_in_exception(self):
        transport = FakeTransport().add(
            "/v22.0/media_1/insights",
            {
                "error": {
                    "message": f"Недействительный токен {TOKEN}",
                    "code": 190,
                }
            },
        )
        parser = InstagramParser(TOKEN, transport=transport)

        with self.assertRaises(InstagramApiError) as context:
            parser.fetch_insights("media_1")

        self.assertNotIn(TOKEN, str(context.exception))
        self.assertNotIn("access_token=", str(context.exception))


class InstagramPaginationTestCase(unittest.TestCase):
    def test_insights_network_error_is_not_treated_as_missing_permission(self):
        transport = (
            FakeTransport()
            .add(
                "/v22.0/me/media",
                {"data": [make_media("media_1")]},
            )
            .add(
                "/v22.0/media_1/insights",
                RuntimeError("temporary network failure"),
            )
        )
        parser = InstagramParser(TOKEN, transport=transport)

        with self.assertRaises(InstagramParserError):
            parser.fetch_posts(
                "account_1",
                "2026-07-01",
                "2026-07-31",
            )

        self.assertEqual(parser.warning, "")

    def test_missing_insights_permission_keeps_posts_and_stops_requests(self):
        permission_response = {
            "error": {
                "message": (
                    "Application does not have permission for this action; "
                    f"private response {TOKEN}"
                ),
                "code": 10,
            }
        }
        transport = (
            FakeTransport()
            .add(
                "/v22.0/me/media",
                {
                    "data": [
                        make_media("media_1"),
                        make_media("media_2"),
                    ]
                },
            )
            .add("/v22.0/media_1/insights", permission_response)
        )
        parser = InstagramParser(TOKEN, transport=transport)

        with self.assertLogs(
            "server.postparser_web.instagram_parser",
            level="WARNING",
        ) as captured_logs:
            result = parser.fetch_posts(
                "account_1",
                "2026-07-01",
                "2026-07-31",
            )

        insight_calls = [
            call
            for call in transport.calls
            if call["path"].endswith("/insights")
        ]
        self.assertEqual(len(result), 2)
        self.assertEqual(len(insight_calls), 1)
        self.assertEqual(parser.warning, INSIGHTS_UNAVAILABLE_WARNING)
        for post in result:
            self.assertEqual(
                {
                    metric: post[metric]
                    for metric in ("views", "reach", "saved", "shares")
                },
                {
                    "views": None,
                    "reach": None,
                    "saved": None,
                    "shares": None,
                },
            )

        log_text = "\n".join(captured_logs.output)
        self.assertIn(INSIGHTS_UNAVAILABLE_WARNING, log_text)
        self.assertNotIn(TOKEN, log_text)
        self.assertNotIn("private response", log_text)

    def test_base_media_permission_error_is_not_ignored(self):
        transport = FakeTransport().add(
            "/v22.0/me/media",
            {
                "error": {
                    "message": "Application does not have permission",
                    "code": 10,
                }
            },
        )
        parser = InstagramParser(TOKEN, transport=transport)

        with self.assertRaises(InstagramApiError):
            parser.fetch_posts(
                "account_1",
                "2026-07-01",
                "2026-07-31",
            )

    def test_fetch_posts_adds_carousel_image_and_insights(self):
        media_item = make_media(
            "media_1",
            media_type="CAROUSEL_ALBUM",
            like_count=15,
            comments_count=4,
        )
        transport = (
            FakeTransport()
            .add("/v22.0/me/media", {"data": [media_item]})
            .add(
                "/v22.0/media_1/children",
                {
                    "data": [
                        {
                            "id": "child_1",
                            "media_type": "IMAGE",
                            "media_url": "https://img.test/child_1.jpg",
                        }
                    ]
                },
            )
            .add(
                "/v22.0/media_1/insights",
                insights_response(
                    views=120,
                    reach=95,
                    saved=8,
                    shares=6,
                ),
            )
        )
        parser = InstagramParser(TOKEN, transport=transport)

        result = parser.fetch_posts(
            "account_1",
            "2026-07-01",
            "2026-07-31",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["image_url"],
            "https://img.test/child_1.jpg",
        )
        self.assertEqual(
            {
                name: result[0][name]
                for name in (
                    "views",
                    "reach",
                    "likes",
                    "comments",
                    "saved",
                    "shares",
                )
            },
            {
                "views": 120,
                "reach": 95,
                "likes": 15,
                "comments": 4,
                "saved": 8,
                "shares": 6,
            },
        )

    def test_date_range_is_inclusive_and_posts_are_sorted(self):
        page = {
            "data": [
                make_media(
                    "start",
                    timestamp="2026-07-01T00:00:00+00:00",
                ),
                make_media(
                    "end",
                    timestamp="2026-07-31T23:59:59+00:00",
                ),
                make_media(
                    "before",
                    timestamp="2026-06-30T23:59:59+00:00",
                ),
                make_media(
                    "after",
                    timestamp="2026-08-01T00:00:00+00:00",
                ),
            ]
        }
        parser, _ = make_parser_for_posts(page)

        result = parser.fetch_posts(
            "account_1",
            "2026-07-01",
            "2026-07-31",
        )

        self.assertEqual(
            [post["external_id"] for post in result],
            ["end", "start"],
        )

    def test_media_pagination_uses_next_url(self):
        first_page = {
            "data": [make_media("media_1")],
            "paging": {
                "next": (
                    "https://graph.instagram.com/v22.0/me/media"
                    "?after=next-page&access_token=old-token"
                )
            },
        }
        second_page = {"data": [make_media("media_2")]}
        parser, transport = make_parser_for_posts(
            first_page,
            second_page,
        )

        result = parser.fetch_posts(
            "account_1",
            "2026-07-01",
            "2026-07-31",
        )

        media_calls = [
            call
            for call in transport.calls
            if call["path"] == "/v22.0/me/media"
        ]
        self.assertEqual(len(result), 2)
        self.assertEqual(len(media_calls), 2)
        self.assertEqual(
            media_calls[1]["parameters"]["after"],
            "next-page",
        )
        self.assertEqual(
            media_calls[1]["parameters"]["access_token"],
            TOKEN,
        )

    def test_media_pagination_uses_cursor_next(self):
        first_page = {
            "data": [make_media("media_1")],
            "paging": {"cursors": {"next": "cursor-page"}},
        }
        second_page = {"data": [make_media("media_2")]}
        parser, transport = make_parser_for_posts(
            first_page,
            second_page,
        )

        parser.fetch_posts(
            "account_1",
            datetime.date(2026, 7, 1),
            datetime.date(2026, 7, 31),
        )

        media_calls = [
            call
            for call in transport.calls
            if call["path"] == "/v22.0/me/media"
        ]
        self.assertEqual(len(media_calls), 2)
        self.assertEqual(
            media_calls[1]["parameters"]["after"],
            "cursor-page",
        )

    def test_pagination_stops_after_posts_older_than_start(self):
        first_page = {
            "data": [
                make_media(
                    "old",
                    timestamp="2026-06-30T12:00:00+00:00",
                )
            ],
            "paging": {"cursors": {"next": "unused-page"}},
        }
        second_page = {"data": [make_media("should_not_load")]}
        parser, transport = make_parser_for_posts(
            first_page,
            second_page,
        )

        result = parser.fetch_posts(
            "account_1",
            "2026-07-01",
            "2026-07-31",
        )

        media_calls = [
            call
            for call in transport.calls
            if call["path"] == "/v22.0/me/media"
        ]
        self.assertEqual(result, [])
        self.assertEqual(len(media_calls), 1)

    def test_reverse_date_range_is_rejected(self):
        parser = InstagramParser(TOKEN, transport=FakeTransport())

        with self.assertRaisesRegex(
            InstagramParserError,
            "не может быть позже",
        ):
            parser.fetch_posts(
                "account_1",
                "2026-08-01",
                "2026-07-31",
            )

    def test_no_real_http_requests_are_made_with_test_transport(self):
        page = {"data": [make_media("media_1")]}
        parser, _ = make_parser_for_posts(page)

        with mock.patch(
            "urllib.request.urlopen"
        ) as real_urlopen:
            result = parser.fetch_posts(
                "account_1",
                "2026-07-01",
                "2026-07-31",
            )

        self.assertEqual(len(result), 1)
        real_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
