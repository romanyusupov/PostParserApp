import asyncio
import datetime
import hashlib
import inspect
import logging
import pathlib
import tempfile
import urllib.parse
from typing import Any


LOGGER = logging.getLogger(__name__)


class TelegramParserError(Exception):
    """Ошибка получения или преобразования публикаций Telegram."""


class TelegramConfigurationError(TelegramParserError):
    """Telegram-парсер настроен некорректно."""


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def parse_telegram_date(value: Any, field_name: str) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()

    if isinstance(value, datetime.date):
        return value

    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            pass

    raise TelegramParserError(
        f"Поле {field_name} должно иметь формат YYYY-MM-DD."
    )


def normalize_telegram_channel(value: Any) -> str:
    source = str(value or "").strip()

    if source.startswith("@"):
        source = source[1:]

    lowered = source.casefold()
    has_scheme = lowered.startswith(("http://", "https://"))
    known_host = lowered.startswith(("t.me/", "www.t.me/"))

    if has_scheme or known_host:
        parsed = urllib.parse.urlsplit(
            source if has_scheme else "https://" + source
        )
        host = (parsed.hostname or "").casefold()

        if host.startswith("www."):
            host = host[4:]

        if host != "t.me":
            raise TelegramParserError(
                "Указан неподдерживаемый адрес Telegram-канала."
            )

        channel = urllib.parse.unquote(parsed.path).strip("/").split("/", 1)[0]
    else:
        if "/" in source or "://" in source:
            raise TelegramParserError(
                "Указан некорректный адрес Telegram-канала."
            )

        channel = source.split("?", 1)[0].split("#", 1)[0]

    channel = channel.strip().lstrip("@")

    if not channel or any(character.isspace() for character in channel):
        raise TelegramParserError("Telegram-канал не указан.")

    return channel


def first_nonempty_paragraph(text: str) -> str:
    paragraph_lines = []
    paragraph_started = False

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned_line = line.strip()

        if cleaned_line:
            paragraph_started = True
            paragraph_lines.append(cleaned_line)
        elif paragraph_started:
            break

    return "\n".join(paragraph_lines)


def _message_datetime(message: Any) -> datetime.datetime:
    value = getattr(message, "date", None)

    if not isinstance(value, datetime.datetime):
        raise TelegramParserError(
            "Telegram вернул сообщение без корректной даты."
        )

    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)

    return value.astimezone(datetime.timezone.utc)


def get_telegram_post_type(message: Any) -> str:
    if getattr(message, "video", None) is not None:
        return "Видео"

    if getattr(message, "photo", None) is not None:
        return "Фото"

    return "Текст"


def _nested_metric(message: Any, container_name: str, field_name: str) -> int:
    container = getattr(message, container_name, None)
    return max(0, _safe_int(getattr(container, field_name, 0)))


def get_telegram_likes(message: Any) -> int:
    direct_likes = getattr(message, "likes", None)
    if direct_likes is not None:
        return max(0, _safe_int(direct_likes))

    reactions = getattr(message, "reactions", None)
    results = getattr(reactions, "results", None)

    if not isinstance(results, (list, tuple)):
        return 0

    return sum(
        max(0, _safe_int(getattr(reaction, "count", 0)))
        for reaction in results
    )


def get_telegram_comments(message: Any) -> int:
    direct_comments = getattr(message, "comments", None)
    if direct_comments is not None:
        return max(0, _safe_int(direct_comments))

    return _nested_metric(message, "replies", "replies")


def normalize_telegram_post(
    message: Any,
    channel_username: str,
    image_url: str = "",
    video_url: str = "",
) -> dict[str, Any]:
    message_id = _safe_int(getattr(message, "id", None))
    if message_id <= 0:
        raise TelegramParserError(
            "Telegram вернул сообщение без корректного идентификатора."
        )

    published_at = _message_datetime(message)
    text = str(
        getattr(message, "message", None)
        or getattr(message, "raw_text", None)
        or ""
    )

    return {
        "source": "telegram",
        "external_id": str(message_id),
        "url": f"https://t.me/{channel_username}/{message_id}",
        "published_at": published_at.isoformat(),
        "text": text,
        "first_paragraph": first_nonempty_paragraph(text),
        "post_type": get_telegram_post_type(message),
        "video_description": "",
        "image_url": image_url,
        "video_url": video_url,
        "views": max(0, _safe_int(getattr(message, "views", 0))),
        "likes": get_telegram_likes(message),
        "comments": get_telegram_comments(message),
        "forwards": max(0, _safe_int(getattr(message, "forwards", 0))),
    }


