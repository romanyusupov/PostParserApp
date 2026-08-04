import os
import pathlib
import tempfile
import unittest
from unittest import mock

from server.postparser_web import create_app


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]


class ProductionDeploymentConfigurationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit = (
            REPOSITORY_ROOT / "deploy" / "postparser-prod.service"
        ).read_text(encoding="utf-8")
        cls.environment = (
            REPOSITORY_ROOT / "deploy" / "postparser-prod.env.example"
        ).read_text(encoding="utf-8")
        cls.nginx = (
            REPOSITORY_ROOT
            / "deploy"
            / "nginx"
            / "postparser-prod.conf.example"
        ).read_text(encoding="utf-8")
        cls.main_nginx = (
            REPOSITORY_ROOT
            / "deploy"
            / "nginx"
            / "postparser-prod-main-switch.conf.example"
        ).read_text(encoding="utf-8")

    def test_unit_uses_isolated_identity_paths_port_and_wsgi(self):
        expected_fragments = (
            "User=postparser-prod",
            "Group=postparser-prod",
            "WorkingDirectory=/opt/postparser-prod",
            "EnvironmentFile=/etc/postparser-prod.env",
            "127.0.0.1:5052",
            "server.web_wsgi:app",
            "ReadWritePaths=/var/lib/postparser-prod /var/log/postparser-prod",
        )

        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.unit)

    def test_runtime_logs_are_separate(self):
        self.assertIn("LogsDirectory=postparser-prod", self.unit)
        self.assertIn("/var/log/postparser-prod/access.log", self.unit)
        self.assertIn("/var/log/postparser-prod/error.log", self.unit)

    def test_environment_uses_separate_databases_and_legacy_policy(self):
        self.assertIn(
            "POSTPARSER_DATA_DIR=/var/lib/postparser-prod",
            self.environment,
        )
        self.assertIn(
            "POSTPARSER_LEGACY_BASE_URL=http://127.0.0.1:5050",
            self.environment,
        )
        self.assertIn(
            "POSTPARSER_LEGACY_OWNED_NETWORKS=telegram,instagram",
            self.environment,
        )
        self.assertNotIn("/var/lib/postparser-shadow", self.environment)

    def test_environment_template_has_no_secret_values(self):
        for line in self.environment.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            name, _, value = line.partition("=")
            if any(
                marker in name
                for marker in (
                    "ACCESS_TOKEN",
                    "SERVICE_ACCOUNT_JSON",
                )
            ):
                self.assertEqual(value, "")

    def test_nginx_example_targets_only_production_port(self):
        self.assertIn("proxy_pass http://127.0.0.1:5052", self.nginx)
        self.assertNotIn("127.0.0.1:5050", self.nginx)
        self.assertNotIn("127.0.0.1:5051", self.nginx)

    def test_future_main_switch_targets_production_port(self):
        self.assertIn("server 127.0.0.1:5052", self.main_nginx)
        self.assertIn("server_name tg-parser.proactivum.ru", self.main_nginx)

    def test_production_sqlite_files_are_created_outside_shadow(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            production_data = pathlib.Path(temporary_directory) / "postparser-prod"
            shadow_data = pathlib.Path(temporary_directory) / "postparser-shadow"
            with mock.patch.dict(
                os.environ,
                {"POSTPARSER_DATA_DIR": str(production_data)},
                clear=True,
            ):
                create_app(
                    {
                        "TESTING": True,
                        "PARSE_RUNNER": object(),
                        "GOOGLE_SHEETS_EXPORTER": object(),
                    }
                )

            self.assertTrue(
                (production_data / "settings.sqlite3").is_file()
            )
            self.assertTrue(
                (production_data / "parse_results.sqlite3").is_file()
            )
            self.assertFalse(shadow_data.exists())


if __name__ == "__main__":
    unittest.main()
