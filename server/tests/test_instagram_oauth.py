import datetime
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
    INSTAGRAM_PROFILE_URL,
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
ADMIN_PASSWORD = "test-admin-password"
AUTHORIZATION_CODE = "test-authorization-code"
SHORT_TOKEN = "test-short-access-token"
LONG_TOKEN = "test-long-access-token"
ALLOWED_ACCOUNT_ID = "allowed-business-account-id"


class FakeOAuthTransport:
    def __init__(
        self,
        error=None,
        profile_id=ALLOWED_ACCOUNT_ID,
        profile_username="connected-account",
    ):
        self.error = error
        self.profile_id = profile_id
        self.profile_username = profile_username
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
            return {"access_token": SHORT_TOKEN, "user_id": self.profile_id}
        if url == INSTAGRAM_LONG_TOKEN_URL:
            return {"access_token": LONG_TOKEN, "token_type": "bearer"}
        if url == INSTAGRAM_PROFILE_URL:
            return {
                "id": self.profile_id,
                "user_id": self.profile_id,
                "username": self.profile_username,
                "account_type": "BUSINESS",
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
                "POSTPARSER_INSTAGRAM_ACCOUNT_ID": ALLOWED_ACCOUNT_ID,
                "POSTPARSER_ADMIN_PASSWORD": ADMIN_PASSWORD,
                "POSTPARSER_PUBLIC_BASE_URL": "https://example.test",
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_directory = pathlib.Path(self.temporary_directory.name)
        self.access_path = self.data_directory / "access.sqlite3"
        self.token_path = self.data_directory / "instagram" / "oauth.env"
        self.transport = FakeOAuthTransport()
        self.app = create_app(
            {
                "TESTING": True,
                "AUTHENTICATION_DISABLED": False,
                "SECRET_KEY": "test-session-secret-with-safe-length",
                "SESSION_COOKIE_SECURE": False,
                "SETTINGS_DATABASE_PATH": self.data_directory
                / "settings.sqlite3",
                "RESULTS_DATABASE_PATH": self.data_directory
                / "results.sqlite3",
                "ACCESS_DATABASE_PATH": self.access_path,
                "PARSE_RUNNER": object(),
                "GOOGLE_SHEETS_EXPORTER": object(),
                "INSTAGRAM_OAUTH_TRANSPORT": self.transport,
                "INSTAGRAM_TOKEN_ENV_PATH": self.token_path,
            }
        )
        self.app.config["SESSION_COOKIE_SECURE"] = False
        self.admin_client = self.app.test_client()
        self.public_client = self.app.test_client()
        self._login(self.admin_client, ADMIN_PASSWORD)

    def _login(self, client, code):
        client.get("/")
        with client.session_transaction() as browser_session:
            csrf_token = browser_session["csrf_token"]
        return client.post(
            "/login",
            data={"access_code": code, "csrf_token": csrf_token},
        )

    def _csrf_headers(self, client=None):
        selected = client or self.admin_client
        with selected.session_transaction() as browser_session:
            return {"X-CSRF-Token": browser_session["csrf_token"]}

    def _create_invitation(self):
        response = self.admin_client.post(
            "/api/v1/admin/instagram/oauth-invitations",
            json={},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201)
        setup_url = response.get_json()["setup_url"]
        parsed = urllib.parse.urlparse(setup_url)
        setup_token = urllib.parse.parse_qs(parsed.query)["setup_token"][0]
        return setup_url, setup_token

    def _connect(self, setup_url=None):
        if setup_url is None:
            setup_url, _ = self._create_invitation()
        parsed = urllib.parse.urlparse(setup_url)
        response = self.public_client.get(
            parsed.path + "?" + parsed.query,
            base_url="https://example.test",
        )
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(response.location or "").query
        )
        return response, query

    def _callback(self, state, code=AUTHORIZATION_CODE, client=None):
        return (client or self.public_client).get(
            "/instagram/callback",
            query_string={"code": code, "state": state},
            base_url="https://example.test",
        )

    def test_agents_policy_allows_exactly_expected_instagram_scopes(self):
        repository_root = pathlib.Path(__file__).resolve().parents[2]
        policy = (repository_root / "AGENTS.md").read_text(encoding="utf-8")
        allowed_scopes_match = re.search(
            r"исчерпывающий список scopes:\s*\n"
            r"\s+- `([^`]+)`[^\n]*\n"
            r"\s+- `([^`]+)`",
            policy,
        )
        self.assertIsNotNone(allowed_scopes_match)
        self.assertEqual(list(allowed_scopes_match.groups()), EXPECTED_SCOPES)

    def test_admin_can_create_one_time_link(self):
        setup_url, setup_token = self._create_invitation()

        self.assertTrue(setup_url.startswith("https://example.test/instagram/connect?"))
        self.assertGreaterEqual(len(setup_token), 32)
        self.assertNotIn(setup_token, self.access_path.read_bytes().decode("latin1"))
        page = self.admin_client.get("/admin/access").get_data(as_text=True)
        self.assertNotIn(setup_token, page)

    def test_regular_user_cannot_create_oauth_link(self):
        user = self.app.extensions["access_store"].create_user()
        client = self.app.test_client()
        self._login(client, user["access_code"])

        response = client.post(
            "/api/v1/admin/instagram/oauth-invitations",
            json={},
            headers=self._csrf_headers(client),
        )

        self.assertEqual(response.status_code, 403)

    def test_connect_without_or_with_wrong_token_is_forbidden(self):
        missing = self.public_client.get("/instagram/connect")
        wrong = self.public_client.get(
            "/instagram/connect",
            query_string={"setup_token": "wrong-token"},
        )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(wrong.status_code, 403)
        self.assertNotEqual(missing.status_code, 302)

    def test_valid_token_redirects_with_exact_scopes(self):
        response, query = self._connect()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.startswith(INSTAGRAM_AUTHORIZATION_URL))
        self.assertEqual(query["client_id"], [APP_ID])
        self.assertEqual(query["redirect_uri"], [REDIRECT_URI])
        self.assertEqual(query["scope"][0].split(","), EXPECTED_SCOPES)
        self.assertEqual(list(INSTAGRAM_OAUTH_SCOPES), EXPECTED_SCOPES)
        self.assertTrue(query["state"][0])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        for forbidden_scope in FORBIDDEN_SCOPES:
            self.assertNotIn(forbidden_scope, response.location)

    def test_expired_and_claimed_setup_tokens_are_forbidden(self):
        invitation = self.app.extensions[
            "instagram_oauth_store"
        ].create_setup_invitation(ttl_seconds=-1)
        expired = self.public_client.get(
            "/instagram/connect",
            query_string={"setup_token": invitation["setup_token"]},
        )
        setup_url, _ = self._create_invitation()
        first, _ = self._connect(setup_url)
        second, _ = self._connect(setup_url)

        self.assertEqual(expired.status_code, 403)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 403)

    def test_callback_rejects_invalid_state_without_exchange(self):
        response = self._callback("wrong-state")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.transport.calls, [])

    def test_callback_is_public_and_saves_token_after_account_check(self):
        _, query = self._connect()
        unauthenticated_client = self.app.test_client()
        response = self._callback(
            query["state"][0],
            client=unauthenticated_client,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Instagram успешно подключён",
            response.get_data(as_text=True),
        )
        self.assertEqual(len(self.transport.calls), 3)
        self.assertEqual(
            self.transport.calls[0]["parameters"]["code"],
            AUTHORIZATION_CODE,
        )
        self.assertEqual(
            load_instagram_access_token(self.token_path),
            LONG_TOKEN,
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.token_path.stat().st_mode), 0o600)

    def test_arbitrary_business_account_is_rejected(self):
        self.transport.profile_id = "arbitrary-business-account"
        _, query = self._connect()

        response = self._callback(query["state"][0])

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.token_path.exists())

    def test_configured_username_allows_only_matching_profile(self):
        allowed_username = "allowed.profile"
        self.transport.profile_id = "different-numeric-id"
        self.transport.profile_username = allowed_username.upper()
        with mock.patch.dict(
            os.environ,
            {"POSTPARSER_INSTAGRAM_ACCOUNT_ID": allowed_username},
        ):
            _, query = self._connect()

            response = self._callback(query["state"][0])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            load_instagram_access_token(self.token_path),
            LONG_TOKEN,
        )

    def test_provider_error_and_transport_failure_are_safe(self):
        _, query = self._connect()
        provider_message = "provider-secret-error-description"
        provider_response = self.public_client.get(
            "/instagram/callback",
            query_string={
                "error": "access_denied",
                "error_description": provider_message,
                "state": query["state"][0],
            },
        )
        self.assertEqual(provider_response.status_code, 400)
        self.assertNotIn(provider_message, provider_response.get_data(as_text=True))

        leaked_error = RuntimeError(
            f"{APP_SECRET} {AUTHORIZATION_CODE} {SHORT_TOKEN}"
        )
        self.app.config["INSTAGRAM_OAUTH_TRANSPORT"] = FakeOAuthTransport(
            error=leaked_error
        )
        _, query = self._connect()
        with self.assertLogs(self.app.logger.name, level="WARNING") as logs:
            failed_response = self._callback(query["state"][0])
        combined = failed_response.get_data(as_text=True) + "\n".join(logs.output)
        self.assertEqual(failed_response.status_code, 502)
        for secret in (APP_SECRET, AUTHORIZATION_CODE, SHORT_TOKEN, LONG_TOKEN):
            self.assertNotIn(secret, combined)

    def test_connect_without_oauth_configuration_is_safe(self):
        setup_url, _ = self._create_invitation()
        parsed = urllib.parse.urlparse(setup_url)
        with mock.patch.dict(os.environ, {}, clear=True):
            response = self.public_client.get(parsed.path + "?" + parsed.query)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(APP_SECRET, response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
