from flask import Blueprint, redirect, render_template, url_for


settings_page_blueprint = Blueprint(
    "settings_page",
    __name__,
)


@settings_page_blueprint.get("/")
def home_page():
    return redirect(url_for("settings_page.settings_page"))


@settings_page_blueprint.get("/shadow/settings")
def settings_page():
    return render_template(
        "settings.html",
        active_section="settings",
    )
