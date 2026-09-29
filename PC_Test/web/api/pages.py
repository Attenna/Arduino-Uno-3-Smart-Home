"""页面路由。"""
from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return render_template("dashboard.html")


@bp.route("/history")
def history_page():
    return render_template("history.html")


@bp.route("/access")
def access_page():
    return render_template("access.html")


@bp.route("/hardware")
def hardware_page():
    return render_template("hardware.html")
