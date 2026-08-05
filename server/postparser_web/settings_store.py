import datetime
import json
import pathlib
import sqlite3


class RevisionConflict(Exception):
    """Настройки были изменены после загрузки клиентом."""

    def __init__(self, expected_revision, current_revision):
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__(
            "Ожидалась ревизия "
            f"{expected_revision}, текущая ревизия {current_revision}."
        )


class SettingsStore:
    DOCUMENT_KEY = "parser_settings"
    SCHEMA_VERSION = 1
    SQLITE_TIMEOUT_SECONDS = 5.0

    def __init__(self, database_path):
        self.database_path = pathlib.Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        return sqlite3.connect(
            self.database_path,
            timeout=self.SQLITE_TIMEOUT_SECONDS,
        )

    def _initialize(self):
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings_documents (
                    key TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _document_key(self, owner_id):
        normalized_owner_id = str(owner_id or "admin").strip()
        if normalized_owner_id == "admin":
            return self.DOCUMENT_KEY
        return f"{self.DOCUMENT_KEY}:{normalized_owner_id}"

    def load(self, owner_id="admin"):
        document_key = self._document_key(owner_id)
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT revision, payload_json
                FROM settings_documents
                WHERE key = ?
                """,
                (document_key,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            return {
                "revision": 0,
                "settings": {
                    "groups": [],
                    "savedAt": "",
                },
            }

        revision, payload_json = row
        return {
            "revision": revision,
            "settings": json.loads(payload_json),
        }

    def save(self, settings, expected_revision, owner_id="admin"):
        document_key = self._document_key(owner_id)
        payload_json = json.dumps(
            settings,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        timestamp = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT revision
                FROM settings_documents
                WHERE key = ?
                """,
                (document_key,),
            ).fetchone()

            current_revision = row[0] if row is not None else 0

            if current_revision != expected_revision:
                raise RevisionConflict(
                    expected_revision,
                    current_revision,
                )

            new_revision = current_revision + 1

            if row is None:
                connection.execute(
                    """
                    INSERT INTO settings_documents (
                        key,
                        schema_version,
                        revision,
                        payload_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_key,
                        self.SCHEMA_VERSION,
                        new_revision,
                        payload_json,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE settings_documents
                    SET schema_version = ?,
                        revision = ?,
                        payload_json = ?,
                        updated_at = ?
                    WHERE key = ?
                    """,
                    (
                        self.SCHEMA_VERSION,
                        new_revision,
                        payload_json,
                        timestamp,
                        document_key,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "revision": new_revision,
            "settings": json.loads(payload_json),
        }
