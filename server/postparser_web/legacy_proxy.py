import ipaddress
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from flask import Blueprint, Response, current_app, jsonify, request


DEFAULT_TIMEOUT_SECONDS = 310.0
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
REQUEST_HEADERS = {"accept", "content-type", "x-api-key"}
RESPONSE_HEADERS = {
    "cache-control",
    "content-disposition",
    "content-language",
    "content-type",
    "etag",
    "expires",
    "last-modified",
    "location",
}
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "code",
    "cookie",
    "oauth_code",
    "password",
    "session",
    "session_data",
    "token",
}


legacy_proxy_bp = Blueprint("legacy_proxy", __name__)


class LegacyProxyConfigurationError(RuntimeError):
    """Legacy upstream is absent or unsafe."""


class LegacyProxyUnavailableError(RuntimeError):
    """Legacy upstream could not be reached."""


@dataclass(frozen=True)
class LegacyUpstreamResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urllib_transport(method, url, headers, body, timeout):
    upstream_request = urllib.request.Request(
        url,
        data=body if method not in {"GET", "HEAD"} else None,
        headers=dict(headers),
        method=method,
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        response = opener.open(upstream_request, timeout=timeout)
    except urllib.error.HTTPError as error:
        return LegacyUpstreamResponse(
            status=error.code,
            body=error.read(),
            headers=dict(error.headers.items()),
        )
    except (OSError, urllib.error.URLError, TimeoutError):
        raise LegacyProxyUnavailableError(
            "Legacy service is unavailable."
        ) from None

    with response:
        return LegacyUpstreamResponse(
            status=response.status,
            body=response.read(),
            headers=dict(response.headers.items()),
        )


def _allowed_hosts() -> set[str]:
    configured = current_app.config.get("LEGACY_PROXY_ALLOWED_HOSTS", ())
    if isinstance(configured, str):
        configured = configured.split(",")
    return {
        str(value).strip().casefold()
        for value in configured
        if str(value).strip()
    }


def _validated_base_url() -> str:
    value = str(
        current_app.config.get("LEGACY_PROXY_BASE_URL") or ""
    ).strip()
    if not value:
        raise LegacyProxyConfigurationError(
            "Legacy proxy is not configured."
        )

    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise LegacyProxyConfigurationError(
            "Legacy proxy upstream is not allowed."
        )

    hostname = parsed.hostname.casefold()
    allowed = hostname in _allowed_hosts()
    try:
        allowed = allowed or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        allowed = allowed or hostname == "localhost"
    if not allowed:
        raise LegacyProxyConfigurationError(
            "Legacy proxy upstream is not allowed."
        )

    path = parsed.path.rstrip("/")
    netloc = parsed.hostname
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urllib.parse.urlunsplit(("http", netloc, path, "", ""))


def _safe_media_path(file_name: str) -> str:
    decoded = urllib.parse.unquote(str(file_name or ""))
    path = pathlib.PurePosixPath(decoded)
    if (
        not decoded
        or decoded.startswith("/")
        or "\\" in decoded
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Invalid media path")
    return "/".join(
        urllib.parse.quote(part, safe="-._~") for part in path.parts
    )


def _target_url(path: str) -> str:
    base_url = _validated_base_url()
    query = request.query_string.decode("ascii", errors="strict")
    return base_url + path + (f"?{query}" if query else "")


def _request_headers() -> dict[str, str]:
    return {
        name: value
        for name, value in request.headers.items()
        if name.casefold() in REQUEST_HEADERS
        and name.casefold() not in HOP_BY_HOP_HEADERS
    }


def _redact_text(value: str) -> str:
    result = re.sub(
        r"(?i)(access_token|api[_-]?key|authorization|code|cookie|session|token)"
        r"(\s*[=:]\s*)([^\s&;,]+)",
        r"\1\2[redacted]",
        value,
    )
    result = re.sub(
        r"(?i)bearer\s+[a-z0-9._~+/=-]+",
        "Bearer [redacted]",
        result,
    )
    result = re.sub(
        r"(?:[A-Za-z]:\\|/)(?:[^\s:'\"]+[\\/]){2,}[^\s:'\"]*",
        "[internal path]",
        result,
    )
    return result


def _sanitize_json(value: Any, parent_key: str = "") -> Any:
    if parent_key.casefold() in {"details", "response"}:
        return "Sensitive upstream details were removed."
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if str(key).casefold() in SENSITIVE_KEYS
                else _sanitize_json(item, str(key))
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json(item, parent_key) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _sanitize_error(response: LegacyUpstreamResponse) -> LegacyUpstreamResponse:
    content_type = str(response.headers.get("Content-Type") or "")
    if "json" in content_type.casefold():
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
    else:
        payload = None

    if payload is None:
        payload = {
            "success": False,
            "error": "Legacy service returned an error.",
        }

    return LegacyUpstreamResponse(
        status=response.status,
        body=json.dumps(
            _sanitize_json(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _flask_response(upstream: LegacyUpstreamResponse) -> Response:
    headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.casefold() in RESPONSE_HEADERS
        and name.casefold() not in HOP_BY_HOP_HEADERS
    }
    return Response(upstream.body, status=upstream.status, headers=headers)


def proxy_current_request(path: str, method: str | None = None) -> Response:
    try:
        url = _target_url(path)
        timeout = float(
            current_app.config.get(
                "LEGACY_PROXY_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            )
        )
        transport: Callable[..., LegacyUpstreamResponse] = (
            current_app.config.get("LEGACY_PROXY_TRANSPORT")
            or _urllib_transport
        )
        upstream = transport(
            method=method or request.method,
            url=url,
            headers=_request_headers(),
            body=request.get_data(cache=True),
            timeout=timeout,
        )
        if not isinstance(upstream, LegacyUpstreamResponse):
            raise LegacyProxyUnavailableError(
                "Legacy transport returned an invalid response."
            )
    except LegacyProxyConfigurationError:
        current_app.logger.warning(
            "Legacy proxy request rejected by server configuration."
        )
        return jsonify(
            {"success": False, "error": "Legacy service is not configured."}
        ), 503
    except (LegacyProxyUnavailableError, ValueError, OSError):
        current_app.logger.warning(
            "Legacy upstream is unavailable for route %s.",
            request.path,
        )
        return jsonify(
            {
                "success": False,
                "error": "Legacy service is temporarily unavailable.",
            }
        ), 502

    if upstream.status >= 400:
        upstream = _sanitize_error(upstream)
    return _flask_response(upstream)


@legacy_proxy_bp.post("/parse")
def legacy_parse():
    return proxy_current_request("/parse")


@legacy_proxy_bp.post("/instagram/parse")
def legacy_instagram_parse():
    return proxy_current_request("/instagram/parse")


@legacy_proxy_bp.get("/instagram/connect")
def legacy_instagram_connect():
    return proxy_current_request("/instagram/connect")


@legacy_proxy_bp.get("/instagram/callback")
def legacy_instagram_callback():
    return proxy_current_request("/instagram/callback")


@legacy_proxy_bp.get("/media/<path:file_name>")
def legacy_media(file_name):
    try:
        safe_path = _safe_media_path(file_name)
    except ValueError:
        return jsonify(
            {"success": False, "error": "Invalid media path."}
        ), 400
    return proxy_current_request(f"/media/{safe_path}")
