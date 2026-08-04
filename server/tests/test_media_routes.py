import pathlib
import tempfile
import unittest

from server.postparser_web import create_app


class MediaRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.media_directory = pathlib.Path(self.temporary_directory.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": self.media_directory / "settings.sqlite3",
                "RESULTS_DATABASE_PATH": self.media_directory / "results.sqlite3",
                "TELEGRAM_MEDIA_DIRECTORY": self.media_directory,
            }
        )
        self.client = self.app.test_client()

    def test_existing_telegram_photo_is_served_read_only(self):
        filename = "a" * 64 + ".jpg"
        photo_path = self.media_directory / filename
        photo_path.write_bytes(b"photo-bytes")

        response = self.client.get("/media/telegram/" + filename)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"photo-bytes")
        response.close()
        self.assertEqual(photo_path.read_bytes(), b"photo-bytes")

    def test_unknown_or_invalid_photo_is_not_exposed(self):
        self.assertEqual(
            self.client.get("/media/telegram/" + "b" * 64 + ".jpg").status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/media/telegram/not-a-photo.session").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
