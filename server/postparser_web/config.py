import os
import pathlib


SERVER_DIR = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = SERVER_DIR / "data"


def get_data_dir():
    configured_path = os.environ.get(
        "POSTPARSER_DATA_DIR",
        "",
    ).strip()

    if configured_path:
        return pathlib.Path(configured_path)

    return DEFAULT_DATA_DIR


def get_settings_database_path():
    return get_data_dir() / "settings.sqlite3"
