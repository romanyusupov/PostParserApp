import unittest

from server.postparser_web.instagram_identifier import (
    normalize_instagram_identifier,
)


class InstagramIdentifierTestCase(unittest.TestCase):
    def test_supported_profile_forms_are_canonicalized(self):
        for value in (
            "proactivum",
            "@proactivum",
            "https://instagram.com/proactivum",
            "https://instagram.com/proactivum/",
            "https://www.instagram.com/proactivum",
            "https://www.instagram.com/proactivum/",
            "https://www.instagram.com/proactivum/?hl=ru",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_instagram_identifier(value),
                    "proactivum",
                )

    def test_dotted_username_is_canonicalized(self):
        for value in (
            "torsunov.oleg",
            "@TORSUNOV.OLEG",
            "https://www.instagram.com/torsunov.oleg/",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_instagram_identifier(value),
                    "torsunov.oleg",
                )

    def test_unsafe_or_non_profile_urls_are_rejected(self):
        for value in (
            "https://evil.instagram.com/proactivum/",
            "https://instagram.com.evil.com/proactivum/",
            "https://www.instagram.com/p/post-id/",
            "https://www.instagram.com/p/",
            "https://www.instagram.com/reel/reel-id/",
            "https://www.instagram.com/reel/",
            "https://www.instagram.com/proactivum/extra",
            "https://www.instagram.com/proactivum/#fragment",
            "https://user@www.instagram.com/proactivum/",
            "http://www.instagram.com/proactivum/",
            "proactİvum",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_instagram_identifier(value), "")

    def test_numeric_account_id_is_only_accepted_in_plain_form(self):
        self.assertEqual(
            normalize_instagram_identifier("123456789"),
            "123456789",
        )
        self.assertEqual(normalize_instagram_identifier("@123456789"), "")
        self.assertEqual(
            normalize_instagram_identifier(
                "https://www.instagram.com/123456789/"
            ),
            "",
        )
