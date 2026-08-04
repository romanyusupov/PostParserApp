import datetime
import logging
import os
import pathlib
import re
import stat
from typing import Any


SPREADSHEET_ID_ENV = "GOOGLE_SPREADSHEET_ID"
CREDENTIALS_PATH_ENV = "GOOGLE_SHEETS_CREDENTIALS_PATH"
MAX_SHEET_NAME_LENGTH = 100
GOOGLE_SHEETS_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
)

EXPORT_HEADERS = (
    "Ссылка",
    "Дата",
    "Первый абзац",
    "Картинка",
    "Просмотры",
    "Лайки",
    "Комментарии",
    "Тип поста",
    "Описание видео",
    "Тип рекламы",
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


def _safe_metric(value: Any) -> Any:
    if value is None or value == "" or isinstance(value, bool):
        return ""

    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return ""


def build_sheet_name(run: dict[str, Any]) -> str:
    raw_name = _safe_text(run.get("group_name")).strip() or "Группа"
    safe_name = re.sub(r"[\[\]:*?/\\]", " ", raw_name)
    safe_name = " ".join(safe_name.split()).strip("'")
    return (safe_name or "Группа")[:MAX_SHEET_NAME_LENGTH]


def build_export_row(post: dict[str, Any]) -> list[Any]:
    return [
        _safe_text(post.get("url")),
        _safe_text(post.get("published_at")),
        _safe_text(post.get("first_paragraph")),
        _safe_text(post.get("image_url")),
        _safe_metric(post.get("views")),
        _safe_metric(post.get("likes")),
        _safe_metric(post.get("comments")),
        _safe_text(post.get("post_type")),
        _safe_text(post.get("video_description")),
        _safe_text(post.get("advertising_type")),
    ]


def _quoted_sheet_name(sheet_name: str) -> str:
    return "'" + sheet_name.replace("'", "''") + "'"


class GoogleSheetsClient:
    def __init__(self, service: Any):
        self._service = service

    @classmethod
    def from_credentials_path(cls, credentials_path: pathlib.Path):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_file(
                str(credentials_path),
                scopes=GOOGLE_SHEETS_SCOPES,
            )
            service = build(
                "sheets",
                "v4",
                credentials=credentials,
                cache_discovery=False,
            )
        except Exception:
            raise GoogleSheetsConfigurationError(
                "Не удалось создать клиент Google Sheets."
            ) from None

        return cls(service)

    def ensure_sheet(self, spreadsheet_id: str, sheet_name: str) -> bool:
        response = self._service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties.title",
            includeGridData=False,
        ).execute()
        existing_titles = {
            str(sheet.get("properties", {}).get("title", ""))
            for sheet in response.get("sheets", [])
        }
        if sheet_name in existing_titles:
            return False

        self._service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {"title": sheet_name},
                        }
                    }
                ]
            },
        ).execute()
        return True

    def clear_sheet(self, spreadsheet_id: str, sheet_name: str) -> None:
        self._service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=_quoted_sheet_name(sheet_name),
            body={},
        ).execute()

    def write_values(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[list[Any]],
    ) -> None:
        self._service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=_quoted_sheet_name(sheet_name) + "!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()


class GoogleSheetsExporter:
    def __init__(
        self,
        client_factory: Any = None,
        spreadsheet_id: Any = None,
        credentials_path: Any = None,
        results_store: Any = None,
        now_factory: Any = None,
    ):
        self._spreadsheet_id = _configured_value(
            spreadsheet_id,
            SPREADSHEET_ID_ENV,
        )
        if not self._spreadsheet_id:
            raise GoogleSheetsConfigurationError(
                "Google Spreadsheet ID не настроен."
            )

        configured_credentials_path = _configured_value(
            credentials_path,
            CREDENTIALS_PATH_ENV,
        )
        if not configured_credentials_path:
            raise GoogleSheetsConfigurationError(
                "Google Service Account не настроен."
            )

        self._credentials_path = pathlib.Path(configured_credentials_path)
        self._validate_credentials_file()
        self._client_factory = client_factory or (
            lambda: GoogleSheetsClient.from_credentials_path(
                self._credentials_path
            )
        )
        self._results_store = results_store
        self._now_factory = now_factory or (
            lambda: datetime.datetime.now(datetime.timezone.utc)
        )

    def _validate_credentials_file(self) -> None:
        try:
            file_stat = self._credentials_path.stat()
        except OSError:
            raise GoogleSheetsConfigurationError(
                "Google Service Account не настроен."
            ) from None

        if not stat.S_ISREG(file_stat.st_mode):
            raise GoogleSheetsConfigurationError(
                "Google Service Account не настроен."
            )

        if os.name != "nt" and stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise GoogleSheetsConfigurationError(
                "Файл Google Service Account должен иметь права 0600."
            )

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

    def _rows_for_run(
        self,
        run: dict[str, Any],
        posts: list[dict[str, Any]],
    ) -> list[list[Any]]:
        exported_at = self._now_factory()
        if isinstance(exported_at, datetime.datetime):
            exported_at_value = exported_at.isoformat()
        else:
            exported_at_value = _safe_text(exported_at)

        rows = [
            ["Группа", _safe_text(run.get("group_name"))],
            ["Дата экспорта", exported_at_value],
            ["Run", run.get("id")],
            [],
            list(EXPORT_HEADERS),
        ]
        rows.extend(build_export_row(post) for post in posts)
        return rows

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
            rows = self._rows_for_run(run, run_posts)
        except Exception:
            LOGGER.error("Не удалось подготовить результаты для экспорта.")
            raise GoogleSheetsExportError(
                "Не удалось подготовить результаты для экспорта."
            ) from None

        try:
            client = self._client_factory()
        except GoogleSheetsConfigurationError:
            raise
        except Exception:
            LOGGER.error("Не удалось создать клиент Google Sheets.")
            raise GoogleSheetsExportError(
                "Не удалось экспортировать результаты в Google Sheets."
            ) from None

        ensure_sheet = getattr(client, "ensure_sheet", None)
        clear_sheet = getattr(client, "clear_sheet", None)
        write_values = getattr(client, "write_values", None)
        if not all(
            callable(method)
            for method in (ensure_sheet, clear_sheet, write_values)
        ):
            raise GoogleSheetsConfigurationError(
                "Клиент Google Sheets настроен некорректно."
            )

        try:
            sheet_created = ensure_sheet(
                self._spreadsheet_id,
                sheet_name,
            )
            if not sheet_created:
                clear_sheet(self._spreadsheet_id, sheet_name)
            write_values(self._spreadsheet_id, sheet_name, rows)
        except Exception:
            LOGGER.error("Не удалось экспортировать результаты в Google Sheets.")
            raise GoogleSheetsExportError(
                "Не удалось экспортировать результаты в Google Sheets."
            ) from None

        return {
            "run_id": run["id"],
            "sheet_name": sheet_name,
            "count": len(run_posts),
        }
