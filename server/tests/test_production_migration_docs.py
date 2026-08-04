import pathlib
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]


class ProductionMigrationDocumentationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = (
            REPOSITORY_ROOT / "docs" / "production-migration.md"
        ).read_text(encoding="utf-8")

    def test_document_has_exact_production_paths_and_ports(self):
        for value in (
            "/opt/postparser-prod",
            "/var/lib/postparser-prod/settings.sqlite3",
            "/var/lib/postparser-prod/parse_results.sqlite3",
            "/etc/postparser-prod.env",
            "127.0.0.1:5052",
            "http://127.0.0.1:5050",
        ):
            with self.subTest(value=value):
                self.assertIn(value, self.document)

    def test_document_keeps_production_data_separate_from_shadow(self):
        self.assertIn("Нельзя копировать shadow-базы", self.document)
        self.assertNotIn("/var/lib/postparser-shadow/", self.document)

    def test_document_contains_health_validation_and_rollback(self):
        self.assertIn(
            "http://127.0.0.1:5052/api/v1/health",
            self.document,
        )
        self.assertIn("## Немедленный rollback", self.document)
        self.assertIn("systemctl reload nginx", self.document)
        self.assertIn("http://127.0.0.1:5050/health", self.document)

    def test_document_does_not_reference_obsolete_source_subdirectory(self):
        self.assertNotIn("/opt/postparser-prod/source", self.document)


if __name__ == "__main__":
    unittest.main()
