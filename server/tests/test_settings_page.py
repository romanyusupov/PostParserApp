import pathlib
import tempfile
import unittest
from html.parser import HTMLParser

from server.postparser_web import create_app


class ScriptTagParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script_tags = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script_tags.append(dict(attrs))


class SettingsPageTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = (
            pathlib.Path(self.temporary_directory.name)
            / "settings.sqlite3"
        )
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": database_path,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def get_page(self):
        return self.client.get("/shadow/settings")

    def test_settings_page_returns_ok(self):
        response = self.get_page()

        self.assertEqual(response.status_code, 200)

    def test_settings_page_contains_title(self):
        page = self.get_page().get_data(as_text=True)

        self.assertIn("Настройки парсера", page)

    def test_settings_page_loads_javascript(self):
        page = self.get_page().get_data(as_text=True)

        self.assertIn("/static/settings.js", page)

    def test_settings_page_loads_stylesheet(self):
        page = self.get_page().get_data(as_text=True)

        self.assertIn("/static/settings.css", page)

    def test_settings_are_not_embedded_in_html(self):
        hidden_name = "Скрытая группа из SQLite"
        self.app.extensions["settings_store"].save(
            {
                "groups": [
                    {
                        "id": "hidden_group",
                        "name": hidden_name,
                    }
                ],
                "savedAt": "",
            },
            expected_revision=0,
        )

        page = self.get_page().get_data(as_text=True)

        self.assertNotIn(hidden_name, page)

    def test_settings_page_has_no_inline_script(self):
        page = self.get_page().get_data(as_text=True)
        parser = ScriptTagParser()
        parser.feed(page)

        self.assertTrue(parser.script_tags)
        self.assertTrue(
            all(script.get("src") for script in parser.script_tags)
        )


if __name__ == "__main__":
    unittest.main()
