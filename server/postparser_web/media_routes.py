import re

from flask import Blueprint, current_app, send_from_directory

from server.postparser_web.config import get_data_dir


media_bp = Blueprint("media", __name__)
TELEGRAM_PHOTO_FILENAME = re.compile(r"^[0-9a-f]{64}\.jpg$")


@media_bp.get("/media/telegram/<filename>")
def telegram_photo(filename):
    if not TELEGRAM_PHOTO_FILENAME.fullmatch(filename):
        return "", 404

    media_directory = current_app.config.get("TELEGRAM_MEDIA_DIRECTORY")
    if media_directory is None:
        media_directory = get_data_dir() / "media" / "telegram"

    return send_from_directory(
        media_directory,
        filename,
        conditional=True,
        max_age=86400,
    )