def _default_client_factory(
    api_id: int,
    api_hash: str,
    session_string: str | None,
    session_name: str | None,
) -> Any:
    from telethon import TelegramClient
    from telethon.sessions import MemorySession, StringSession

    if session_string:
        session = StringSession(session_string)
    elif session_name:
        session = session_name
    else:
        session = MemorySession()

    return TelegramClient(session, api_id, api_hash)


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class TelegramParser:
    def __init__(
        self,
        api_id: Any,
        api_hash: Any,
        session_string: Any = None,
        session_name: Any = None,
        client_factory: Any = None,
        media_directory: Any = None,
        public_base_url: Any = None,
    ):
        normalized_api_id = str(api_id or "").strip()
        normalized_api_hash = str(api_hash or "").strip()

        if not normalized_api_id:
            raise TelegramConfigurationError("Telegram API ID не настроен.")

        try:
            numeric_api_id = int(normalized_api_id)
        except (TypeError, ValueError):
            raise TelegramConfigurationError(
                "Telegram API ID должен быть положительным числом."
            ) from None

        if numeric_api_id <= 0:
            raise TelegramConfigurationError(
                "Telegram API ID должен быть положительным числом."
            )

        if not normalized_api_hash:
            raise TelegramConfigurationError("Telegram API hash не настроен.")

        factory = client_factory or _default_client_factory
        if not callable(factory):
            raise TelegramConfigurationError(
                "Фабрика Telegram-клиента должна быть функцией."
            )

        self._api_id = numeric_api_id
        self._api_hash = normalized_api_hash
        self._session_string = str(session_string or "").strip() or None
        raw_session_name = str(session_name or "")
        self._session_name = (
            raw_session_name
            if not self._session_string and raw_session_name.strip()
            else None
        )
        self._session_is_required = (
            client_factory is None
            and not self._session_string
            and not self._session_name
        )
        self._client_factory = factory
        media_directory_value = str(media_directory or "").strip()
        self._media_directory = (
            pathlib.Path(media_directory_value)
            if media_directory_value
            else None
        )
        self._public_base_url = str(public_base_url or "").strip().rstrip("/")

    def _safe_error_message(self, error: Exception) -> str:
        message = " ".join(str(error or "").split())

        for secret in (
            self._api_hash,
            self._session_string,
            self._session_name,
        ):
            if secret:
                message = message.replace(secret, "[скрыто]")

        return message[:500] or "Неизвестная ошибка Telegram."

    def _stored_photo_url(self, channel_username: str, message_id: int) -> str:
        digest = hashlib.sha256(
            f"{channel_username.casefold()}:{message_id}".encode("utf-8")
        ).hexdigest()
        relative_url = f"/media/telegram/{digest}.jpg"
        if not self._public_base_url:
            return relative_url
        return self._public_base_url + relative_url

    async def _download_photo(
        self,
        client: Any,
        message: Any,
        channel_username: str,
    ) -> str:
        if self._media_directory is None:
            return ""

        downloader = getattr(client, "download_media", None)
        if not callable(downloader):
            return ""

        message_id = _safe_int(getattr(message, "id", None))
        if message_id <= 0:
            return ""

        target_url = self._stored_photo_url(channel_username, message_id)
        target_path = self._media_directory / pathlib.PurePosixPath(
            urllib.parse.urlsplit(target_url).path
        ).name

        try:
            if target_path.is_file() and target_path.stat().st_size > 0:
                return target_url

            photo_bytes = await _await_if_needed(
                downloader(message, file=bytes, thumb=-1)
            )
            if not isinstance(photo_bytes, (bytes, bytearray)) or not photo_bytes:
                return ""

            self._media_directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self._media_directory,
                prefix="telegram-photo-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(bytes(photo_bytes))
                temporary_path = pathlib.Path(temporary_file.name)
            try:
                temporary_path.replace(target_path)
            finally:
                temporary_path.unlink(missing_ok=True)
            return target_url
        except Exception:
            LOGGER.warning(
                "Не удалось сохранить изображение Telegram для сообщения %s.",
                message_id,
            )
            return ""

    async def _media_url(
        self,
        client: Any,
        message: Any,
        media_type: str,
        channel_username: str,
    ) -> str:
        resolver = getattr(client, "get_media_url", None)
        if callable(resolver):
            value = await _await_if_needed(resolver(message, media_type))
            return str(value or "").strip()

        if media_type == "photo":
            return await self._download_photo(
                client,
                message,
                channel_username,
            )
        return ""

    async def _fetch_posts(
        self,
        channel_username: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[dict[str, Any]]:
        client = None

        try:
            client = self._client_factory(
                self._api_id,
                self._api_hash,
                self._session_string,
                self._session_name,
            )
            await _await_if_needed(client.connect())

            authorization_check = getattr(client, "is_user_authorized", None)
            if callable(authorization_check):
                is_authorized = await _await_if_needed(authorization_check())
                if not is_authorized:
                    raise TelegramParserError(
                        "Telegram-сессия не авторизована."
                    )

            entity = await _await_if_needed(client.get_entity(channel_username))
            entity_username = str(
                getattr(entity, "username", None) or channel_username
            ).strip().lstrip("@")
            result = []
            seen_message_ids = set()
            end_offset_date = datetime.datetime.combine(
                end_date + datetime.timedelta(days=1),
                datetime.time.min,
                tzinfo=datetime.timezone.utc,
            )

            async for message in client.iter_messages(
                entity,
                limit=None,
                offset_date=end_offset_date,
            ):
                message_id = _safe_int(getattr(message, "id", None))
                if message_id <= 0 or message_id in seen_message_ids:
                    continue

                published_at = _message_datetime(message)
                published_date = published_at.date()

                if published_date < start_date:
                    break

                if published_date > end_date:
                    continue

                seen_message_ids.add(message_id)
                post_type = get_telegram_post_type(message)
                image_url = ""
                video_url = ""

                if post_type == "Видео":
                    video_url = await self._media_url(
                        client,
                        message,
                        "video",
                        entity_username,
                    )
                elif post_type == "Фото":
                    image_url = await self._media_url(
                        client,
                        message,
                        "photo",
                        entity_username,
                    )

                result.append(
                    (
                        published_at,
                        normalize_telegram_post(
                            message,
                            entity_username,
                            image_url,
                            video_url,
                        ),
                    )
                )

            result.sort(key=lambda item: item[0], reverse=True)
            return [post for _, post in result]
        except TelegramParserError as error:
            raise TelegramParserError(
                self._safe_error_message(error)
            ) from None
        except Exception:
            raise TelegramParserError(
                "Не удалось получить публикации Telegram."
            ) from None
        finally:
            if client is not None:
                disconnect = getattr(client, "disconnect", None)
                if callable(disconnect):
                    try:
                        await _await_if_needed(disconnect())
                    except Exception:
                        pass

    def fetch_posts(
        self,
        channel: Any,
        date_start: Any,
        date_end: Any,
    ) -> list[dict[str, Any]]:
        if self._session_is_required:
            raise TelegramConfigurationError(
                "Telegram-сессия не настроена."
            )

        channel_username = normalize_telegram_channel(channel)
        start_date = parse_telegram_date(date_start, "date_start")
        end_date = parse_telegram_date(date_end, "date_end")

        if start_date > end_date:
            raise TelegramParserError(
                "Дата начала не может быть позже даты окончания."
            )

        try:
            return asyncio.run(
                self._fetch_posts(
                    channel_username,
                    start_date,
                    end_date,
                )
            )
        except TelegramParserError:
            raise
        except Exception:
            raise TelegramParserError(
                "Не удалось выполнить Telegram-парсинг."
            ) from None
