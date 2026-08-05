import os
import pathlib
import tempfile
import unittest
from unittest import mock

from server.postparser_web import create_app
from server.postparser_web.authentication import (
    ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
    SESSION_SECRET_ENVIRONMENT_VARIABLE,
)


ADMIN_PASSWORD = "AdminPasswordForTests123"


def valid_group(group_id, name):
    return {
        "id": group_id,
        "name": name,
        "network": "vk",
        "url": "https://vk.com/example",
        "dateStart": "2026-08-01",
        "dateEnd": "2026-08-05",
        "advertisingTypes": [],
    }


class AuthenticationTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_directory = pathlib.Path(self.temporary_directory.name)
        self.environment = mock.patch.dict(
            os.environ,
            {ADMIN_PASSWORD_ENVIRONMENT_VARIABLE: ADMIN_PASSWORD},
        )
        self.environment.start()
        self.app = create_app(
            {
                "TESTING": True,
                "AUTHENTICATION_DISABLED": False,
                "SECRET_KEY": "test-session-secret-with-safe-length",
                "SETTINGS_DATABASE_PATH": self.data_directory
                / "settings.sqlite3",
                "RESULTS_DATABASE_PATH": self.data_directory
                / "results.sqlite3",
                "ACCESS_DATABASE_PATH": self.data_directory
                / "access.sqlite3",
                "GOOGLE_SHEETS_EXPORTER": None,
            }
        )
        self.secure_cookie_default = self.app.config["SESSION_COOKIE_SECURE"]
        self.app.config["SESSION_COOKIE_SECURE"] = False
        self.client = self.app.test_client()

    def tearDown(self):
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _login(self, code):
        self.client.get("/")
        with self.client.session_transaction() as browser_session:
            csrf_token = browser_session["csrf_token"]
        return self.client.post(
            "/login",
            data={"access_code": code, "csrf_token": csrf_token},
        )

    def _csrf_headers(self, client=None):
        selected_client = client or self.client
        with selected_client.session_transaction() as browser_session:
            return {"X-CSRF-Token": browser_session["csrf_token"]}

    def _set_principal(self, owner_id, name, role="user"):
        with self.client.session_transaction() as browser_session:
            browser_session["principal"] = {
                "owner_id": owner_id,
                "name": name,
                "role": role,
            }
            browser_session["csrf_token"] = "test-csrf-token"

    def test_welcome_page_has_exact_heading_and_single_access_field(self):
        response = self.client.get("/")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Добро пожаловать в сервис аналитики публикаций в социальных сетях",
            page,
        )
        self.assertEqual(page.count('id="accessCode"'), 1)
        self.assertIn("Введите ваш код доступа", page)

    def test_unauthenticated_api_is_rejected_and_health_is_public(self):
        api_response = self.client.get("/api/v1/settings")
        health_response = self.client.get("/health")

        self.assertEqual(api_response.status_code, 401)
        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.get_json(), {"status": "ok"})

    def test_session_cookie_has_required_security_flags(self):
        self.assertTrue(self.app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertTrue(self.secure_cookie_default)
        self.assertEqual(self.app.config["SESSION_COOKIE_SAMESITE"], "Lax")

    def test_production_refuses_to_start_without_authentication_secrets(self):
        with mock.patch.dict(
            os.environ,
            {
                ADMIN_PASSWORD_ENVIRONMENT_VARIABLE: "",
                SESSION_SECRET_ENVIRONMENT_VARIABLE: "",
            },
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Production-аутентификация не настроена",
            ):
                create_app(
                    {
                        "TESTING": False,
                        "AUTHENTICATION_DISABLED": False,
                        "SETTINGS_DATABASE_PATH": self.data_directory
                        / "missing-settings.sqlite3",
                        "ACCESS_DATABASE_PATH": self.data_directory
                        / "missing-access.sqlite3",
                    }
                )

    def test_admin_password_opens_settings_and_access_panel(self):
        response = self._login(ADMIN_PASSWORD)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/shadow/settings")
        settings_page = self.client.get("/shadow/settings")
        access_page = self.client.get("/admin/access")
        self.assertEqual(settings_page.status_code, 200)
        self.assertEqual(access_page.status_code, 200)
        self.assertIn("Дать доступ", access_page.get_data(as_text=True))

    def test_invalid_code_has_generic_error(self):
        response = self._login("wrong-code")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 401)
        self.assertIn("Неверный код доступа", page)
        self.assertNotIn(ADMIN_PASSWORD, page)

    def test_admin_creates_twenty_character_code_stored_only_as_hash(self):
        self._login(ADMIN_PASSWORD)

        response = self.client.post(
            "/api/v1/admin/users",
            json={},
            headers=self._csrf_headers(),
        )
        user = response.get_json()["user"]

        self.assertEqual(response.status_code, 201)
        self.assertEqual(user["name"], "Пользователь 1")
        self.assertEqual(len(user["access_code"]), 20)
        database_bytes = (self.data_directory / "access.sqlite3").read_bytes()
        self.assertNotIn(user["access_code"].encode("utf-8"), database_bytes)

        users_response = self.client.get("/api/v1/admin/users")
        stored_user = users_response.get_json()["users"][0]
        self.assertNotIn("access_code", stored_user)
        self.assertNotIn("code_hash", stored_user)

    def test_user_starts_empty_and_cannot_open_admin_panel(self):
        user = self.app.extensions["access_store"].create_user()

        self._login(user["access_code"])

        settings = self.client.get("/api/v1/settings").get_json()
        self.assertEqual(settings["revision"], 0)
        self.assertEqual(settings["settings"]["groups"], [])
        self.assertEqual(self.client.get("/admin/access").status_code, 302)
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/users",
                json={},
                headers=self._csrf_headers(),
            ).status_code,
            403,
        )

    def test_settings_and_runs_are_isolated_between_users(self):
        settings_store = self.app.extensions["settings_store"]
        results_store = self.app.extensions["results_store"]
        settings_store.save(
            {"groups": [valid_group("admin-group", "Admin")], "savedAt": ""},
            0,
            owner_id="admin",
        )
        settings_store.save(
            {"groups": [valid_group("user-group", "User")], "savedAt": ""},
            0,
            owner_id="user:1",
        )
        admin_run = results_store.create_run(
            "admin-group", "Admin", "vk", owner_id="admin"
        )
        user_run = results_store.create_run(
            "user-group", "User", "vk", owner_id="user:1"
        )
        created_user = self.app.extensions["access_store"].create_user()
        self.assertEqual(created_user["owner_id"], "user:1")
        self._set_principal("user:1", "Пользователь 1")

        settings_response = self.client.get("/api/v1/settings").get_json()
        runs_response = self.client.get("/api/v1/runs").get_json()

        self.assertEqual(
            [group["id"] for group in settings_response["settings"]["groups"]],
            ["user-group"],
        )
        self.assertEqual(
            [run["id"] for run in runs_response["runs"]],
            [user_run],
        )
        self.assertEqual(self.client.get(f"/api/v1/runs/{admin_run}").status_code, 404)

        parse_response = self.client.post(
            "/api/v1/parse",
            json={"groupId": "admin-group"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(parse_response.status_code, 404)

    def test_csrf_is_required_for_authenticated_post_requests(self):
        self._login(ADMIN_PASSWORD)

        response = self.client.post("/api/v1/admin/users", json={})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["success"], False)

    def test_successful_login_rotates_session_identifier(self):
        self.client.get("/")
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("session_id", browser_session)

        self._login(ADMIN_PASSWORD)

        with self.client.session_transaction() as browser_session:
            self.assertGreater(len(browser_session["session_id"]), 32)

    def test_repeated_invalid_logins_are_rate_limited(self):
        responses = [self._login("wrong-code") for _ in range(9)]

        self.assertTrue(all(response.status_code == 401 for response in responses[:8]))
        self.assertEqual(responses[8].status_code, 429)

    def test_disabled_user_immediately_loses_existing_session(self):
        self._login(ADMIN_PASSWORD)
        create_response = self.client.post(
            "/api/v1/admin/users",
            json={},
            headers=self._csrf_headers(),
        )
        user = create_response.get_json()["user"]
        user_client = self.app.test_client()
        user_client.get("/")
        with user_client.session_transaction() as browser_session:
            login_csrf = browser_session["csrf_token"]
        login_response = user_client.post(
            "/login",
            data={
                "access_code": user["access_code"],
                "csrf_token": login_csrf,
            },
        )
        self.assertEqual(login_response.status_code, 302)

        disable_response = self.client.patch(
            f"/api/v1/admin/users/{user['id']}",
            json={"active": False},
            headers=self._csrf_headers(),
        )

        self.assertEqual(disable_response.status_code, 200)
        self.assertEqual(user_client.get("/api/v1/settings").status_code, 401)
        user_client.get("/")
        with user_client.session_transaction() as browser_session:
            disabled_login_csrf = browser_session["csrf_token"]
        self.assertEqual(
            user_client.post(
                "/login",
                data={
                    "access_code": user["access_code"],
                    "csrf_token": disabled_login_csrf,
                },
            ).status_code,
            401,
        )

    def test_logout_clears_session(self):
        self._login(ADMIN_PASSWORD)
        response = self.client.post(
            "/logout",
            data={"csrf_token": self._csrf_headers()["X-CSRF-Token"]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/v1/settings").status_code, 401)


if __name__ == "__main__":
    unittest.main()
