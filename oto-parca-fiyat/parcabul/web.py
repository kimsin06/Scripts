"""Web sitesi: kod ile arama, araca göre parça listesi, üyelik ve aylık abonelik."""

import os
import secrets
import sqlite3
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, subscription
from .codes import format_price, normalize_code


def create_app(db_path=None, secret_key=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or os.environ.get("PARCABUL_DB", "parcabul.db")
    app.config["SECRET_KEY"] = secret_key or os.environ.get("PARCABUL_SECRET_KEY") or secrets.token_hex(32)
    app.config["PAYMENT_INFO"] = os.environ.get(
        "PARCABUL_ODEME_BILGISI",
        "Ödemeyi havale/EFT ile yapıp açıklamaya e-posta adresinizi yazın; "
        "aboneliğiniz onaylandığında aktif olur.",
    )
    app.jinja_env.filters["fiyat"] = format_price

    conn = db.connect(app.config["DB_PATH"])
    db.init_db(conn)
    conn.close()

    def get_db():
        if "db" not in g:
            g.db = db.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def current_user():
        uid = session.get("user_id")
        return db.get_user(get_db(), uid) if uid else None

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            token = session.get("csrf")
            if not token or not secrets.compare_digest(request.form.get("csrf", ""), token):
                abort(400)

    @app.context_processor
    def inject():
        user = current_user()
        active = subscription.active_until(get_db(), user["id"]) if user else None
        return {"user": user, "sub_until": active, "csrf_token": csrf_token,
                "monthly_fee": subscription.monthly_fee_kurus()}

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login", next=request.full_path))
            return view(*args, **kwargs)
        return wrapper

    @app.route("/")
    def index():
        return render_template("index.html", makes=db.list_makes(get_db()))

    @app.route("/ara")
    def search():
        code = request.args.get("kod", "").strip()
        if not normalize_code(code):
            return redirect(url_for("index"))
        conn = get_db()
        offers = db.search_offers(conn, code)
        user = current_user()
        subscribed = bool(user and subscription.is_active(conn, user["id"]))
        return render_template("search.html", code=code, offers=offers, subscribed=subscribed,
                               sellers=len({o["seller"] for o in offers}))

    @app.route("/arac")
    @app.route("/arac/<make>")
    def vehicles(make=None):
        conn = get_db()
        if make is None:
            return render_template("makes.html", makes=db.list_makes(conn))
        vehicles = db.list_vehicles(conn, make)
        if not vehicles:
            abort(404)
        return render_template("vehicles.html", make=make, vehicles=vehicles)

    @app.route("/arac/v/<int:vehicle_id>")
    def vehicle_parts(vehicle_id):
        conn = get_db()
        vehicle = db.get_vehicle(conn, vehicle_id)
        if not vehicle:
            abort(404)
        user = current_user()
        subscribed = bool(user and subscription.is_active(conn, user["id"]))
        return render_template("vehicle_parts.html", vehicle=vehicle, subscribed=subscribed,
                               parts=db.parts_for_vehicle(conn, vehicle_id))

    @app.route("/kayit", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            if "@" not in email or len(password) < 8:
                flash("Geçerli bir e-posta ve en az 8 karakterli şifre girin.")
            else:
                conn = get_db()
                try:
                    uid = db.create_user(conn, email, generate_password_hash(password))
                    conn.commit()
                except sqlite3.IntegrityError:
                    flash("Bu e-posta ile kayıtlı bir hesap var.")
                else:
                    session.clear()
                    session["user_id"] = uid
                    return redirect(url_for("plan"))
        return render_template("auth.html", mode="kayit")

    @app.route("/giris", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = db.get_user_by_email(get_db(), request.form.get("email", ""))
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear()
                session["user_id"] = user["id"]
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("index"))
            flash("E-posta veya şifre hatalı.")
        return render_template("auth.html", mode="giris")

    @app.route("/cikis", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/abonelik")
    @login_required
    def plan():
        return render_template("plan.html", payment_info=app.config["PAYMENT_INFO"])

    return app
