import datetime
import json
import logging
import urllib.parse
import urllib.request
from typing import Any


VK_API_BASE_URL = "https://api.vk.com/method/"
WALL_PAGE_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 15.0
COMMUNITY_TYPES = {"group", "page", "event"}
PHOTO_TYPE_ORDER = {
    "s": 1,
    "m": 2,
    "x": 3,
    "o": 4,
    "p": 5,
    "q": 6,
    "r": 7,
    "y": 8,
    "z": 9,
    "w": 10,
}
LOGGER = logging.getLogger(__name__)


class VkParserError(Exception):
    """Ошибка получения или преобразования публикаций VK."""


class VkApiError(VkParserError):
    """VK API вернул структурированную ошибку."""

    def __init__(self, error_code: Any, description: str):
        self.error_code = error_code
        self.description = description
        super().__init__(
            f"Ошибка VK API №{error_code}: {description}"
        )


class VkConfigurationError(VkParserError):
    """VK-парсер настроен некорректно."""


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _oldest_page_date(page_items: list[Any]) -> str:
    timestamps = [
        _safe_int(item.get("date"))
        for item in page_items
        if isinstance(item, dict) and _safe_int(item.get("date")) > 0
    ]
    if not timestamps:
        return "none"

    try:
        return datetime.datetime.fromtimestamp(
            min(timestamps),
            tz=datetime.timezone.utc,
        ).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return "invalid"


def parse_vk_date(value: Any, field_name: str) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()

    if isinstance(value, datetime.date):
        return value

    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            pass

    raise VkParserError(
        f"Поле {field_name} должно иметь формат YYYY-MM-DD."
    )


def extract_vk_screen_name(value: Any) -> str:
    source = str(value or "").strip()

    if not source:
        raise VkParserError("Адрес сообщества VK не указан.")

    lowered = source.casefold()
    has_scheme = lowered.startswith(("http://", "https://"))
    known_host_prefix = lowered.startswith(
        (
            "vk.com/",
            "vk.ru/",
            "www.vk.com/",
            "www.vk.ru/",
            "m.vk.com/",
            "m.vk.ru/",
        )
    )

    if has_scheme or known_host_prefix:
        parsed = urllib.parse.urlparse(
            source if has_scheme else "https://" + source
        )
        host = (parsed.hostname or "").casefold()

        if host.startswith("www.") or host.startswith("m."):
            host = host.split(".", 1)[1]

        if host not in {"vk.com", "vk.ru"}:
            raise VkParserError("Указан неподдерживаемый адрес VK.")

        screen_name = parsed.path.strip("/").split("/", 1)[0]
    else:
        if "/" in source or "://" in source:
            raise VkParserError("Указан некорректный адрес VK.")

        screen_name = source.split("?", 1)[0].split("#", 1)[0]

    screen_name = urllib.parse.unquote(screen_name).strip()

    if not screen_name or any(character.isspace() for character in screen_name):
        raise VkParserError(
            "Не удалось определить короткое имя сообщества VK."
        )

    wall_name = screen_name.casefold()
    if wall_name.startswith("wall"):
        wall_owner = wall_name[4:].split("_", 1)[0]
        if wall_owner.startswith("-") and wall_owner[1:].isdigit():
            return wall_owner

    return screen_name


def _direct_owner_id(screen_name: str) -> int | None:
    if screen_name.startswith("-") and screen_name[1:].isdigit():
        owner_id = int(screen_name)
        return owner_id if owner_id < 0 else None

    lowered = screen_name.casefold()
    for prefix in ("public", "club", "event"):
        object_id = lowered.removeprefix(prefix)
        if object_id != lowered and object_id.isdigit():
            numeric_id = int(object_id)
            return -numeric_id if numeric_id > 0 else None

    return None


def _first_nonempty_paragraph(text: str) -> str:
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


