import asyncio
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from telethon import TelegramClient
from telethon.tl.custom.message import Message


# ============================================================
# TELEGRAM
# ============================================================

API_ID = int(
    os.environ.get(
        "TELEGRAM_API_ID",
        "0"
    )
)

API_HASH = os.environ.get(
    "TELEGRAM_API_HASH",
    ""
).strip()

SESSION_NAME = os.environ.get(
    "TELEGRAM_SESSION_NAME",
    "telegram_parser"
).strip()

# ============================================================
# INSTAGRAM
# ============================================================

INSTAGRAM_APP_ID = os.environ.get(
    "INSTAGRAM_APP_ID",
    ""
).strip()

INSTAGRAM_APP_SECRET = os.environ.get(
    "INSTAGRAM_APP_SECRET",
    ""
).strip()

INSTAGRAM_REDIRECT_URI = os.environ.get(
    "INSTAGRAM_REDIRECT_URI",
    ""
).strip()

INSTAGRAM_SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_insights"
]

INSTAGRAM_TOKEN_FILE = (
    Path(__file__).resolve().parent
    / "instagram_token.json"
)

def instagram_api_get(endpoint, params=None):
    if not INSTAGRAM_TOKEN_FILE.exists():
        raise RuntimeError(
            "Instagram token file does not exist"
        )

    token_data = json.loads(
        INSTAGRAM_TOKEN_FILE.read_text(
            encoding="utf-8"
        )
    )

    access_token = token_data.get(
        "access_token",
        ""
    ).strip()

    if not access_token:
        raise RuntimeError(
            "Instagram access token is missing"
        )

    query_params = dict(params or {})
    query_params["access_token"] = access_token

    if endpoint.startswith("https://"):
        url = endpoint
        separator = "&" if "?" in url else "?"
        url += separator + urllib.parse.urlencode(
            query_params
        )
    else:
        url = (
            "https://graph.instagram.com/"
            + endpoint.lstrip("/")
            + "?"
            + urllib.parse.urlencode(query_params)
        )

    request_object = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "TelegramInstagramParser/1.0",
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request_object,
        timeout=60
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )

