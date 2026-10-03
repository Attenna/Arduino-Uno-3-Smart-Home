"""页面路由。"""
from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return render_template("dashboard.html")


@bp.route("/rooms")
def rooms_page():
    return render_template("rooms.html")


@bp.route("/settings")
def settings_page():
    return render_template("settings.html")


@bp.route("/login")
def login_page():
    return render_template("login.html")


@bp.route("/history")
def history_page():
    return render_template("history.html")


@bp.route("/access")
def access_page():
    return render_template("access.html")


@bp.route("/hardware")
def hardware_page():
    return render_template("hardware.html")


@bp.route("/voice")
def voice_page():
    return render_template("voice.html")


@bp.route("/automation")
def automation_page():
    return render_template("automation.html")
