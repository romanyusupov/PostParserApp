from flask import Flask

from server.postparser_web.config import get_settings_database_path
from server.postparser_web.settings_page import settings_page_blueprint
from server.postparser_web.settings_routes import settings_blueprint
from server.postparser_web.settings_store import SettingsStore


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SETTINGS_DATABASE_PATH=get_settings_database_path()
    )

    if test_config is not None:
        app.config.update(test_config)

    settings_store = SettingsStore(
        app.config["SETTINGS_DATABASE_PATH"]
    )
    app.extensions["settings_store"] = settings_store
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(settings_page_blueprint)

    return app
