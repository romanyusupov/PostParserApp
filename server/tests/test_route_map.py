import pathlib
import tempfile
import unittest

from server.postparser_web import create_app


class RouteMapTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        data_directory = pathlib.Path(self.temporary_directory.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": data_directory / "settings.sqlite3",
                "RESULTS_DATABASE_PATH": data_directory / "results.sqlite3",
                "PARSE_RUNNER": object(),
                "GOOGLE_SHEETS_EXPORTER": object(),
            }
        )

    def test_compatibility_and_new_routes_are_all_registered(self):
        routes = {
            (rule.rule, method)
            for rule in self.app.url_map.iter_rules()
            for method in rule.methods - {"HEAD", "OPTIONS"}
        }
        expected = {
            ("/parse", "POST"),
            ("/instagram/parse", "POST"),
            ("/instagram/connect", "GET"),
            ("/instagram/callback", "GET"),
            ("/media/<path:file_name>", "GET"),
            ("/health", "GET"),
            ("/api/v1/health", "GET"),
            ("/api/v1/parse", "POST"),
            ("/api/v1/runs", "GET"),
            ("/api/v1/settings", "GET"),
            ("/api/v1/settings", "PUT"),
            ("/results", "GET"),
            ("/shadow/settings", "GET"),
        }

        self.assertTrue(expected.issubset(routes))

    def test_no_route_and_method_pair_is_registered_twice(self):
        pairs = [
            (rule.rule, method)
            for rule in self.app.url_map.iter_rules()
            for method in rule.methods - {"HEAD", "OPTIONS"}
        ]

        self.assertEqual(len(pairs), len(set(pairs)))

    def test_proxy_module_does_not_open_legacy_secret_files(self):
        proxy_source = (
            pathlib.Path(__file__).parents[1]
            / "postparser_web"
            / "legacy_proxy.py"
        ).read_text(encoding="utf-8")

        for forbidden in (".session", "instagram_token", "telegram_api.py"):
            self.assertNotIn(forbidden, proxy_source)


if __name__ == "__main__":
    unittest.main()
