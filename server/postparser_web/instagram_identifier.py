import re
import urllib.parse
from typing import Any


INSTAGRAM_PROFILE_HOSTS = {"instagram.com", "www.instagram.com"}
INSTAGRAM_USERNAME_PATTERN = re.compile(
    r"[a-z0-9._]{1,30}",
    re.IGNORECASE | re.ASCII,
)
INSTAGRAM_RESERVED_PATHS = {
    "accounts",
    "direct",
    "explore",
    "p",
    "reel",
    "reels",
    "stories",
    "tv",
}


def normalize_instagram_identifier(value: Any) -> str:
    identifier = str(value or "").strip()
    if not identifier:
        return ""

    if identifier.isdecimal():
        return identifier

    if "://" in identifier:
        try:
            parsed = urllib.parse.urlsplit(identifier)
            port = parsed.port
        except ValueError:
            return ""

        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() not in INSTAGRAM_PROFILE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.fragment
        ):
            return ""

        path = parsed.path
        if not path.startswith("/") or "%" in path:
            return ""

        username = path[1:-1] if path.endswith("/") else path[1:]
        if (
            not username
            or "/" in username
            or username.isdecimal()
            or username.casefold() in INSTAGRAM_RESERVED_PATHS
        ):
            return ""
    else:
        username = identifier.removeprefix("@").strip()
        if not username or username.isdecimal():
            return ""

    if not INSTAGRAM_USERNAME_PATTERN.fullmatch(username):
        return ""

    return username.casefold()
