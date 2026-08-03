from typing import Any


class ParseRunnerError(Exception):
    """Ошибка координации парсинга и сохранения результатов."""


class ParseRunnerConfigurationError(ParseRunnerError):
    """Зависимости сервиса запуска настроены некорректно."""


class ParseRunnerGroupNotFoundError(ParseRunnerError):
    """Группа с указанным идентификатором отсутствует."""


def _required_method(value: Any, method_name: str, description: str) -> None:
    if not callable(getattr(value, method_name, None)):
        raise ParseRunnerConfigurationError(
            f"{description} должен поддерживать {method_name}()."
        )


def _load_group(settings_store: Any, group_id: str) -> dict[str, Any]:
    try:
        stored_document = settings_store.load()
    except Exception:
        raise ParseRunnerError(
            "Не удалось загрузить настройки парсеров."
        ) from None

    if not isinstance(stored_document, dict):
        raise ParseRunnerError(
            "Хранилище вернуло некорректный документ настроек."
        )

    settings = stored_document.get("settings")
    groups = settings.get("groups") if isinstance(settings, dict) else None
    if not isinstance(groups, list):
        raise ParseRunnerError(
            "В настройках отсутствует список групп."
        )

    for group in groups:
        if isinstance(group, dict) and group.get("id") == group_id:
            return group

    raise ParseRunnerGroupNotFoundError(
        f"Группа с id «{group_id}» не найдена."
    )


def _group_string(
    group: dict[str, Any],
    field_name: str,
    description: str,
) -> str:
    value = group.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ParseRunnerError(
            f"Для группы не указано {description}."
        )
    return value.strip()


class ParseRunnerService:
    def __init__(
        self,
        settings_store: Any,
        parse_service: Any,
        results_store: Any,
    ):
        _required_method(settings_store, "load", "SettingsStore")
        _required_method(parse_service, "parse_group", "ParseService")
        _required_method(results_store, "create_run", "ResultsStore")
        _required_method(results_store, "save_posts", "ResultsStore")
        _required_method(results_store, "finish_run", "ResultsStore")
        _required_method(results_store, "fail_run", "ResultsStore")

        self._settings_store = settings_store
        self._parse_service = parse_service
        self._results_store = results_store

    def _mark_failed(
        self,
        run_id: int,
        saved_count: int,
        original_error: Exception,
    ) -> None:
        try:
            self._results_store.fail_run(run_id, saved_count)
        except Exception:
            raise ParseRunnerError(
                "Парсинг завершился с ошибкой, но запуск не удалось "
                "перевести в состояние failed."
            ) from original_error

    def run_group(self, group_id: Any) -> dict[str, Any]:
        normalized_group_id = str(group_id or "").strip()
        if not normalized_group_id:
            raise ParseRunnerError("Идентификатор группы не указан.")

        group = _load_group(self._settings_store, normalized_group_id)
        group_name = _group_string(group, "name", "название")
        network = _group_string(
            group,
            "network",
            "социальную сеть",
        ).casefold()
        run_id = self._results_store.create_run(
            normalized_group_id,
            group_name,
            network,
        )
        saved_count = 0

        try:
            parse_result = self._parse_service.parse_group(
                normalized_group_id
            )
            if not isinstance(parse_result, dict):
                raise ParseRunnerError(
                    "ParseService вернул некорректный результат."
                )

            posts = parse_result.get("posts")
            if not isinstance(posts, list):
                raise ParseRunnerError(
                    "ParseService не вернул список публикаций."
                )

            warning = str(parse_result.get("warning") or "").strip()

            saved_count = self._results_store.save_posts(run_id, posts)
            count = len(posts)
            if warning:
                self._results_store.finish_run(run_id, count, warning)
            else:
                self._results_store.finish_run(run_id, count)
        except Exception as error:
            self._mark_failed(run_id, saved_count, error)
            raise

        result = {
            "run_id": run_id,
            "group_id": normalized_group_id,
            "group_name": group_name,
            "network": network,
            "count": count,
            "posts": posts,
        }
        if warning:
            result["warning"] = warning

        return result
