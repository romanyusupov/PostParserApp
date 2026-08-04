import json
import pathlib
import tempfile
import unittest

from server.postparser_web import create_app
from server.postparser_web.legacy_proxy import (
    LegacyProxyUnavailableError,
    LegacyUpstreamResponse,
)


class RecordingTransport:
    def __init__(self, response=None, error=None):
        self.response = response or LegacyUpstreamResponse(
            200,
            b'{"ok":true}',
            {"Content-Type": "application/json"},
        )
        self.error = error
        self.calls = []

    def __call__(self, **request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class LegacyProxyTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        data_directory = pathlib.Path(self.temporary_directory.name)
        self.transport = RecordingTransport()
        self.app = create_app(
            {
                "TESTING": True,
                "SETTINGS_DATABASE_PATH": data_directory / "settings.sqlite3",
                "RESULTS_DATABASE_PATH": data_directory / "results.sqlite3",
                "PARSE_RUNNER": object(),
                "GOOGLE_SHEETS_EXPORTER": object(),
                "LEGACY_PROXY_BASE_URL": "http://127.0.0.1:5050",
                "LEGACY_PROXY_TRANSPORT": self.transport,
                "POSTPARSER_SERVICE_NAME": "postparser-prod",
            }
        )
        self.client = self.app.test_client()

    def test_parse_preserves_method_query_body_and_required_headers(self):
        body = b'{"groups":["group-1"]}'
        response = self.client.post(
            "/parse?mode=small",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-API-Key": "test-key",
                "Connection": "keep-alive",
            },
        )

        self.assertEqual(response.status_code, 200)
        call = self.transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "http://127.0.0.1:5050/parse?mode=small")
        self.assertEqual(call["body"], body)
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["headers"]["X-Api-Key"], "test-key")
        self.assertNotIn("Connection", call["headers"])

    def test_instagram_parse_is_proxied(self):
        self.client.post("/instagram/parse", json={"limit": 1})

        self.assertEqual(
            self.transport.calls[0]["url"],
            "http://127.0.0.1:5050/instagram/parse",
        )

    def test_success_body_and_status_are_unchanged(self):
        body = b'{"custom":[1,2],"message":"unchanged"}'
        self.transport.response = LegacyUpstreamResponse(
            201,
            body,
            {"Content-Type": "application/json; charset=utf-8"},
        )

        response = self.client.post("/parse", data=b"{}")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, body)

    def test_connect_redirect_location_is_preserved_without_following(self):
        location = "https://example.test/oauth?scope=basic"
        self.transport.response = LegacyUpstreamResponse(
            302,
            b"",
            {"Location": location},
        )

        response = self.client.get("/instagram/connect")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], location)
        self.assertEqual(len(self.transport.calls), 1)

    def test_callback_forwards_query_without_logging_sensitive_value(self):
        marker = "test-oauth-marker"
        with self.assertLogs(self.app.logger, level="INFO") as logs:
            self.app.logger.info("callback test started")
            response = self.client.get(
                "/instagram/callback",
                query_string={"code": marker, "state": "expected"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("code=test-oauth-marker", self.transport.calls[0]["url"])
        self.assertNotIn(marker, "\n".join(logs.output))

    def test_media_body_and_content_type_are_preserved(self):
        image = b"\x89PNG\r\n\x1a\n"
        self.transport.response = LegacyUpstreamResponse(
            200,
            image,
            {"Content-Type": "image/png"},
        )

        response = self.client.get("/media/folder/image.png")

        self.assertEqual(response.data, image)
        self.assertEqual(response.content_type, "image/png")
        self.assertTrue(self.transport.calls[0]["url"].endswith("/media/folder/image.png"))

    def test_media_traversal_is_rejected_before_transport(self):
        response = self.client.get("/media/%2e%2e%2fprivate.file")

        self.assertIn(response.status_code, {400, 404})
        self.assertEqual(self.transport.calls, [])

    def test_legacy_health_is_proxied_exactly(self):
        self.transport.response = LegacyUpstreamResponse(
            200,
            b'{"status":"legacy-ok"}',
            {"Content-Type": "application/json"},
        )

        response = self.client.get("/health")

        self.assertEqual(response.data, b'{"status":"legacy-ok"}')
        self.assertEqual(
            self.transport.calls[0]["url"],
            "http://127.0.0.1:5050/health",
        )

    def test_new_health_does_not_call_legacy(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(
            response.get_json(),
            {"status": "ok", "service": "postparser-prod"},
        )
        self.assertEqual(self.transport.calls, [])

    def test_unavailable_upstream_returns_safe_bad_gateway(self):
        self.transport.error = LegacyProxyUnavailableError("private details")
        request_marker = "request-body-must-not-be-logged"

        with self.assertLogs(self.app.logger, level="WARNING") as logs:
            response = self.client.post(
                "/parse",
                data=request_marker.encode("ascii"),
            )

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private", response.get_data(as_text=True))
        self.assertNotIn(request_marker, "\n".join(logs.output))

    def test_unsafe_upstream_is_rejected_without_transport_call(self):
        self.app.config["LEGACY_PROXY_BASE_URL"] = "http://public.example.test"

        response = self.client.post("/parse")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.transport.calls, [])

    def test_client_cannot_override_upstream(self):
        self.client.post("/parse?upstream=http://public.example.test")

        self.assertTrue(
            self.transport.calls[0]["url"].startswith("http://127.0.0.1:5050/")
        )

    def test_error_payload_is_sanitized_and_status_is_preserved(self):
        self.transport.response = LegacyUpstreamResponse(
            401,
            json.dumps(
                {
                    "error": "authorization token=test-value",
                    "access_token": "test-value",
                    "details": {"response": "full upstream response"},
                }
            ).encode(),
            {"Content-Type": "application/json"},
        )

        response = self.client.post("/parse")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("test-value", response.get_data(as_text=True))
        self.assertEqual(response.get_json()["access_token"], "[redacted]")

    def test_hop_by_hop_response_headers_are_removed(self):
        self.transport.response = LegacyUpstreamResponse(
            200,
            b"ok",
            {
                "Content-Type": "text/plain",
                "Connection": "close",
                "Transfer-Encoding": "chunked",
            },
        )

        response = self.client.get("/instagram/connect")

        self.assertNotIn("Connection", response.headers)
        self.assertNotIn("Transfer-Encoding", response.headers)


if __name__ == "__main__":
    unittest.main()
