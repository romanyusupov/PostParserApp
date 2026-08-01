import datetime
import logging
import os
import re
from typing import Any


SPREADSHEET_ID_ENV = "POSTPARSER_GOOGLE_SPREADSHEET_ID"
SERVICE_ACCOUNT_JSON_ENV = "POSTPARSER_GOOGLE_SERVICE_ACCOUNT_JSON"
MAX_SHEET_NAME_LENGTH = 100

EXPORT_HEADERS = (
    "Дата",
    "Сеть",
    "Группа",
    "Тип",
    "Текст",
    "Первый абзац",
    "Ссылка",
    "Просмотры",
    "Лайки",
    "Комментарии",
    "Сохранения",
    "Репосты",
)

LOGGER = logging.getLogger(__name__)


class GoogleSheetsExportError(Exception):
    """Ошибка экспорта результатов в Google Sheets."""


class GoogleSheetsConfigurationError(GoogleSheetsExportError):
    """Ошибка безопасной конфигурации экспорта."""


def _configured_value(explicit_value: Any, environment_name: str) -> str:
    value = (
        explicit_value
        if explicit_value is not None
        else os.environ.get(environment_name, "")
    )
    return str(value).strip() if value is not None else ""


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def _safe_metric(value: Any) -> int:
    if isinstance(value, bool):
        return 0

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _network_title(network: Any) -> str:
    labels = {
        "vk": "VK",
        "instagram": "Instagram",
        "telegram": "Telegram",
    }
    normalized_network = _safe_text(network).strip().lower()
    return labels.get(normalized_network, normalized_network or "Сеть")


def _run_year(run: dict[str, Any]) -> str:
    raw_date = _safe_text(
        run.get("finished_at") or run.get("started_at")
    ).strip()
    if not raw_date:
        return "без даты"

    try:
        return str(datetime.datetime.fromisoformat(raw_date).year)
    except ValueError:
        match = re.search(r"\b\d{4}\b", raw_date)
        return match.group(0) if match else "без даты"


def build_sheet_name(run: dict[str, Any]) -> str:
    raw_name = " ".join(
        (
            _network_title(run.get("network")),
            _safe_text(run.get("group_name")).strip() or "Группа",
            _run_year(run),
        )
    )
    safe_name = re.sub(r"[\[\]:*?/\\]", " ", raw_name)
    safe_name = " ".join(safe_name.split()).strip("'")
    return (safe_name or "Результаты")[:MAX_SHEET_NAME_LENGTH]


def _post_reposts(post: dict[str, Any]) -> int:
    shares = _safe_metric(post.get("shares"))
    return shares or _safe_metric(post.get("forwards"))


def build_export_row(post: dict[str, Any], group_name: Any) -> list[Any]:
    return [
        _safe_text(post.get("published_at")),
        _safe_text(post.get("source")),
        _safe_text(group_name),
        _safe_text(post.get("post_type")),
        _safe_text(post.get("text")),
        _safe_text(post.get("first_paragraph")),
        _safe_text(post.get("url")),
        _safe_metric(post.get("views")),
        _safe_metric(post.get("likes")),
        _safe_metric(post.get("comments")),
        _safe_metric(post.get("saved")),
        _post_reposts(post),
    ]


class GoogleSheetsExporter:
    def __init__(
        self,
        client_factory: Any = None,
        spreadsheet_id: Any = None,
        credentials_json: Any = None,
        results_store: Any = None,
    ):
        self._spreadsheet_id = _configured_value(
            spreadsheet_id,
            SPREADSHEET_ID_ENV,
        )
        if not self._spreadsheet_id:
            raise GoogleSheetsConfigurationError(
                "Google Spreadsheet ID не настроен."
            )

        self._credentials_json = _configured_value(
            credentials_json,
            SERVICE_ACCOUNT_JSON_ENV,
        )
        if not self._credentials_json:
            raise GoogleSheetsConfigurationError(
                "Google Service Account не настроен."
            )

        self._client_factory = client_factory
        self._results_store = results_store

    def _validate_dependencies(self) -> None:
        if not callable(self._client_factory):
            raise GoogleSheetsConfigurationError(
                "Фабрика клиента Google Sheets не настроена."
            )

        if not callable(getattr(self._results_store, "get_run", None)):
            raise GoogleSheetsConfigurationError(
                "Хранилище результатов не настроено."
            )

        if not callable(getattr(self._results_store, "get_posts", None)):
            raise GoogleSheetsConfigurationError(
                "Хранилище результатов не настроено."
            )

    def export_run(self, run_id: Any) -> dict[str, Any]:
        self._validate_dependencies()

        try:
            run = self._results_store.get_run(run_id)
        except Exception:
            LOGGER.error("Не удалось прочитать результаты для экспорта.")
            raise GoogleSheetsExportError(
                "Не удалось подготовить результаты для экспорта."
            ) from None

        if run is None:
            raise GoogleSheetsExportError("Запуск не найден.")

        try:
            posts = self._results_store.get_posts(
                group_id=run["group_id"],
                network=run["network"],
            )
            run_posts = [
                post
                for post in posts
                if post.get("run_id") == run["id"]
            ]
            sheet_name = build_sheet_name(run)
            rows = [list(EXPORT_HEADERS)]
            rows.extend(
                build_export_row(post, run["group_name"])
                for post in run_posts
            )
        except Exception:
            LOGGER.error("Не удалось подготовить результаты для экспорта.")
            raise GoogleSheetsExportError(
                "Не удалось подготовить результаты для экспорта."
            ) from None

        try:
            client = self._client_factory()
        except Exception:
            LOGGER.error(
                "Не удалось создать клиент Google Sheets для экспорта."
            )
            raise GoogleSheetsExportError(
                "Не удалось экспортировать результаты в Google Sheets."
            ) from None

        create_sheet = getattr(client, "create_sheet", None)
        write_values = getattr(client, "write_values", None)
        if not callable(create_sheet) or not callable(write_values):
            raise GoogleSheetsConfigurationError(
                "Клиент Google Sheets настроен некорректно."
            )

        try:
            create_sheet(self._spreadsheet_id, sheet_name)
            write_values(self._spreadsheet_id, sheet_name, rows)
        except Exception:
            LOGGER.error(
                "Не удалось экспортировать результаты в Google Sheets."
            )
            raise GoogleSheetsExportError(
                "Не удалось экспортировать результаты в Google Sheets."
            ) from None

        return {
            "run_id": run["id"],
            "sheet_name": sheet_name,
            "count": len(run_posts),
        }
