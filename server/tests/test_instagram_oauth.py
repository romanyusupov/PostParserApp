import os
import pathlib
import re
import stat
import tempfile
import unittest
import urllib.parse
from unittest import mock

from server.postparser_web import create_app
from server.postparser_web.instagram_oauth import (
    INSTAGRAM_AUTHORIZATION_URL,
    INSTAGRAM_LONG_TOKEN_URL,
    INSTAGRAM_OAUTH_SCOPES,
    INSTAGRAM_TOKEN_URL,
)
from server.postparser_web.instagram_token_store import (
    INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE,
    load_instagram_access_token,
)


EXPECTED_SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_insights",
]
FORBIDDEN_SCOPES = [
    "instagram_business_content_publish",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
]
APP_ID = "test-instagram-app-id"
APP_SECRET = "test-instagram-app-secret"
REDIRECT_URI = "https://example.test/instagram/callback"
AUTHORIZATION_CODE = "test-authorization-code"
SHORT_TOKEN = "test-short-access-token"
LONG_TOKEN = "test-long-access-token"


class FakeOAuthTransport:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def __call__(self, url, *, method, parameters):
        self.calls.append(
            {
                "url": url,
                "method": method,
                "parameters": dict(parameters),
            }
        )
        if self.error is not None:
            raise self.error

        if url == INSTAGRAM_TOKEN_URL:
            return {
                "access_token": SHORT_TOKEN,
                "user_id": "test-user-id",
            }

        if url == INSTAGRAM_LONG_TOKEN_URL:
            return {
                "access_token": LONG_TOKEN,
                "token_type": "bearer",
            }

        raise AssertionError(f"Unexpected OAuth URL: {url}")


class InstagramOAuthTestCase(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(
            os.environ,
            {
                "INSTAGRAM_APP_ID": APP_ID,
                "INSTAGRAM_APP_SECRET": APP_SECRET,
                "INSTAGRAM_REDIRECT_URI": REDIRECT_URI,
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_directory = pathlib.Path(self.temporary_directory.name)
        self.token_path = self.data_directory / "instagram" / "oauth.env"
        self.transport = FakeOAuthTransport()
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": (
                    self.data_directory / "settings.sqlite3"
                ),
                "RESULTS_DATABASE_PATH": (
                    self.data_directory / "results.sqlite3"
                ),
                "PARSE_RUNNER": object(),
                "GOOGLE_SHEETS_EXPORTER": object(),
                "INSTAGRAM_OAUTH_TRANSPORT": self.transport,
                "INSTAGRAM_TOKEN_ENV_PATH": self.token_path,
            }
        )
        self.client = self.app.test_client()

    def _connect(self):
        response = self.client.get(
            "/instagram/connect",
            base_url="https://example.test",
        )
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(response.location).query
        )
        return response, query

    def _callback(self, state, code=AUTHORIZATION_CODE):
        return self.client.get(
            "/instagram/callback",
            query_string={"code": code, "state": state},
            base_url="https://example.test",
        )

    def test_agents_policy_allows_exactly_expected_instagram_scopes(self):
        repository_root = pathlib.Path(__file__).resolve().parents[2]
        policy = (repository_root / "AGENTS.md").read_text(
            encoding="utf-8"
        )
        allowed_scopes_match = re.search(
            r"исчерпывающий список scopes:\s*\n"
            r"\s+- `([^`]+)`[^\n]*\n"
            r"\s+- `([^`]+)`",
            policy,
        )

        self.assertIsNotNone(allowed_scopes_match)
        self.assertEqual(
            list(allowed_scopes_match.groups()),
            EXPECTED_SCOPES,
        )

    def test_connect_redirect_contains_only_expected_scopes(self):
        response, query = self._connect()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.startswith(INSTAGRAM_AUTHORIZATION_URL))
        self.assertEqual(query["client_id"], [APP_ID])
        self.assertEqual(query["redirect_uri"], [REDIRECT_URI])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"][0].split(","), EXPECTED_SCOPES)
        self.assertEqual(list(INSTAGRAM_OAUTH_SCOPES), EXPECTED_SCOPES)
        self.assertTrue(query["state"][0])

        for forbidden_scope in FORBIDDEN_SCOPES:
            self.assertNotIn(forbidden_scope, response.location)

    def test_connect_sets_secure_state_cookie(self):
        response, _ = self._connect()
        cookie = response.headers.get("Set-Cookie", "")

        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_callback_exchanges_code_and_saves_env_format_token(self):
        _, query = self._connect()
        response = self._callback(query["state"][0])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"success": True, "message": "Instagram подключён."},
        )
        self.assertEqual(len(self.transport.calls), 2)
        self.assertEqual(
            self.transport.calls[0]["parameters"]["code"],
            AUTHORIZATION_CODE,
        )
        self.assertEqual(
            self.token_path.read_text(encoding="utf-8"),
            f"{INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE}={LONG_TOKEN}\n",
        )
        self.assertEqual(
            stat.S_IMODE(self.token_path.stat().st_mode),
            0o600,
        )

    def test_saved_token_is_available_to_new_parser_storage(self):
        _, query = self._connect()
        self._callback(query["state"][0])

        self.assertEqual(
            load_instagram_access_token(self.token_path),
            LONG_TOKEN,
        )

    def test_callback_response_does_not_expose_secrets(self):
        _, query = self._connect()
        response = self._callback(query["state"][0])
        body = response.get_data(as_text=True)

        for secret in (
            APP_SECRET,
            AUTHORIZATION_CODE,
            SHORT_TOKEN,
            LONG_TOKEN,
        ):
            self.assertNotIn(secret, body)

    def test_callback_failure_is_safe_in_response_and_logs(self):
        leaked_error = RuntimeError(
            f"{APP_SECRET} {AUTHORIZATION_CODE} {SHORT_TOKEN}"
        )
        self.app.config["INSTAGRAM_OAUTH_TRANSPORT"] = FakeOAuthTransport(
            error=leaked_error
        )
        _, query = self._connect()

        with self.assertLogs(self.app.logger.name, level="WARNING") as logs:
            response = self._callback(query["state"][0])

        self.assertEqual(response.status_code, 502)
        combined_output = response.get_data(as_text=True) + "\n".join(
            logs.output
        )
        for secret in (
            APP_SECRET,
            AUTHORIZATION_CODE,
            SHORT_TOKEN,
        ):
            self.assertNotIn(secret, combined_output)

    def test_callback_rejects_invalid_state_without_exchange(self):
        self._connect()
        response = self._callback("wrong-state")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.transport.calls, [])

    def test_provider_error_is_not_reflected(self):
        provider_message = "provider-secret-error-description"
        response = self.client.get(
            "/instagram/callback",
            query_string={
                "error": "access_denied",
                "error_description": provider_message,
            },
            base_url="https://example.test",
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(
            provider_message,
            response.get_data(as_text=True),
        )
        self.assertEqual(self.transport.calls, [])

    def test_connect_without_configuration_is_safe(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            response = self.client.get("/instagram/connect")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(APP_SECRET, response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
