import datetime
import json
import logging
import urllib.parse
import urllib.error
import urllib.request
from typing import Any


GRAPH_API_BASE_URL = "https://graph.instagram.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
MEDIA_FIELDS = ",".join(
    (
        "id",
        "caption",
        "media_type",
        "media_url",
        "thumbnail_url",
        "permalink",
        "timestamp",
        "like_count",
        "comments_count",
    )
)
INSIGHT_METRICS = ("views", "reach", "saved", "shares")
INSIGHTS_PERMISSION = "instagram_business_manage_insights"
INSIGHTS_UNAVAILABLE_WARNING = (
    "Instagram Insights unavailable: missing " + INSIGHTS_PERMISSION
)


logger = logging.getLogger(__name__)


class InstagramParserError(Exception):
    """Ошибка получения или преобразования публикаций Instagram."""


class InstagramApiError(InstagramParserError):
    """Instagram API вернул структурированную ошибку."""

    def __init__(self, error_code: Any, description: str):
        self.error_code = error_code
        self.description = description
        super().__init__(
            f"Ошибка Instagram API №{error_code}: {description}"
        )


class InstagramConfigurationError(InstagramParserError):
    """Instagram-парсер настроен некорректно."""


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


def parse_instagram_date(value: Any, field_name: str) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()

    if isinstance(value, datetime.date):
        return value

    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            pass

    raise InstagramParserError(
        f"Поле {field_name} должно иметь формат YYYY-MM-DD."
    )


def parse_instagram_timestamp(value: Any) -> datetime.datetime:
    normalized = str(value or "").strip()

    if not normalized:
        raise InstagramParserError(
            "Instagram вернул публикацию без корректной даты."
        )

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        published_at = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        raise InstagramParserError(
            "Instagram вернул публикацию с некорректной датой."
        ) from None

    if published_at.tzinfo is None:
        published_at = published_at.replace(
            tzinfo=datetime.timezone.utc
        )

    return published_at.astimezone(datetime.timezone.utc)


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


def get_instagram_post_type(media_item: dict[str, Any]) -> str:
    media_type = str(
        media_item.get("media_type") or ""
    ).strip().upper()

    return {
        "IMAGE": "Фото",
        "CAROUSEL_ALBUM": "Карусель",
        "VIDEO": "Видео",
    }.get(media_type, "Другое")


def _child_media_url(child: Any) -> str:
    if not isinstance(child, dict):
        return ""

    media_type = str(child.get("media_type") or "").upper()
    media_url = str(child.get("media_url") or "").strip()
    thumbnail_url = str(
        child.get("thumbnail_url") or ""
    ).strip()

    if media_type == "VIDEO":
        return thumbnail_url or media_url

    return media_url or thumbnail_url


def get_instagram_image_url(
    media_item: dict[str, Any],
    carousel_image_url: str = "",
) -> str:
    media_type = str(
        media_item.get("media_type") or ""
    ).strip().upper()
    media_url = str(media_item.get("media_url") or "").strip()
    thumbnail_url = str(
        media_item.get("thumbnail_url") or ""
    ).strip()

    if media_type == "IMAGE":
        return media_url

    if media_type == "VIDEO":
        return thumbnail_url or media_url

    if media_type == "CAROUSEL_ALBUM":
        if carousel_image_url:
            return carousel_image_url

        children = media_item.get("children")
        if isinstance(children, dict):
            children = children.get("data")

        if isinstance(children, list) and children:
            return _child_media_url(children[0]) or media_url

        return media_url

    return ""


def normalize_instagram_post(
    media_item: dict[str, Any],
    insights: dict[str, int | None] | None = None,
    carousel_image_url: str = "",
) -> dict[str, Any]:
    if not isinstance(media_item, dict):
        raise InstagramParserError(
            "Instagram вернул некорректную публикацию."
        )

    media_id = str(media_item.get("id") or "").strip()
    if not media_id:
        raise InstagramParserError(
            "Instagram вернул публикацию без идентификатора."
        )

    published_at = parse_instagram_timestamp(
        media_item.get("timestamp")
    )
    caption = str(media_item.get("caption") or "")
    insight_values = insights if insights is not None else {}

    return {
        "source": "instagram",
        "external_id": media_id,
        "url": str(media_item.get("permalink") or "").strip(),
        "published_at": published_at.isoformat(),
        "text": caption,
        "first_paragraph": first_nonempty_paragraph(caption),
        "post_type": get_instagram_post_type(media_item),
        "image_url": get_instagram_image_url(
            media_item,
            carousel_image_url,
        ),
        "views": _optional_nonnegative_int(
            insight_values.get("views")
        ),
        "reach": _optional_nonnegative_int(
            insight_values.get("reach")
        ),
        "likes": max(0, _safe_int(media_item.get("like_count"))),
        "comments": max(
            0,
            _safe_int(media_item.get("comments_count")),
        ),
        "saved": _optional_nonnegative_int(
            insight_values.get("saved")
        ),
        "shares": _optional_nonnegative_int(
            insight_values.get("shares")
        ),
    }


