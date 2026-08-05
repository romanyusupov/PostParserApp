import datetime
import os
import pathlib
import secrets
import sqlite3
import string
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash


ACCESS_CODE_ALPHABET = string.ascii_letters + string.digits
ACCESS_CODE_LENGTH = 20


class AccessStore:
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
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS access_users (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    code_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(access_users)"
                ).fetchall()
            }
            if "deleted" not in columns:
                connection.execute(
                    """
                    ALTER TABLE access_users
                    ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0
                    """
                )
            connection.commit()
        finally:
            connection.close()
        if os.name != "nt":
            os.chmod(self.database_path, 0o600)

    def create_user(self) -> dict[str, Any]:
        access_code = "".join(
            secrets.choice(ACCESS_CODE_ALPHABET)
            for _ in range(ACCESS_CODE_LENGTH)
        )
        code_hash = generate_password_hash(access_code, method="scrypt")
        created_at = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            next_id = int(
                connection.execute(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM access_users"
                ).fetchone()[0]
            )
            name = f"Пользователь {next_id}"
            connection.execute(
                """
                INSERT INTO access_users (
                    id, name, code_hash, active, created_at
                )
                VALUES (?, ?, ?, 1, ?)
                """,
                (next_id, name, code_hash, created_at),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "id": next_id,
            "owner_id": f"user:{next_id}",
            "name": name,
            "access_code": access_code,
            "created_at": created_at,
        }

    def list_users(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT id, name, active, created_at
                FROM access_users
                WHERE deleted = 0
                ORDER BY id
                """
            ).fetchall()
        finally:
            connection.close()

        return [
            {
                "id": int(row["id"]),
                "owner_id": f"user:{int(row['id'])}",
                "name": row["name"],
                "active": bool(row["active"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def set_active(self, user_id: Any, active: Any) -> dict[str, Any] | None:
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError):
            return None
        if normalized_user_id <= 0 or not isinstance(active, bool):
            return None

        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE access_users
                SET active = ?
                WHERE id = ? AND deleted = 0
                """,
                (1 if active else 0, normalized_user_id),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                """
                SELECT id, name, active, created_at
                FROM access_users
                WHERE id = ?
                """,
                (normalized_user_id,),
            ).fetchone()
        finally:
            connection.close()

        return {
            "id": int(row["id"]),
            "owner_id": f"user:{int(row['id'])}",
            "name": row["name"],
            "active": bool(row["active"]),
            "created_at": row["created_at"],
        }

    def delete_user(self, user_id: Any) -> bool:
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError):
            return False
        if normalized_user_id <= 0:
            return False

        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE access_users
                SET active = 0, deleted = 1
                WHERE id = ? AND deleted = 0
                """,
                (normalized_user_id,),
            )
            exists = cursor.rowcount == 1
            if not exists:
                exists = connection.execute(
                    "SELECT 1 FROM access_users WHERE id = ?",
                    (normalized_user_id,),
                ).fetchone() is not None
            connection.commit()
        finally:
            connection.close()
        return exists

    def active_principal(self, owner_id: Any) -> dict[str, str] | None:
        normalized_owner_id = str(owner_id or "").strip()
        if not normalized_owner_id.startswith("user:"):
            return None
        try:
            user_id = int(normalized_owner_id.partition(":")[2])
        except ValueError:
            return None

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT id, name
                FROM access_users
                WHERE id = ? AND active = 1 AND deleted = 0
                """,
                (user_id,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            return None
        return {
            "owner_id": f"user:{int(row['id'])}",
            "name": str(row["name"]),
            "role": "user",
        }

    def authenticate(self, access_code: Any) -> dict[str, str] | None:
        normalized_code = str(access_code or "")
        if not normalized_code:
            return None

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT id, name, code_hash
                FROM access_users
                WHERE active = 1 AND deleted = 0
                ORDER BY id
                """
            ).fetchall()
        finally:
            connection.close()

        for row in rows:
            if check_password_hash(row["code_hash"], normalized_code):
                user_id = int(row["id"])
                return {
                    "owner_id": f"user:{user_id}",
                    "name": str(row["name"]),
                    "role": "user",
                }

        return None
