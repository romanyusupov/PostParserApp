import os
from typing import Any

from server.postparser_web.instagram_parser import (
    InstagramConfigurationError,
    InstagramParser,
    InstagramParserError,
)
from server.postparser_web.telegram_parser import (
    TelegramConfigurationError,
    TelegramParser,
    TelegramParserError,
)
from server.postparser_web.vk_parser import (
    VkConfigurationError,
    VkParser,
    VkParserError,
)


VK_ACCESS_TOKEN_ENVIRONMENT_VARIABLE = "POSTPARSER_VK_ACCESS_TOKEN"
INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE = (
    "POSTPARSER_INSTAGRAM_ACCESS_TOKEN"
)
TELEGRAM_API_ID_ENVIRONMENT_VARIABLE = "TELEGRAM_API_ID"
TELEGRAM_API_HASH_ENVIRONMENT_VARIABLE = "TELEGRAM_API_HASH"
TELEGRAM_SESSION_STRING_ENVIRONMENT_VARIABLE = "TELEGRAM_SESSION_STRING"


class ParseServiceError(Exception):
    """Ошибка запуска парсера для сохранённой группы."""


class ParseGroupNotFoundError(ParseServiceError):
    """Группа с указанным идентификатором отсутствует."""


class ParseConfigurationError(ParseServiceError):
    """Конфигурации недостаточно для запуска парсера."""


class UnsupportedNetworkError(ParseServiceError):
    """Для социальной сети не зарегистрирован парсер."""


class ParserExecutionError(ParseServiceError):
    """Выбранный парсер не смог получить публикации."""


def _create_vk_parser() -> VkParser:
    access_token = os.environ.get(
        VK_ACCESS_TOKEN_ENVIRONMENT_VARIABLE,
        "",
    ).strip()

    if not access_token:
        raise ParseConfigurationError(
            "VK-подключение не настроено."
        )

    return VkParser(access_token)


def _create_instagram_parser() -> InstagramParser:
    access_token = os.environ.get(
        INSTAGRAM_ACCESS_TOKEN_ENVIRONMENT_VARIABLE,
        "",
    ).strip()

    if not access_token:
        raise ParseConfigurationError(
            "Instagram-подключение не настроено."
        )

    return InstagramParser(access_token)


def _create_telegram_parser() -> TelegramParser:
    api_id = os.environ.get(
        TELEGRAM_API_ID_ENVIRONMENT_VARIABLE,
        "",
    ).strip()
    api_hash = os.environ.get(
        TELEGRAM_API_HASH_ENVIRONMENT_VARIABLE,
        "",
    ).strip()
    session_string = os.environ.get(
        TELEGRAM_SESSION_STRING_ENVIRONMENT_VARIABLE,
        "",
    ).strip()

    if not api_id or not api_hash:
        raise ParseConfigurationError(
            "Telegram-подключение не настроено."
        )

    return TelegramParser(
        api_id,
        api_hash,
        session_string=session_string or None,
    )


DEFAULT_PARSER_FACTORIES = {
    "vk": _create_vk_parser,
    "instagram": _create_instagram_parser,
    "telegram": _create_telegram_parser,
}

PARSER_CONFIGURATION_ERRORS = (
    VkConfigurationError,
    InstagramConfigurationError,
    TelegramConfigurationError,
)

PARSER_ERRORS = (
    VkParserError,
    InstagramParserError,
    TelegramParserError,
)


def _find_group(stored_document: Any, group_id: str) -> dict[str, Any] | None:
    if not isinstance(stored_document, dict):
        raise ParseConfigurationError(
            "Хранилище вернуло некорректный документ настроек."
        )

    settings = stored_document.get("settings")
    if not isinstance(settings, dict):
        raise ParseConfigurationError(
            "В документе отсутствуют настройки парсеров."
        )

    groups = settings.get("groups")
    if not isinstance(groups, list):
        raise ParseConfigurationError(
            "В настройках отсутствует список групп."
        )

    for group in groups:
        if isinstance(group, dict) and group.get("id") == group_id:
            return group

    return None


def _required_group_string(
    group: dict[str, Any],
    field_name: str,
    description: str,
) -> str:
    value = group.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ParseConfigurationError(
            f"Для группы не указано {description}."
        )

    return value.strip()


class ParseService:
    def __init__(
        self,
        settings_store: Any,
        parser_factories: dict[str, Any] | None = None,
    ):
        if not callable(getattr(settings_store, "load", None)):
            raise ParseConfigurationError(
                "Хранилище настроек должно поддерживать load()."
            )

        factories = dict(DEFAULT_PARSER_FACTORIES)
        if parser_factories is not None:
            if not isinstance(parser_factories, dict):
                raise ParseConfigurationError(
                    "parser_factories должен быть словарём."
                )
            factories.update(parser_factories)

        self._settings_store = settings_store
        self._parser_factories = factories

    def parse_group(self, group_id: Any) -> dict[str, Any]:
        normalized_group_id = str(group_id or "").strip()
        if not normalized_group_id:
            raise ParseServiceError("Идентификатор группы не указан.")

        try:
            stored_document = self._settings_store.load()
        except Exception:
            raise ParseServiceError(
                "Не удалось загрузить настройки парсеров."
            ) from None

        group = _find_group(stored_document, normalized_group_id)
        if group is None:
            raise ParseGroupNotFoundError(
                f"Группа с id «{normalized_group_id}» не найдена."
            )

        group_name = _required_group_string(
            group,
            "name",
            "название",
        )
        network = _required_group_string(
            group,
            "network",
            "социальную сеть",
        ).casefold()

        if network not in {"vk", "instagram", "telegram"}:
            raise UnsupportedNetworkError(
                f"Социальная сеть «{network}» не поддерживается."
            )

        group_url = _required_group_string(
            group,
            "url",
            "URL или имя канала",
        )
        date_start = _required_group_string(
            group,
            "dateStart",
            "дату начала",
        )
        date_end = _required_group_string(
            group,
            "dateEnd",
            "дату окончания",
        )
        parser_factory = self._parser_factories.get(network)

        if not callable(parser_factory):
            raise ParseConfigurationError(
                f"Фабрика парсера для сети «{network}» не настроена."
            )

        try:
            parser = parser_factory()
        except ParseConfigurationError:
            raise
        except PARSER_CONFIGURATION_ERRORS as error:
            raise ParseConfigurationError(str(error)) from error
        except Exception:
            raise ParseConfigurationError(
                f"Не удалось создать парсер для сети «{network}»."
            ) from None

        fetch_posts = getattr(parser, "fetch_posts", None)
        if not callable(fetch_posts):
            raise ParseConfigurationError(
                f"Парсер для сети «{network}» не поддерживает fetch_posts()."
            )

        try:
            posts = fetch_posts(
                group_url,
                date_start,
                date_end,
            )
        except PARSER_CONFIGURATION_ERRORS as error:
            raise ParseConfigurationError(str(error)) from error
        except PARSER_ERRORS as error:
            raise ParserExecutionError(
                f"Ошибка парсера {network}: {error}"
            ) from error
        except Exception:
            raise ParserExecutionError(
                f"Не удалось выполнить парсинг для сети «{network}»."
            ) from None

        if not isinstance(posts, list):
            raise ParserExecutionError(
                f"Парсер сети «{network}» вернул некорректный результат."
            )

        return {
            "group_id": normalized_group_id,
            "group_name": group_name,
            "network": network,
            "count": len(posts),
            "posts": posts,
        }