def parse_instagram_datetime(value):
    if not value:
        return None

    normalized = str(value).strip()

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.strptime(
            normalized,
            "%Y-%m-%dT%H:%M:%S%z"
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(timezone.utc)

def instagram_get_children(media_id):
    if not media_id:
        return []

    try:
        result = instagram_api_get(
            f"{media_id}/children",
            {
                "fields": (
                    "id,media_type,media_url,"
                    "thumbnail_url,permalink"
                )
            }
        )
        return result.get("data", []) or []
    except Exception:
        return []


def instagram_get_post_type(media_item):
    media_type = (
        media_item.get("media_type", "")
        .strip()
        .upper()
    )

    if media_type == "CAROUSEL_ALBUM":
        return "Карусель и текст"

    if media_type == "VIDEO":
        return "Видео и текст"

    return "Текст с картинкой"


def instagram_get_preview_image(media_item):
    media_type = (
        media_item.get("media_type", "")
        .strip()
        .upper()
    )

    media_url = (media_item.get("media_url") or "").strip()
    thumbnail_url = (
        media_item.get("thumbnail_url") or ""
    ).strip()

    if media_type == "IMAGE":
        return media_url, 1

    if media_type == "VIDEO":
        return (thumbnail_url or media_url), 1

    if media_type == "CAROUSEL_ALBUM":
        children = instagram_get_children(
            media_item.get("id", "")
        )

        if not children:
            return "", 0

        first = children[0]
        first_type = (
            first.get("media_type", "")
            .strip()
            .upper()
        )
        first_url = (first.get("media_url") or "").strip()
        first_thumb = (
            first.get("thumbnail_url") or ""
        ).strip()

        if first_type == "VIDEO":
            return (first_thumb or first_url), len(children)

        return (first_url or first_thumb), len(children)

    return (media_url or thumbnail_url), 1



def collect_instagram_posts(
    start_date,
    end_date,
    advertising_types: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Получает публикации подключённого Instagram-аккаунта
    за указанный период включительно.

    Пагинация продолжается, пока публикации не закончатся
    либо пока не будет достигнута дата раньше date_start.
    """
    profile = instagram_api_get(
        "me",
        {
            "fields": (
                "id,user_id,username,name,"
                "account_type,media_count"
            )
        }
    )

    fields = (
        "id,caption,media_type,media_product_type,"
        "media_url,thumbnail_url,permalink,timestamp,"
        "username,like_count,comments_count"
    )

    page = instagram_api_get(
        "me/media",
        {
            "fields": fields,
            "limit": 100
        }
    )

    posts: list[dict[str, Any]] = []
    stop_pagination = False

    while True:
        for media_item in page.get("data", []) or []:
            published_at = parse_instagram_datetime(
                media_item.get("timestamp")
            )

            if published_at is None:
                continue

            published_date = published_at.date()

            if published_date < start_date:
                stop_pagination = True
                break

            if published_date > end_date:
                continue

            caption = str(
                media_item.get("caption") or ""
            ).strip()

            image_url, media_items_count = (
                instagram_get_preview_image(
                    media_item
                )
            )

            likes_count = int(
                media_item.get("like_count") or 0
            )

            comments_count = int(
                media_item.get("comments_count") or 0
            )

            posts.append({
                "post_url": str(
                    media_item.get("permalink") or ""
                ).strip(),

                "date": published_at.isoformat(),

                "text": caption,

                "image_url": image_url,

                # Instagram API не предоставляет единое число
                # просмотров для всех типов публикаций.
                "views": 0,

                # Для совместимости с Telegram-парсером
                # лайки записываются в поле reactions.
                "reactions": likes_count,

                "comments": comments_count,

                "post_type": instagram_get_post_type(
                    media_item
                ),

                "advertising_type":
                    get_advertising_type(
                        caption,
                        advertising_types
                    ),

                "instagram_media_id": str(
                    media_item.get("id") or ""
                ),

                "instagram_media_type": str(
                    media_item.get("media_type") or ""
                ),

                "instagram_media_product_type": str(
                    media_item.get(
                        "media_product_type"
                    ) or ""
                ),

                "instagram_username": str(
                    media_item.get("username")
                    or profile.get("username")
                    or ""
                ),

                "media_items_count":
                    media_items_count,

                "likes": likes_count
            })

        if stop_pagination:
            break

        next_url = (
            page.get("paging", {})
            .get("next")
        )

        if not next_url:
            break

        # В ссылке next уже находится access_token.
        # Удаляем его, чтобы instagram_api_get добавил
        # актуальный токен только один раз.
        parsed_url = urllib.parse.urlsplit(
            next_url
        )

        next_query = urllib.parse.parse_qsl(
            parsed_url.query,
            keep_blank_values=True
        )

        next_query = [
            (key, value)
            for key, value in next_query
            if key != "access_token"
        ]

        clean_next_url = urllib.parse.urlunsplit((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            urllib.parse.urlencode(next_query),
            parsed_url.fragment
        ))

        page = instagram_api_get(
            clean_next_url
        )

    posts.sort(
        key=lambda item: item["date"],
        reverse=True
    )

    return profile, posts


def parse_instagram_account(
    payload: dict[str, Any]
) -> dict[str, Any]:
    date_start_text = str(
        payload.get("date_start", "")
    ).strip()

    date_end_text = str(
        payload.get("date_end", "")
    ).strip()

    advertising_types = payload.get(
        "advertising_types",
        []
    )

    if not date_start_text:
        raise ValueError(
            "Не указана дата начала."
        )

    if not date_end_text:
        raise ValueError(
            "Не указана дата окончания."
        )

    if not isinstance(
        advertising_types,
        list
    ):
        raise ValueError(
            "advertising_types должен быть массивом."
        )

    start_date = parse_date(
        date_start_text
    )

    end_date = parse_date(
        date_end_text
    )

    if start_date > end_date:
        raise ValueError(
            "Дата начала не может быть "
            "позже даты окончания."
        )

    profile, posts = collect_instagram_posts(
        start_date,
        end_date,
        advertising_types
    )

    return {
        "success": True,
        "account_id": str(
            profile.get("id") or ""
        ),
        "instagram_user_id": str(
            profile.get("user_id") or ""
        ),
        "account_name": str(
            profile.get("name") or ""
        ),
        "account_username": str(
            profile.get("username") or ""
        ),
        "account_type": str(
            profile.get("account_type") or ""
        ),
        "date_start": date_start_text,
        "date_end": date_end_text,
        "posts_count": len(posts),
        "posts": posts
    }


# ============================================================
# ЗАЩИТА API
# ============================================================

# Придумайте длинный случайный ключ.
# Позже этот же ключ сохраним в Apps Script.
#
# Пример формата:
# Ключ API берётся из переменной окружения API_ACCESS_KEY.
API_ACCESS_KEY = os.environ.get(
    "API_ACCESS_KEY",
    ""
).strip()


# ============================================================
# ФАЙЛЫ
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "api_media"

MEDIA_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# ОБЩИЕ ФУНКЦИИ
# ============================================================

def parse_date(value: str):
    """Преобразует YYYY-MM-DD в дату."""
    return datetime.strptime(
        value,
        "%Y-%m-%d"
    ).date()


def normalize_text(value: str) -> str:
    """
    Нормализует строку для поиска:
    — нижний регистр;
    — ё → е;
    — знаки препинания → пробелы.
    """
    text = (
        str(value or "")
        .lower()
        .replace("ё", "е")
    )

    text = re.sub(
        r"[^a-zа-я0-9]+",
        " ",
        text,
        flags=re.IGNORECASE
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def contains_phrase(
    normalized_text: str,
    phrase: str
) -> bool:
    """
    Ищет целое слово или фразу.

    Например:
    — слово шаг;
    — clck;
    — любовь.
    """
    normalized_phrase = normalize_text(
        phrase
    )

    if (
        not normalized_text
        or not normalized_phrase
    ):
        return False

    return (
        f" {normalized_phrase} "
        in f" {normalized_text} "
    )


def normalize_words(value: Any) -> list[str]:
    """
    Принимает массив либо строку через запятую.
    Возвращает очищенный список без повторов.
    """
    if isinstance(value, list):
        source = value
    else:
        source = str(value or "").split(",")

    result: list[str] = []
    used: set[str] = set()

    for item in source:
        cleaned = re.sub(
            r"\s+",
            " ",
            str(item or "").strip()
        )

        if not cleaned:
            continue

        normalized = normalize_text(cleaned)

        if (
            not normalized
            or normalized in used
        ):
            continue

        used.add(normalized)
        result.append(cleaned)

    return result


def get_advertising_type(
    text: str,
    advertising_types: list[dict[str, Any]]
) -> str:
    """
    Telegram использует только поле postWords.

    Правила проверяются сверху вниз.
    Возвращается первый найденный тип.
    """
    normalized_text = normalize_text(text)

    for rule in advertising_types:
        type_name = str(
            rule.get("type", "")
        ).strip()

        if not type_name:
            continue

        words = normalize_words(
            rule.get("postWords", [])
        )

        found = any(
            contains_phrase(
                normalized_text,
                word
            )
            for word in words
        )

        if found:
            return type_name

    return ""


def get_reactions_count(
    message: Message
) -> int:
    """Суммирует все реакции."""
    reactions = getattr(
        message,
        "reactions",
        None
    )

    results = getattr(
        reactions,
        "results",
        None
    )

    if not results:
        return 0

    return sum(
        int(
            getattr(item, "count", 0)
            or 0
        )
        for item in results
    )


def get_comments_count(
    message: Message
) -> int:
    """Получает число комментариев."""
    replies = getattr(
        message,
        "replies",
        None
    )

    if not replies:
        return 0

    return int(
        getattr(
            replies,
            "replies",
            0
        )
        or 0
    )


def is_photo_message(
    message: Message
) -> bool:
    return message.photo is not None


def is_video_message(
    message: Message
) -> bool:
    if message.video is not None:
        return True

    document = message.document

    if not document:
        return False

    mime_type = str(
        getattr(
            document,
            "mime_type",
            ""
        )
        or ""
    )

    return mime_type.startswith(
        "video/"
    )


def determine_post_type(
    messages: list[Message]
) -> str:
    """
    Определяет тип Telegram-публикации.
    """
    photos_count = sum(
        1
        for message in messages
        if is_photo_message(message)
    )

    has_video = any(
        is_video_message(message)
        for message in messages
    )

    if has_video:
        return "Видео и текст"

    if photos_count >= 2:
        return "Карусель и текст"

    if photos_count == 1:
        return "Текст с картинкой"

    return "Текст"


def get_main_message(
    messages: list[Message]
) -> Message:
    """
    Основным считается сообщение,
    содержащее текст.
    """
    for message in messages:
        if str(
            message.message or ""
        ).strip():
            return message

    return messages[0]


def get_post_text(
    messages: list[Message]
) -> str:
    """Собирает полный текст публикации."""
    text_parts: list[str] = []

    for message in messages:
        text = str(
            message.message or ""
        ).strip()

        if (
            text
            and text not in text_parts
        ):
            text_parts.append(text)

    return "\n\n".join(text_parts)


def group_messages(
    messages: list[Message]
) -> list[list[Message]]:
    """
    Объединяет элементы Telegram-альбома
    с одинаковым grouped_id.
    """
    grouped: dict[
        str,
        list[Message]
    ] = defaultdict(list)

    for message in messages:
        if message.grouped_id:
            key = (
                "album_"
                + str(message.grouped_id)
            )
        else:
            key = (
                "message_"
                + str(message.id)
            )

        grouped[key].append(message)

    groups = list(
        grouped.values()
    )

    for group in groups:
        group.sort(
            key=lambda item: item.id
        )

    groups.sort(
        key=lambda group: (
            get_main_message(group).date
        ),
        reverse=True
    )

    return groups


def extract_channel_username(
    channel: Any,
    channel_url: str
) -> str:
    username = str(
        getattr(
            channel,
            "username",
            ""
        )
        or ""
    ).strip()

    if username:
        return username

    match = re.search(
        r"(?:t\.me|telegram\.me)/"
        r"([A-Za-z0-9_]+)",
        channel_url
    )

    if match:
        return match.group(1)

    raise RuntimeError(
        "Не удалось определить username канала."
    )


def build_post_link(
    username: str,
    message_id: int
) -> str:
    return (
        f"https://t.me/"
        f"{username}/"
        f"{message_id}"
    )


def get_public_base_url() -> str:
    """
    Формирует базовый URL для картинок.

    После подключения HTTPS-туннеля Flask
    получит заголовок X-Forwarded-Host.
    """
    forwarded_proto = request.headers.get(
        "X-Forwarded-Proto"
    )

    forwarded_host = request.headers.get(
        "X-Forwarded-Host"
    )

    if forwarded_host:
        protocol = (
            forwarded_proto
            or "https"
        )

        return (
            f"{protocol}://"
            f"{forwarded_host}"
        ).rstrip("/")

    return request.host_url.rstrip("/")


def check_access_key() -> bool:
    """
    Проверяет ключ в заголовке:

    X-API-Key: ...
    """
    received_key = request.headers.get(
        "X-API-Key",
        ""
    )

    return secrets.compare_digest(
        str(received_key),
        str(API_ACCESS_KEY)
    )


# ============================================================
# TELEGRAM-ПАРСИНГ
# ============================================================

async def collect_messages(
    client: TelegramClient,
    channel: Any,
    start_date,
    end_date
) -> list[Message]:
    """
    Получает сообщения за период включительно.
    """
    result: list[Message] = []

    async for message in client.iter_messages(
        channel
    ):
        if not message.date:
            continue

        message_date = (
            message.date.date()
        )

        if message_date > end_date:
            continue

        if message_date < start_date:
            break

        if getattr(
            message,
            "action",
            None
        ):
            continue

        result.append(message)

    return result


async def download_main_image(
    client: TelegramClient,
    messages: list[Message],
    file_name: str
) -> str:
    """
    Скачивает первую фотографию публикации.
    Возвращает только имя файла.
    """
    for message in messages:
        if not is_photo_message(
            message
        ):
            continue

        target_path = (
            MEDIA_DIR
            / f"{file_name}.jpg"
        )

        downloaded = (
            await client.download_media(
                message,
                file=str(target_path)
            )
        )

        if downloaded:
            return Path(
                downloaded
            ).name

    return ""


async def parse_telegram_channel(
    payload: dict[str, Any]
) -> dict[str, Any]:
    channel_url = str(
        payload.get(
            "channel_url",
            ""
        )
    ).strip()

    date_start_text = str(
        payload.get(
            "date_start",
            ""
        )
    ).strip()

    date_end_text = str(
        payload.get(
            "date_end",
            ""
        )
    ).strip()

    advertising_types = payload.get(
        "advertising_types",
        []
    )

    if not channel_url:
        raise ValueError(
            "Не указан URL Telegram-канала."
        )

    if not date_start_text:
        raise ValueError(
            "Не указана дата начала."
        )

    if not date_end_text:
        raise ValueError(
            "Не указана дата окончания."
        )

    if not isinstance(
        advertising_types,
        list
    ):
        raise ValueError(
            "advertising_types должен быть массивом."
        )

    start_date = parse_date(
        date_start_text
    )

    end_date = parse_date(
        date_end_text
    )

    if start_date > end_date:
        raise ValueError(
            "Дата начала не может быть "
            "позже даты окончания."
        )

    client = TelegramClient(
        SESSION_NAME,
        API_ID,
        API_HASH
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram-сессия "
                "не авторизована."
            )

        channel = await client.get_entity(
            channel_url
        )

        channel_title = str(
            getattr(
                channel,
                "title",
                channel_url
            )
        )

        channel_username = (
            extract_channel_username(
                channel,
                channel_url
            )
        )

        messages = await collect_messages(
            client,
            channel,
            start_date,
            end_date
        )

        message_groups = group_messages(
            messages
        )

        public_base_url = (
            get_public_base_url()
        )

        posts: list[
            dict[str, Any]
        ] = []

        for message_group in message_groups:
            main_message = (
                get_main_message(
                    message_group
                )
            )

            post_text = get_post_text(
                message_group
            )

            file_name = (
                f"{channel_username}_"
                f"{main_message.id}"
            )

            image_file_name = (
                await download_main_image(
                    client,
                    message_group,
                    file_name
                )
            )

            image_url = ""

            if image_file_name:
                image_url = (
                    f"{public_base_url}"
                    f"/media/"
                    f"{image_file_name}"
                )

            views = max(
                int(message.views or 0)
                for message in message_group
            )

            reactions = sum(
                get_reactions_count(
                    message
                )
                for message in message_group
            )

            comments = max(
                get_comments_count(
                    message
                )
                for message in message_group
            )

            posts.append({
                "post_url":
                    build_post_link(
                        channel_username,
                        main_message.id
                    ),

                "date":
                    main_message.date.isoformat(),

                "text":
                    post_text,

                "image_url":
                    image_url,

                "views":
                    views,

                "reactions":
                    reactions,

                "comments":
                    comments,

                "post_type":
                    determine_post_type(
                        message_group
                    ),

                "advertising_type":
                    get_advertising_type(
                        post_text,
                        advertising_types
                    ),

                "telegram_message_id":
                    main_message.id,

                "telegram_grouped_id":
                    (
                        str(
                            main_message.grouped_id
                        )
                        if main_message.grouped_id
                        else ""
                    )
            })

        return {
            "success": True,
            "channel_title":
                channel_title,
            "channel_username":
                channel_username,
            "date_start":
                date_start_text,
            "date_end":
                date_end_text,
            "posts_count":
                len(posts),
            "posts":
                posts
        }

    finally:
        await client.disconnect()


# ============================================================
# HTTP-МАРШРУТЫ
# ============================================================

@app.get("/health")
def health():
    """Проверка работы сервера."""
    return jsonify({
        "success": True,
        "service":
            "telegram-parser-api",
        "status":
            "running"
    })


@app.post("/parse")
def parse_channel():
    """
    Запускает Telegram-парсинг.

    Требуется заголовок:
    X-API-Key
    """
    if not check_access_key():
        return jsonify({
            "success": False,
            "error":
                "Неверный API-ключ."
        }), 401

    payload = request.get_json(
        silent=True
    )

    if not isinstance(payload, dict):
        return jsonify({
            "success": False,
            "error":
                "Тело запроса должно "
                "содержать JSON."
        }), 400

    try:
        result = asyncio.run(
            parse_telegram_channel(
                payload
            )
        )

        return jsonify(result)

    except Exception as error:
        app.logger.exception(
            "Ошибка Telegram-парсинга"
        )

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500



@app.post("/instagram/parse")
def parse_instagram():
    """
    Получает Instagram-публикации за период.

    Требуется заголовок:
    X-API-Key
    """
    if not check_access_key():
        return jsonify({
            "success": False,
            "error": "Неверный API-ключ."
        }), 401

    payload = request.get_json(
        silent=True
    )

    if not isinstance(payload, dict):
        return jsonify({
            "success": False,
            "error":
                "Тело запроса должно "
                "содержать JSON."
        }), 400

    try:
        result = parse_instagram_account(
            payload
        )

        return jsonify(result)

    except urllib.error.HTTPError as error:
        response_text = ""

        try:
            response_text = error.read().decode(
                "utf-8",
                errors="replace"
            )
        except Exception:
            response_text = str(error)

        app.logger.exception(
            "Ошибка Instagram API"
        )

        return jsonify({
            "success": False,
            "error":
                f"Instagram API HTTP "
                f"{error.code}",
            "details": response_text
        }), 502

    except Exception as error:
        app.logger.exception(
            "Ошибка Instagram-парсинга"
        )

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.get("/media/<path:file_name>")
def media(file_name: str):
    """
    Отдаёт скачанные изображения.
    """
    return send_from_directory(
        MEDIA_DIR,
        file_name
    )

@app.get("/instagram/connect")
def instagram_connect():
    if not INSTAGRAM_APP_ID or not INSTAGRAM_REDIRECT_URI:
        return jsonify({
            "ok": False,
            "error": "Instagram settings are not configured"
        }), 500

    params = {
        "client_id": INSTAGRAM_APP_ID,
        "redirect_uri": INSTAGRAM_REDIRECT_URI,
        "response_type": "code",
        "scope": ",".join(INSTAGRAM_SCOPES),
    }

    authorization_url = (
        "https://www.instagram.com/oauth/authorize?"
        + urllib.parse.urlencode(params)
    )

    return jsonify({
        "ok": True,
        "authorization_url": authorization_url
    })

@app.get("/instagram/callback")
def instagram_callback():
    error = request.args.get("error")
    if error:
        return jsonify({
            "ok": False,
            "error": error,
            "error_reason": request.args.get("error_reason"),
            "error_description": request.args.get("error_description"),
        }), 400

    code = request.args.get("code", "").strip()

    if not code:
        return jsonify({
            "ok": False,
            "error": "Authorization code is missing"
        }), 400

    try:
        token_request_data = urllib.parse.urlencode({
            "client_id": INSTAGRAM_APP_ID,
            "client_secret": INSTAGRAM_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": INSTAGRAM_REDIRECT_URI,
            "code": code,
        }).encode("utf-8")

        token_request = urllib.request.Request(
            "https://api.instagram.com/oauth/access_token",
            data=token_request_data,
            method="POST",
        )

        with urllib.request.urlopen(token_request, timeout=30) as response:
            short_token_data = json.loads(
                response.read().decode("utf-8")
            )

        short_token = short_token_data.get("access_token", "")
        user_id = short_token_data.get("user_id")

        if not short_token:
            return jsonify({
                "ok": False,
                "error": "Instagram did not return an access token",
                "response": short_token_data,
            }), 500

        long_token_params = urllib.parse.urlencode({
            "grant_type": "ig_exchange_token",
            "client_secret": INSTAGRAM_APP_SECRET,
            "access_token": short_token,
        })

        long_token_url = (
            "https://graph.instagram.com/access_token?"
            + long_token_params
        )

        with urllib.request.urlopen(long_token_url, timeout=30) as response:
            long_token_data = json.loads(
                response.read().decode("utf-8")
            )

        token_data = {
            "access_token": long_token_data.get(
                "access_token",
                short_token
            ),
            "token_type": long_token_data.get("token_type"),
            "expires_in": long_token_data.get("expires_in"),
            "user_id": user_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        INSTAGRAM_TOKEN_FILE.write_text(
            json.dumps(
                token_data,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8",
        )

        return jsonify({
            "ok": True,
            "message": "Instagram account connected",
            "user_id": user_id,
            "expires_in": token_data.get("expires_in"),
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5050,
        debug=False,
        threaded=False
    )
