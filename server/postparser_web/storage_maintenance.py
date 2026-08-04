import datetime
import logging
import pathlib
import re
import urllib.parse
from typing import Any

import click


LOGGER = logging.getLogger(__name__)
TELEGRAM_PHOTO_NAME = re.compile(r"^[0-9a-f]{64}\.jpg$")


class StorageRetentionService:
    def __init__(
        self,
        results_store: Any,
        telegram_media_directory: Any,
        runs_per_group: int = 3,
        media_grace_days: int = 7,
        now_factory=None,
    ):
        self._results_store = results_store
        self._media_directory = pathlib.Path(telegram_media_directory)
        self._runs_per_group = int(runs_per_group)
        self._media_grace_days = int(media_grace_days)
        self._now_factory = now_factory or (
            lambda: datetime.datetime.now(datetime.timezone.utc)
        )

    @staticmethod
    def _telegram_photo_name(image_url: Any) -> str | None:
        path = urllib.parse.urlsplit(str(image_url or "")).path
        parts = pathlib.PurePosixPath(path).parts
        if len(parts) < 3 or parts[-3:-1] != ("media", "telegram"):
            return None
        name = parts[-1]
        return name if TELEGRAM_PHOTO_NAME.fullmatch(name) else None

    def _referenced_photo_names(self) -> set[str]:
        return {
            name
            for image_url in self._results_store.list_image_urls()
            if (name := self._telegram_photo_name(image_url)) is not None
        }

    def remove_unreferenced_media(self) -> int:
        if not self._media_directory.is_dir():
            return 0

        referenced_names = self._referenced_photo_names()
        cutoff = self._now_factory() - datetime.timedelta(
            days=self._media_grace_days
        )
        deleted_count = 0

        for path in self._media_directory.iterdir():
            if (
                path.is_symlink()
                or not path.is_file()
                or not TELEGRAM_PHOTO_NAME.fullmatch(path.name)
                or path.name in referenced_names
            ):
                continue
            modified_at = datetime.datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=datetime.timezone.utc,
            )
            if modified_at > cutoff:
                continue
            path.unlink()
            deleted_count += 1

        return deleted_count

    def cleanup_group(self, group_id: Any) -> dict[str, int]:
        deleted_runs = self._results_store.prune_group_runs(
            group_id,
            self._runs_per_group,
        )
        deleted_media = self.remove_unreferenced_media()
        return {
            "deleted_runs": deleted_runs,
            "deleted_media": deleted_media,
        }

    def maintain_all(self) -> dict[str, int]:
        deleted_runs = self._results_store.prune_all_group_runs(
            self._runs_per_group
        )
        deleted_media = self.remove_unreferenced_media()
        self._results_store.maintain_database()
        return {
            "deleted_runs": deleted_runs,
            "deleted_media": deleted_media,
        }


def register_storage_maintenance_command(app) -> None:
    @app.cli.command("maintain-storage")
    def maintain_storage() -> None:
        """Prune old runs/media and compact the results database."""
        retention = app.extensions["storage_retention"]
        result = retention.maintain_all()
        click.echo(
            "Storage maintenance completed: "
            f"deleted_runs={result['deleted_runs']}, "
            f"deleted_media={result['deleted_media']}"
        )


def cleanup_after_success(retention: Any, group_id: str) -> None:
    try:
        result = retention.cleanup_group(group_id)
    except Exception:
        LOGGER.exception(
            "Storage retention failed after a successful parser run."
        )
        return

    if result["deleted_runs"] or result["deleted_media"]:
        LOGGER.info(
            "Storage retention completed: deleted_runs=%s, deleted_media=%s.",
            result["deleted_runs"],
            result["deleted_media"],
        )
