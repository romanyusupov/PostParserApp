from flask import Blueprint, render_template


settings_page_blueprint = Blueprint(
    "settings_page",
    __name__,
)


@settings_page_blueprint.get("/shadow/settings")
def settings_page():
    return render_template(
        "settings.html",
        active_section="settings",
    )