def _default_transport(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            return error.read()
        raise


class InstagramParser:
    def __init__(
        self,
        access_token: Any,
        api_version: str = "v22.0",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Any = None,
    ):
        token = str(access_token or "").strip()

        if not token:
            raise InstagramConfigurationError(
                "Токен Instagram не настроен."
            )

        try:
            configured_timeout = float(timeout)
        except (TypeError, ValueError) as error:
            raise InstagramConfigurationError(
                "Таймаут Instagram должен быть положительным числом."
            ) from error

        if configured_timeout <= 0:
            raise InstagramConfigurationError(
                "Таймаут Instagram должен быть положительным числом."
            )

        self._access_token = token
        self.api_version = str(api_version or "v22.0").strip("/")
        self.timeout = configured_timeout
        self._transport = transport or _default_transport
        self.warning = ""

        if not callable(self._transport) and not callable(
            getattr(self._transport, "request", None)
        ):
            raise InstagramConfigurationError(
                "Транспорт Instagram должен быть функцией "
                "или объектом с request()."
            )

    def _safe_api_description(self, value: Any) -> str:
        description = " ".join(str(value or "").split())
        description = description.replace(
            self._access_token,
            "[скрыто]",
        )
        return description[:500] or "неизвестная ошибка"

    def _build_url(
        self,
        endpoint: str,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        endpoint = str(endpoint or "").strip()

        if endpoint.startswith(("https://", "http://")):
            parsed = urllib.parse.urlsplit(endpoint)
            query_items = urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            query_parameters = {
                key: value
                for key, value in query_items
                if key != "access_token"
            }
            base_url = urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    "",
                    parsed.fragment,
                )
            )
        else:
            query_parameters = {}
            base_url = (
                f"{GRAPH_API_BASE_URL}/{self.api_version}/"
                + endpoint.lstrip("/")
            )

        query_parameters.update(parameters or {})
        query_parameters["access_token"] = self._access_token
        return base_url + "?" + urllib.parse.urlencode(query_parameters)

    def _api_call(
        self,
        endpoint: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._build_url(endpoint, parameters)

        try:
            if callable(self._transport):
                raw_response = self._transport(url, self.timeout)
            else:
                raw_response = self._transport.request(url, self.timeout)
        except Exception:
            raise InstagramParserError(
                "Не удалось выполнить запрос к Instagram API."
            ) from None

        if isinstance(raw_response, dict):
            data = raw_response
        else:
            if isinstance(raw_response, bytes):
                try:
                    response_text = raw_response.decode("utf-8")
                except UnicodeDecodeError:
                    raise InstagramParserError(
                        "Instagram вернул некорректный JSON."
                    ) from None
            elif isinstance(raw_response, str):
                response_text = raw_response
            else:
                raise InstagramParserError(
                    "Instagram вернул некорректный JSON."
                )

            try:
                data = json.loads(response_text)
            except (TypeError, ValueError):
                raise InstagramParserError(
                    "Instagram вернул некорректный JSON."
                ) from None

        if not isinstance(data, dict):
            raise InstagramParserError(
                "Instagram вернул некорректный ответ."
            )

        error = data.get("error")
        if isinstance(error, dict):
            error_code = error.get("code", "неизвестен")
            description = self._safe_api_description(
                error.get("message")
            )
            raise InstagramApiError(error_code, description)

        return data

    def fetch_insights(self, media_id: Any) -> dict[str, int | None]:
        normalized_media_id = str(media_id or "").strip()
        if not normalized_media_id:
            raise InstagramParserError(
                "Идентификатор публикации Instagram не указан."
            )

        data = self._api_call(
            "/"
            + urllib.parse.quote(normalized_media_id, safe="")
            + "/insights",
            {"metric": ",".join(INSIGHT_METRICS)},
        )
        metrics = {name: None for name in INSIGHT_METRICS}
        items = data.get("data")

        if not isinstance(items, list):
            return metrics

        for item in items:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name") or "")
            if name not in metrics:
                continue

            value = item.get("value")
            values = item.get("values")
            if isinstance(values, list) and values:
                first_value = values[0]
                if isinstance(first_value, dict):
                    value = first_value.get("value", value)

            metrics[name] = max(0, _safe_int(value))

        return metrics

    @staticmethod
    def _is_missing_insights_permission(
        error: InstagramApiError,
    ) -> bool:
        description = str(error.description or "").casefold()
        error_code = str(error.error_code or "").strip()

        if INSIGHTS_PERMISSION in description:
            return True

        permission_marker = any(
            marker in description
            for marker in (
                "permission",
                "permissions",
                "not authorized",
                "does not have",
            )
        )
        return error_code in {"10", "200"} and permission_marker

    def _fetch_carousel_image(self, media_id: str) -> str:
        data = self._api_call(
            "/" + urllib.parse.quote(media_id, safe="") + "/children",
            {
                "fields": (
                    "id,media_type,media_url,thumbnail_url"
                )
            },
        )
        children = data.get("data")

        if not isinstance(children, list) or not children:
            return ""

        return _child_media_url(children[0])

    def fetch_posts(
        self,
        account_id: Any,
        date_start: Any,
        date_end: Any,
    ) -> list[dict[str, Any]]:
        self.warning = ""
        insights_available = True
        normalized_account_id = str(account_id or "").strip()
        if not normalized_account_id:
            raise InstagramParserError(
                "Instagram Business Account ID не указан."
            )

        start_date = parse_instagram_date(date_start, "date_start")
        end_date = parse_instagram_date(date_end, "date_end")

        if start_date > end_date:
            raise InstagramParserError(
                "Дата начала не может быть позже даты окончания."
            )

        page = self._api_call(
            "/me/media",
            {"fields": MEDIA_FIELDS},
        )
        result: list[tuple[datetime.datetime, dict[str, Any]]] = []
        seen_media_ids = set()
        used_page_markers = set()

        while True:
            items = page.get("data")
            if not isinstance(items, list):
                raise InstagramParserError(
                    "Instagram не вернул список публикаций."
                )

            reached_start_boundary = False

            for media_item in items:
                if not isinstance(media_item, dict):
                    raise InstagramParserError(
                        "Instagram вернул некорректную публикацию."
                    )

                published_at = parse_instagram_timestamp(
                    media_item.get("timestamp")
                )
                published_date = published_at.date()

                if published_date < start_date:
                    reached_start_boundary = True
                    continue

                if published_date > end_date:
                    continue

                media_id = str(media_item.get("id") or "").strip()
                if not media_id:
                    raise InstagramParserError(
                        "Instagram вернул публикацию без идентификатора."
                    )

                if media_id in seen_media_ids:
                    continue

                seen_media_ids.add(media_id)
                carousel_image_url = ""

                if str(
                    media_item.get("media_type") or ""
                ).upper() == "CAROUSEL_ALBUM":
                    carousel_image_url = self._fetch_carousel_image(
                        media_id
                    )

                insights = None
                if insights_available:
                    try:
                        insights = self.fetch_insights(media_id)
                    except InstagramApiError as error:
                        if not self._is_missing_insights_permission(error):
                            raise

                        insights_available = False
                        self.warning = INSIGHTS_UNAVAILABLE_WARNING
                        logger.warning(self.warning)
                normalized_post = normalize_instagram_post(
                    media_item,
                    insights,
                    carousel_image_url,
                )
                result.append((published_at, normalized_post))

            if reached_start_boundary:
                break

            paging = page.get("paging")
            if not isinstance(paging, dict):
                break

            next_url = str(paging.get("next") or "").strip()
            cursors = paging.get("cursors")
            cursor = ""

            if isinstance(cursors, dict):
                cursor = str(cursors.get("next") or "").strip()

            if next_url:
                page_marker = "url:" + next_url
                next_endpoint = next_url
                next_parameters = None
            elif cursor:
                page_marker = "cursor:" + cursor
                next_endpoint = "/me/media"
                next_parameters = {
                    "fields": MEDIA_FIELDS,
                    "after": cursor,
                }
            else:
                break

            if page_marker in used_page_markers:
                break

            used_page_markers.add(page_marker)
            page = self._api_call(
                next_endpoint,
                next_parameters,
            )

        result.sort(key=lambda item: item[0], reverse=True)
        return [post for _, post in result]
