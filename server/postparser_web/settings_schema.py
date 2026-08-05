import datetime


class SettingsValidationError(Exception):
    """Настройки не соответствуют ожидаемому контракту."""


def _clean_string(value, limit=None):
    text = " ".join(str(value or "").split())
    if limit is not None:
        text = text[:limit]
    return text


def _comparison_key(value):
    return _clean_string(value).casefold().replace("ё", "е")


def _prepare_words(words):
    if not isinstance(words, list):
        return words

    result = []
    used = set()

    for word in words:
        if not isinstance(word, str):
            result.append(word)
            continue

        cleaned = _clean_string(word, 200)
        if not cleaned:
            continue

        key = _comparison_key(cleaned)
        if key in used:
            continue

        used.add(key)
        result.append(cleaned)

    return result


def _prepare_advertising_types(advertising_types):
    if not isinstance(advertising_types, list):
        return advertising_types

    result = []

    for advertising_type in advertising_types:
        if not isinstance(advertising_type, dict):
            result.append(advertising_type)
            continue

        result.append(
            {
                "type": _clean_string(
                    advertising_type.get("type", ""),
                    100,
                ),
                "postWords": _prepare_words(
                    advertising_type.get("postWords", [])
                ),
                "videoWords": _prepare_words(
                    advertising_type.get("videoWords", [])
                ),
            }
        )

    return result


def _normalize_network(value):
    network = _clean_string(value).casefold()

    if network in {"tg", "telegram"}:
        return "telegram"

    if network in {"ig", "instagram"}:
        return "instagram"

    return "vk"


def prepare_settings(settings):
    if not isinstance(settings, dict):
        raise SettingsValidationError(
            "Настройки должны быть словарём."
        )

    source_groups = settings.get("groups", [])

    if isinstance(source_groups, list):
        groups = []

        for group in source_groups:
            if not isinstance(group, dict):
                groups.append(group)
                continue

            groups.append(
                {
                    "id": _clean_string(group.get("id", "")),
                    "name": _clean_string(
                        group.get("name", ""),
                        100,
                    ),
                    "network": _normalize_network(
                        group.get("network", "")
                    ),
                    "url": _clean_string(
                        group.get("url", ""),
                        500,
                    ),
                    "dateStart": _clean_string(
                        group.get("dateStart", "")
                    ),
                    "dateEnd": _clean_string(
                        group.get("dateEnd", "")
                    ),
                    "advertisingTypes":
                        _prepare_advertising_types(
                            group.get(
                                "advertisingTypes",
                                [],
                            )
                        ),
                }
            )
    else:
        groups = source_groups

    return {
        "groups": groups,
        "savedAt": _clean_string(
            settings.get("savedAt", "")
        ),
    }


def _require_nonempty_string(value, message):
    if not isinstance(value, str) or not value.strip():
        raise SettingsValidationError(message)


def _parse_date(value, group_name, field_name):
    if not isinstance(value, str):
        raise SettingsValidationError(
            f"В группе «{group_name}» поле {field_name} "
            "должно быть строкой."
        )

    if not value:
        return None

    try:
        return datetime.date.fromisoformat(value)
    except ValueError as error:
        raise SettingsValidationError(
            f"В группе «{group_name}» поле {field_name} "
            "должно иметь формат YYYY-MM-DD."
        ) from error


def _validate_words(words, group_name, type_name, field_name):
    if not isinstance(words, list):
        raise SettingsValidationError(
            f"В типе «{type_name}» группы «{group_name}» "
            f"поле {field_name} должно быть списком строк."
        )

    if not all(isinstance(word, str) for word in words):
        raise SettingsValidationError(
            f"В типе «{type_name}» группы «{group_name}» "
            f"поле {field_name} должно содержать только строки."
        )


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise SettingsValidationError(
            "Настройки должны быть словарём."
        )

    groups = settings.get("groups")

    if not isinstance(groups, list):
        raise SettingsValidationError(
            "Поле groups должно быть списком."
        )

    used_group_names = set()

    for group_index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            raise SettingsValidationError(
                f"Группа №{group_index} должна быть словарём."
            )

        _require_nonempty_string(
            group.get("id"),
            f"В группе №{group_index} не указан id.",
        )
        _require_nonempty_string(
            group.get("name"),
            f"В группе №{group_index} не указано название.",
        )
        _require_nonempty_string(
            group.get("network"),
            f"В группе №{group_index} не указана социальная сеть.",
        )
        _require_nonempty_string(
            group.get("url"),
            f"В группе №{group_index} не указан URL.",
        )

        group_name = group["name"].strip()
        group_name_key = _comparison_key(group_name)

        if group_name_key in used_group_names:
            raise SettingsValidationError(
                f"Название группы «{group_name}» повторяется."
            )

        used_group_names.add(group_name_key)

        network = group["network"]
        if network not in {"vk", "telegram", "instagram"}:
            raise SettingsValidationError(
                f"В группе «{group_name}» указана "
                "неподдерживаемая социальная сеть."
            )

        date_start_value = group.get("dateStart", "")
        date_end_value = group.get("dateEnd", "")
        date_start = _parse_date(
            date_start_value,
            group_name,
            "dateStart",
        )
        date_end = _parse_date(
            date_end_value,
            group_name,
            "dateEnd",
        )

        if (
            network in {"telegram", "instagram"}
            and (date_start is None or date_end is None)
        ):
            raise SettingsValidationError(
                f"Для группы «{group_name}» укажите "
                "дату начала и дату окончания."
            )

        if (
            date_start is not None
            and date_end is not None
            and date_start > date_end
        ):
            raise SettingsValidationError(
                f"В группе «{group_name}» дата начала "
                "не может быть позже даты окончания."
            )

        advertising_types = group.get("advertisingTypes")
        if not isinstance(advertising_types, list):
            raise SettingsValidationError(
                f"В группе «{group_name}» advertisingTypes "
                "должен быть списком."
            )

        used_type_names = set()

        for type_index, advertising_type in enumerate(
            advertising_types,
            start=1,
        ):
            if not isinstance(advertising_type, dict):
                raise SettingsValidationError(
                    f"Тип рекламы №{type_index} в группе "
                    f"«{group_name}» должен быть словарём."
                )

            type_name = advertising_type.get("type")
            _require_nonempty_string(
                type_name,
                f"Введите название типа рекламы в группе "
                f"«{group_name}», строка {type_index}.",
            )

            type_name = type_name.strip()
            type_name_key = _comparison_key(type_name)

            if type_name_key in used_type_names:
                raise SettingsValidationError(
                    f"В группе «{group_name}» повторяется "
                    f"тип рекламы «{type_name}»."
                )

            used_type_names.add(type_name_key)

            _validate_words(
                advertising_type.get("postWords"),
                group_name,
                type_name,
                "postWords",
            )
            _validate_words(
                advertising_type.get("videoWords"),
                group_name,
                type_name,
                "videoWords",
            )
