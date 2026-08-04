import os
import pathlib
import tempfile
from typing import Any

from server.postparser_web.config import get_data_dir


INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE = (
    "POSTPARSER_INSTAGRAM_ACCESS_TOKEN"
)
INSTAGRAM_TOKEN_ENV_FILENAME = "access-token.env"


class InstagramTokenStorageError(Exception):
    """Не удалось безопасно прочитать или сохранить Instagram-токен."""


def get_instagram_token_env_path() -> pathlib.Path:
    return get_data_dir() / "instagram" / INSTAGRAM_TOKEN_ENV_FILENAME


def _normalized_path(path: Any = None) -> pathlib.Path:
    if path is None:
        return get_instagram_token_env_path()

    return pathlib.Path(path)


def load_instagram_access_token(path: Any = None) -> str:
    environment_token = os.environ.get(
        INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE,
        "",
    ).strip()
    if environment_token:
        return environment_token

    token_path = _normalized_path(path)
    if not token_path.is_file():
        return ""

    try:
        matching_values = []
        for raw_line in token_path.read_text(encoding="utf-8").splitlines():
            name, separator, value = raw_line.partition("=")
            if (
                separator
                and name.strip()
                == INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE
            ):
                matching_values.append(value.strip())
    except OSError:
        raise InstagramTokenStorageError(
            "Не удалось прочитать Instagram OAuth token storage."
        ) from None

    if len(matching_values) != 1:
        return ""

    return matching_values[0]


def save_instagram_access_token(token: Any, path: Any = None) -> pathlib.Path:
    normalized_token = str(token or "").strip()
    if (
        not normalized_token
        or "\n" in normalized_token
        or "\r" in normalized_token
        or "\x00" in normalized_token
    ):
        raise InstagramTokenStorageError(
            "Instagram OAuth вернул некорректный access token."
        )

    token_path = _normalized_path(path)
    token_directory = token_path.parent
    temporary_path = None

    try:
        token_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(token_directory, 0o700)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".instagram-token-",
            dir=token_directory,
            text=True,
        )
        temporary_path = pathlib.Path(temporary_name)
        os.chmod(temporary_path, 0o600)

        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(
                f"{INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE}="
                f"{normalized_token}\n"
            )
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_path, token_path)
        temporary_path = None
        os.chmod(token_path, 0o600)
    except OSError:
        raise InstagramTokenStorageError(
            "Не удалось сохранить Instagram OAuth token storage."
        ) from None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass

    return token_path