def _post_attachments(post: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = post.get("attachments")

    if not isinstance(attachments, list):
        return []

    return [
        attachment
        for attachment in attachments
        if isinstance(attachment, dict)
    ]


def _photo_attachments(
    post: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        attachment["photo"]
        for attachment in _post_attachments(post)
        if attachment.get("type") == "photo"
        and isinstance(attachment.get("photo"), dict)
    ]


def _video_attachments(
    post: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        attachment["video"]
        for attachment in _post_attachments(post)
        if attachment.get("type") == "video"
        and isinstance(attachment.get("video"), dict)
    ]


def get_vk_post_type(post: dict[str, Any]) -> str:
    if _video_attachments(post):
        return "Видео и текст"

    photo_count = len(_photo_attachments(post))

    if photo_count >= 2:
        return "Карусель и текст"

    if photo_count == 1:
        return "Текст с картинкой"

    return "Текст"


def get_largest_photo_url(photo: dict[str, Any]) -> str:
    sizes = photo.get("sizes")

    if not isinstance(sizes, list):
        return ""

    available = [
        size
        for size in sizes
        if isinstance(size, dict) and str(size.get("url") or "")
    ]

    if not available:
        return ""

    def size_key(size: dict[str, Any]) -> tuple[int, int, int, int]:
        width = max(0, _safe_int(size.get("width")))
        height = max(0, _safe_int(size.get("height")))
        type_rank = PHOTO_TYPE_ORDER.get(
            str(size.get("type") or "").casefold(),
            0,
        )
        return width * height, width, height, type_rank

    largest = max(available, key=size_key)
    return str(largest.get("url") or "")


def get_vk_post_image_url(post: dict[str, Any]) -> str:
    photos = _photo_attachments(post)
    return get_largest_photo_url(photos[0]) if photos else ""


def get_vk_video_description(post: dict[str, Any]) -> str:
    videos = _video_attachments(post)
    return str(videos[0].get("description") or "") if videos else ""


def _counter_value(post: dict[str, Any], field_name: str) -> int:
    counter = post.get(field_name)

    if not isinstance(counter, dict):
        return 0

    return max(0, _safe_int(counter.get("count")))


def _post_identity(
    post: dict[str, Any],
    fallback_owner_id: int | None = None,
) -> tuple[int, int]:
    owner_id = _safe_int(post.get("owner_id"), fallback_owner_id or 0)
    post_id = _safe_int(post.get("id"))

    if not owner_id or not post_id:
        raise VkParserError(
            "VK вернул публикацию без корректного идентификатора."
        )

    return owner_id, post_id


def normalize_vk_post(
    post: dict[str, Any],
    fallback_owner_id: int | None = None,
) -> dict[str, Any]:
    if not isinstance(post, dict):
        raise VkParserError("VK вернул некорректную публикацию.")

    owner_id, post_id = _post_identity(post, fallback_owner_id)
    timestamp = _safe_int(post.get("date"))

    if timestamp <= 0:
        raise VkParserError("VK вернул публикацию без корректной даты.")

    try:
        published_at = datetime.datetime.fromtimestamp(
            timestamp,
            tz=datetime.timezone.utc,
        ).isoformat()
    except (OverflowError, OSError, ValueError) as error:
        raise VkParserError(
            "VK вернул публикацию с некорректной датой."
        ) from error

    text = str(post.get("text") or "")

    return {
        "source": "vk",
        "external_id": f"{owner_id}_{post_id}",
        "url": f"https://vk.com/wall{owner_id}_{post_id}",
        "published_at": published_at,
        "text": text,
        "first_paragraph": _first_nonempty_paragraph(text),
        "post_type": get_vk_post_type(post),
        "image_url": get_vk_post_image_url(post),
        "video_description": get_vk_video_description(post),
        "views": _counter_value(post, "views"),
        "likes": _counter_value(post, "likes"),
        "comments": _counter_value(post, "comments"),
    }


def _default_transport(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class VkParser:
    def __init__(
        self,
        access_token: Any,
        api_version: str = "5.199",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Any = None,
    ):
        token = str(access_token or "").strip()

        if not token:
            raise VkConfigurationError("Токен VK не настроен.")

        try:
            configured_timeout = float(timeout)
        except (TypeError, ValueError) as error:
            raise VkConfigurationError(
                "Таймаут VK должен быть положительным числом."
            ) from error

        if configured_timeout <= 0:
            raise VkConfigurationError(
                "Таймаут VK должен быть положительным числом."
            )

        self._access_token = token
        self.api_version = str(api_version or "5.199")
        self.timeout = configured_timeout
        self._transport = transport or _default_transport

        if not callable(self._transport) and not callable(
            getattr(self._transport, "request", None)
        ):
            raise VkConfigurationError(
                "Транспорт VK должен быть функцией или объектом с request()."
            )

    def _safe_api_description(self, value: Any) -> str:
        description = " ".join(str(value or "").split())
        description = description.replace(
            self._access_token,
            "[скрыто]",
        )
        return description[:500] or "неизвестная ошибка"

    def _api_call(
        self,
        method: str,
        parameters: dict[str, Any],
    ) -> Any:
        request_parameters = dict(parameters)
        request_parameters["access_token"] = self._access_token
        request_parameters["v"] = self.api_version
        query = urllib.parse.urlencode(request_parameters)
        url = VK_API_BASE_URL + method + "?" + query

        try:
            if callable(self._transport):
                raw_response = self._transport(url, self.timeout)
            else:
                raw_response = self._transport.request(url, self.timeout)
        except Exception:
            raise VkParserError(
                "Не удалось выполнить запрос к VK API."
            ) from None

        if isinstance(raw_response, dict):
            data = raw_response
        else:
            if isinstance(raw_response, bytes):
                try:
                    response_text = raw_response.decode("utf-8")
                except UnicodeDecodeError:
                    raise VkParserError(
                        "VK вернул некорректный JSON."
                    ) from None
            elif isinstance(raw_response, str):
                response_text = raw_response
            else:
                raise VkParserError("VK вернул некорректный JSON.")

            try:
                data = json.loads(response_text)
            except (TypeError, ValueError):
                raise VkParserError(
                    "VK вернул некорректный JSON."
                ) from None

        if not isinstance(data, dict):
            raise VkParserError("VK вернул некорректный ответ.")

        error = data.get("error")
        if isinstance(error, dict):
            error_code = error.get("error_code", "неизвестен")
            description = self._safe_api_description(
                error.get("error_msg")
            )
            raise VkApiError(error_code, description)

        if "response" not in data:
            raise VkParserError("VK вернул некорректный ответ.")

        return data["response"]

    def resolve_owner_id(self, group_url: Any) -> int:
        screen_name = extract_vk_screen_name(group_url)
        direct_owner_id = _direct_owner_id(screen_name)

        if direct_owner_id is not None:
            return direct_owner_id

        response = self._api_call(
            "utils.resolveScreenName",
            {"screen_name": screen_name},
        )

        if not isinstance(response, dict):
            raise VkParserError(
                "Не удалось определить сообщество VK."
            )

        object_id = _safe_int(response.get("object_id"))
        object_type = str(response.get("type") or "")

        if object_id <= 0:
            raise VkParserError(
                "Не удалось определить сообщество VK."
            )

        if object_type and object_type not in COMMUNITY_TYPES:
            raise VkParserError(
                "Указанный адрес ведёт не на сообщество VK."
            )

        return -abs(object_id)

    def fetch_posts(
        self,
        group_url: Any,
        date_start: Any,
        date_end: Any,
    ) -> list[dict[str, Any]]:
        start_date = parse_vk_date(date_start, "date_start")
        end_date = parse_vk_date(date_end, "date_end")

        if start_date > end_date:
            raise VkParserError(
                "Дата начала не может быть позже даты окончания."
            )

        start_timestamp = int(
            datetime.datetime.combine(
                start_date,
                datetime.time.min,
                tzinfo=datetime.timezone.utc,
            ).timestamp()
        )
        end_timestamp = int(
            datetime.datetime.combine(
                end_date,
                datetime.time.max,
                tzinfo=datetime.timezone.utc,
            ).timestamp()
        )
        owner_id = self.resolve_owner_id(group_url)
        offset = 0
        seen_posts: set[tuple[int, int]] = set()
        result: list[tuple[int, dict[str, Any]]] = []

        while True:
            response = self._api_call(
                "wall.get",
                {
                    "owner_id": owner_id,
                    "count": WALL_PAGE_SIZE,
                    "offset": offset,
                    "filter": "owner",
                },
            )

            if not isinstance(response, dict) or not isinstance(
                response.get("items"),
                list,
            ):
                raise VkParserError(
                    "VK не вернул список публикаций."
                )

            page_items = response["items"]
            response_count = _safe_int(response.get("count"), -1)
            LOGGER.info(
                "VK pagination: offset=%d items=%d response_count=%d "
                "oldest_date=%s",
                offset,
                len(page_items),
                response_count,
                _oldest_page_date(page_items),
            )
            if not page_items:
                break

            regular_timestamps = []

            for post in page_items:
                if not isinstance(post, dict):
                    raise VkParserError(
                        "VK вернул некорректную публикацию."
                    )

                timestamp = _safe_int(post.get("date"))
                is_pinned = _safe_int(post.get("is_pinned")) == 1

                if timestamp > 0 and not is_pinned:
                    regular_timestamps.append(timestamp)

                identity = _post_identity(post, owner_id)
                if identity in seen_posts:
                    continue

                seen_posts.add(identity)

                if timestamp < start_timestamp or timestamp > end_timestamp:
                    continue

                result.append(
                    (
                        timestamp,
                        normalize_vk_post(post, owner_id),
                    )
                )

            offset += WALL_PAGE_SIZE

            reached_start_boundary = any(
                timestamp < start_timestamp
                for timestamp in regular_timestamps
            )

            if reached_start_boundary:
                break

            if response_count >= 0 and offset >= response_count:
                break

        result.sort(key=lambda item: item[0], reverse=True)
        return [post for _, post in result]
