import datetime
import json
import pathlib
import sqlite3
from typing import Any


POST_TEXT_FIELDS = (
    "source",
    "external_id",
    "url",
    "published_at",
    "text",
    "first_paragraph",
    "post_type",
    "advertising_type",
    "image_url",
    "video_url",
)

POST_METRIC_FIELDS = (
    "views",
    "reach",
    "likes",
    "comments",
    "saved",
    "shares",
    "forwards",
)
OPTIONAL_POST_METRIC_FIELDS = {"views", "reach", "saved", "shares"}

RUNNING_STATUS = "running"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"


class ResultsStoreError(Exception):
    """Ошибка чтения или записи результатов парсинга."""


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            raise ResultsStoreError(
                "Текстовое поле публикации содержит неподдерживаемое значение."
            ) from None

    return str(value)


def _safe_metric(value: Any) -> int:
    if isinstance(value, bool):
        return 0

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _positive_run_id(value: Any) -> int:
    try:
        run_id = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ResultsStoreError(
            "Идентификатор запуска должен быть положительным числом."
        ) from None

    if run_id <= 0:
        raise ResultsStoreError(
            "Идентификатор запуска должен быть положительным числом."
        )

    return run_id


def _normalize_post(post: Any) -> tuple[Any, ...]:
    if not isinstance(post, dict):
        raise ResultsStoreError(
            "Каждая публикация должна быть словарём."
        )

    text_values = tuple(
        _safe_text(post.get(field_name))
        for field_name in POST_TEXT_FIELDS
    )
    metric_values = tuple(
        ""
        if (
            field_name in OPTIONAL_POST_METRIC_FIELDS
            and field_name in post
            and post[field_name] is None
        )
        else _safe_metric(post.get(field_name))
        for field_name in POST_METRIC_FIELDS
    )
    return text_values + metric_values


