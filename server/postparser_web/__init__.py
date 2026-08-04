import pathlib

from flask import Flask

from server.postparser_web.config import get_settings_database_path
from server.postparser_web.google_sheets_export import (
    GoogleSheetsConfigurationError,
    GoogleSheetsExporter,
)
from server.postparser_web.health_routes import health_bp
from server.postparser_web.instagram_oauth import instagram_oauth_bp
from server.postparser_web.parse_routes import parse_bp
from server.postparser_web.parse_runner import ParseRunnerService
from server.postparser_web.parse_service import ParseService
from server.postparser_web.results_store import ResultsStore
from server.postparser_web.results_routes import results_bp
from server.postparser_web.results_export_routes import results_export_bp
from server.postparser_web.run_routes import run_bp
from server.postparser_web.settings_page import settings_page_blueprint
from server.postparser_web.settings_routes import settings_blueprint
from server.postparser_web.settings_store import SettingsStore
from server.postparser_web.vk_routes import vk_blueprint


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

    results_store = app.config.get("RESULTS_STORE")
    if results_store is None:
        results_database_path = app.config.get("RESULTS_DATABASE_PATH")
        if results_database_path is None:
            settings_database_path = pathlib.Path(
                app.config["SETTINGS_DATABASE_PATH"]
            )
            results_database_path = settings_database_path.with_name(
                "parse_results.sqlite3"
            )

        results_store = ResultsStore(results_database_path)

    app.extensions["results_store"] = results_store

    google_sheets_exporter = app.config.get("GOOGLE_SHEETS_EXPORTER")
    if google_sheets_exporter is None:
        try:
            google_sheets_exporter = GoogleSheetsExporter(
                client_factory=app.config.get(
                    "GOOGLE_SHEETS_CLIENT_FACTORY"
                ),
                spreadsheet_id=app.config.get(
                    "GOOGLE_SHEETS_SPREADSHEET_ID"
                ),
                credentials_path=app.config.get(
                    "GOOGLE_SHEETS_CREDENTIALS_PATH"
                ),
                results_store=results_store,
            )
        except GoogleSheetsConfigurationError:
            google_sheets_exporter = None

    app.extensions["google_sheets_exporter"] = google_sheets_exporter

    parse_runner = app.config.get("PARSE_RUNNER")
    if parse_runner is None:
        parse_service = ParseService(
            settings_store,
            parser_factories=app.config.get("PARSER_FACTORIES"),
        )
        parse_runner = ParseRunnerService(
            settings_store,
            parse_service,
            results_store,
        )
        app.extensions["parse_service"] = parse_service

    app.extensions["parse_runner"] = parse_runner
    app.register_blueprint(health_bp)
    app.register_blueprint(instagram_oauth_bp)
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(settings_page_blueprint)
    app.register_blueprint(vk_blueprint)
    app.register_blueprint(parse_bp)
    app.register_blueprint(run_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(results_export_bp)

    return app
