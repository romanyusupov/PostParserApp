import datetime
import hashlib
import pathlib
import secrets
import sqlite3
from typing import Any


SETUP_TOKEN_BYTES = 32
SETUP_TOKEN_TTL_SECONDS = 48 * 60 * 60
OAUTH_STATE_BYTES = 32
OAUTH_STATE_TTL_SECONDS = 15 * 60


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _normalized_now(value: Any = None) -> datetime.datetime:
    if value is None:
        return _utc_now()
    if not isinstance(value, datetime.datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _timestamp(value: datetime.datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _token_hash(value: Any) -> str:
    normalized = str(value or "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class InstagramOAuthInvitationStore:
    SQLITE_TIMEOUT_SECONDS = 5.0

    def __init__(self, database_path: Any):
        self.database_path = pathlib.Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS instagram_oauth_invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    claimed_at TEXT NOT NULL DEFAULT '',
                    used_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS instagram_oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    invitation_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (invitation_id)
                        REFERENCES instagram_oauth_invitations(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_instagram_oauth_expiry
                ON instagram_oauth_invitations (expires_at);
                """
            )
            connection.commit()
        finally:
            connection.close()

    def create_setup_invitation(
        self,
        *,
        now: Any = None,
        ttl_seconds: int = SETUP_TOKEN_TTL_SECONDS,
    ) -> dict[str, Any]:
        created_at = _normalized_now(now)
        expires_at = created_at + datetime.timedelta(seconds=ttl_seconds)
        setup_token = secrets.token_urlsafe(SETUP_TOKEN_BYTES)

        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                INSERT INTO instagram_oauth_invitations (
                    token_hash,
                    created_at,
                    expires_at
                ) VALUES (?, ?, ?)
                """,
                (
                    _token_hash(setup_token),
                    _timestamp(created_at),
                    _timestamp(expires_at),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        return {
            "id": int(cursor.lastrowid),
            "setup_token": setup_token,
            "expires_at": _timestamp(expires_at),
        }

    def create_oauth_state(
        self,
        setup_token: Any,
        *,
        now: Any = None,
        state_ttl_seconds: int = OAUTH_STATE_TTL_SECONDS,
    ) -> str | None:
        normalized_token = str(setup_token or "").strip()
        if not normalized_token:
            return None

        created_at = _normalized_now(now)
        state_expires_at = created_at + datetime.timedelta(
            seconds=state_ttl_seconds
        )
        oauth_state = secrets.token_urlsafe(OAUTH_STATE_BYTES)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            invitation = connection.execute(
                """
                SELECT id
                FROM instagram_oauth_invitations
                WHERE token_hash = ?
                  AND expires_at > ?
                  AND used_at = ''
                """,
                (
                    _token_hash(normalized_token),
                    _timestamp(created_at),
                ),
            ).fetchone()
            if invitation is None:
                connection.rollback()
                return None

            invitation_id = int(invitation["id"])
            connection.execute(
                """
                INSERT INTO instagram_oauth_states (
                    state_hash,
                    invitation_id,
                    created_at,
                    expires_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    _token_hash(oauth_state),
                    invitation_id,
                    _timestamp(created_at),
                    _timestamp(state_expires_at),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        return oauth_state

    def is_setup_token_valid(
        self,
        setup_token: Any,
        *,
        now: Any = None,
    ) -> bool:
        """Проверяет приглашение без изменения его состояния."""
        normalized_token = str(setup_token or "").strip()
        if not normalized_token:
            return False

        checked_at = _normalized_now(now)
        connection = self._connect()
        try:
            invitation = connection.execute(
                """
                SELECT 1
                FROM instagram_oauth_invitations
                WHERE token_hash = ?
                  AND expires_at > ?
                  AND used_at = ''
                """,
                (
                    _token_hash(normalized_token),
                    _timestamp(checked_at),
                ),
            ).fetchone()
            return invitation is not None
        finally:
            connection.close()

    def consume_state(
        self,
        oauth_state: Any,
        *,
        now: Any = None,
    ) -> int | None:
        normalized_state = str(oauth_state or "").strip()
        if not normalized_state:
            return None

        consumed_at = _normalized_now(now)
        stale_claim_before = consumed_at - datetime.timedelta(
            seconds=OAUTH_STATE_TTL_SECONDS
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT states.state_hash, states.invitation_id
                FROM instagram_oauth_states AS states
                JOIN instagram_oauth_invitations AS invitations
                  ON invitations.id = states.invitation_id
                WHERE states.state_hash = ?
                  AND states.expires_at > ?
                  AND states.consumed_at = ''
                  AND invitations.used_at = ''
                """,
                (
                    _token_hash(normalized_state),
                    _timestamp(consumed_at),
                ),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None

            claimed = connection.execute(
                """
                UPDATE instagram_oauth_invitations
                SET claimed_at = ?
                WHERE id = ?
                  AND used_at = ''
                  AND (claimed_at = '' OR claimed_at <= ?)
                """,
                (
                    _timestamp(consumed_at),
                    int(row["invitation_id"]),
                    _timestamp(stale_claim_before),
                ),
            )
            if claimed.rowcount != 1:
                connection.rollback()
                return None

            updated = connection.execute(
                """
                UPDATE instagram_oauth_states
                SET consumed_at = ?
                WHERE state_hash = ? AND consumed_at = ''
                """,
                (_timestamp(consumed_at), row["state_hash"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
            return int(row["invitation_id"])
        finally:
            connection.close()

    def release_invitation_claim(self, invitation_id: Any) -> bool:
        try:
            normalized_id = int(invitation_id)
        except (TypeError, ValueError):
            return False
        if normalized_id <= 0:
            return False

        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE instagram_oauth_invitations
                SET claimed_at = ''
                WHERE id = ? AND used_at = '' AND claimed_at != ''
                """,
                (normalized_id,),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def mark_invitation_used(
        self,
        invitation_id: Any,
        *,
        now: Any = None,
    ) -> bool:
        try:
            normalized_id = int(invitation_id)
        except (TypeError, ValueError):
            return False
        if normalized_id <= 0:
            return False

        used_at = _normalized_now(now)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE instagram_oauth_invitations
                SET used_at = ?
                WHERE id = ? AND claimed_at != '' AND used_at = ''
                """,
                (_timestamp(used_at), normalized_id),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()