class ResultsStore:
    SQLITE_TIMEOUT_SECONDS = 5.0

    def __init__(self, database_path: Any):
        self.database_path = pathlib.Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.SQLITE_TIMEOUT_SECONDS,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parse_runs (
                    id INTEGER PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    network TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    warning TEXT NOT NULL DEFAULT ''
                )
                """
            )
            run_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(parse_runs)"
                ).fetchall()
            }
            if "status" not in run_columns:
                connection.execute(
                    """
                    ALTER TABLE parse_runs
                    ADD COLUMN status TEXT NOT NULL DEFAULT 'running'
                    """
                )
                connection.execute(
                    """
                    UPDATE parse_runs
                    SET status = CASE
                        WHEN finished_at = '' THEN 'running'
                        ELSE 'completed'
                    END
                    """
                )
            if "warning" not in run_columns:
                connection.execute(
                    """
                    ALTER TABLE parse_runs
                    ADD COLUMN warning TEXT NOT NULL DEFAULT ''
                    """
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    text TEXT NOT NULL,
                    first_paragraph TEXT NOT NULL,
                    post_type TEXT NOT NULL,
                    advertising_type TEXT,
                    image_url TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    views INTEGER,
                    reach INTEGER,
                    likes INTEGER NOT NULL,
                    comments INTEGER NOT NULL,
                    saved INTEGER NOT NULL,
                    shares INTEGER NOT NULL,
                    forwards INTEGER NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES parse_runs(id)
                        ON DELETE CASCADE,
                    UNIQUE (run_id, source, external_id)
                )
                """
            )
            post_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(posts)"
                ).fetchall()
            }
            if "reach" not in post_columns:
                connection.execute(
                    "ALTER TABLE posts ADD COLUMN reach INTEGER"
                )
            if "advertising_type" not in post_columns:
                connection.execute(
                    "ALTER TABLE posts ADD COLUMN advertising_type TEXT"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_parse_runs_group_network
                ON parse_runs (group_id, network)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_posts_published_at
                ON posts (published_at)
                """
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_run(
        self,
        group_id: Any,
        group_name: Any,
        network: Any,
    ) -> int:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO parse_runs (
                    group_id,
                    group_name,
                    network,
                    status,
                    started_at,
                    finished_at,
                    count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _safe_text(group_id),
                    _safe_text(group_name),
                    _safe_text(network),
                    RUNNING_STATUS,
                    _utc_now(),
                    "",
                    0,
                ),
            )
            run_id = int(cursor.lastrowid)
            connection.commit()
            return run_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _complete_run(
        self,
        run_id: Any,
        count: Any,
        status: str,
        warning: Any = "",
    ) -> dict[str, Any]:
        normalized_run_id = _positive_run_id(run_id)
        normalized_count = _safe_metric(count)
        finished_at = _utc_now()
        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE parse_runs
                SET finished_at = ?, count = ?, status = ?, warning = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    normalized_count,
                    status,
                    _safe_text(warning),
                    normalized_run_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ResultsStoreError(
                    f"Запуск с id {normalized_run_id} не найден."
                )

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "run_id": normalized_run_id,
            "finished_at": finished_at,
            "count": normalized_count,
            "status": status,
            "warning": _safe_text(warning),
        }

    def finish_run(
        self,
        run_id: Any,
        count: Any,
        warning: Any = "",
    ) -> dict[str, Any]:
        return self._complete_run(
            run_id,
            count,
            COMPLETED_STATUS,
            warning,
        )

    def fail_run(self, run_id: Any, count: Any) -> dict[str, Any]:
        return self._complete_run(
            run_id,
            count,
            FAILED_STATUS,
        )

    def get_run(self, run_id: Any) -> dict[str, Any] | None:
        normalized_run_id = _positive_run_id(run_id)
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    group_id,
                    group_name,
                    network,
                    status,
                    started_at,
                    finished_at,
                    count,
                    warning
                FROM parse_runs
                WHERE id = ?
                """,
                (normalized_run_id,),
            ).fetchone()
        finally:
            connection.close()

        return dict(row) if row is not None else None

    def list_runs(self, limit: Any = 50) -> list[dict[str, Any]]:
        if isinstance(limit, bool):
            raise ResultsStoreError(
                "Лимит запусков должен быть положительным числом."
            )

        try:
            normalized_limit = int(limit)
        except (TypeError, ValueError, OverflowError):
            raise ResultsStoreError(
                "Лимит запусков должен быть положительным числом."
            ) from None

        if normalized_limit <= 0:
            raise ResultsStoreError(
                "Лимит запусков должен быть положительным числом."
            )

        normalized_limit = min(normalized_limit, 50)
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    group_id,
                    group_name,
                    network,
                    status,
                    started_at,
                    finished_at,
                    count,
                    warning
                FROM parse_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
        finally:
            connection.close()

        return [dict(row) for row in rows]

    def save_posts(self, run_id: Any, posts: Any) -> int:
        normalized_run_id = _positive_run_id(run_id)
        if not isinstance(posts, (list, tuple)):
            raise ResultsStoreError(
                "Публикации должны быть списком."
            )

        connection = self._connect()
        inserted_count = 0

        try:
            connection.execute("BEGIN IMMEDIATE")
            run_exists = connection.execute(
                "SELECT 1 FROM parse_runs WHERE id = ?",
                (normalized_run_id,),
            ).fetchone()

            if run_exists is None:
                raise ResultsStoreError(
                    f"Запуск с id {normalized_run_id} не найден."
                )

            for post in posts:
                values = _normalize_post(post)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO posts (
                        run_id,
                        source,
                        external_id,
                        url,
                        published_at,
                        text,
                        first_paragraph,
                        post_type,
                        advertising_type,
                        image_url,
                        video_url,
                        views,
                        reach,
                        likes,
                        comments,
                        saved,
                        shares,
                        forwards
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (normalized_run_id,) + values,
                )
                inserted_count += max(0, cursor.rowcount)

            connection.commit()
            return inserted_count
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_posts(
        self,
        group_id: Any = None,
        network: Any = None,
    ) -> list[dict[str, Any]]:
        conditions = []
        parameters = []

        if group_id is not None:
            conditions.append("runs.group_id = ?")
            parameters.append(_safe_text(group_id))

        if network is not None:
            conditions.append("runs.network = ?")
            parameters.append(_safe_text(network))

        where_clause = (
            " WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )
        query = (
            """
            SELECT
                posts.id,
                posts.run_id,
                runs.group_id,
                runs.group_name,
                runs.network,
                posts.source,
                posts.external_id,
                posts.url,
                posts.published_at,
                posts.text,
                posts.first_paragraph,
                posts.post_type,
                posts.advertising_type,
                posts.image_url,
                posts.video_url,
                posts.views,
                posts.reach,
                posts.likes,
                posts.comments,
                posts.saved,
                posts.shares,
                posts.forwards
            FROM posts
            JOIN parse_runs AS runs ON runs.id = posts.run_id
            """
            + where_clause
            + " ORDER BY posts.published_at DESC, posts.id DESC"
        )

        connection = self._connect()
        try:
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

        return [dict(row) for row in rows]
