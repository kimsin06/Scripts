import re

import pytest

from parcabul import db, subscription
from parcabul.__main__ import main
from parcabul.web import create_app


@pytest.fixture
def app(tmp_path):
    path = str(tmp_path / "w.db")
    main(["--db", path, "demo"])
    app = create_app(path, secret_key="test")
    app.config["TESTING"] = True
    return app


def csrf(client, url):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(url).get_data(as_text=True)).group(1)


def register(client, email="ali@example.com"):
    token = csrf(client, "/kayit")
    return client.post("/kayit", data={"email": email, "password": "sifre1234", "csrf": token})


def test_guest_sees_only_cheapest_price(app):
    html = app.test_client().get("/ara?kod=DEMO-HF-200").get_data(as_text=True)
    assert "1.149,90 TL" in html and "3 satıcıda" in html
    assert "Demo Parça B" not in html and "demo-b.example" not in html


def test_subscriber_sees_sellers_and_links(app):
    client = app.test_client()
    assert register(client).status_code == 302
    with app.app_context():
        conn = db.connect(app.config["DB_PATH"])
        subscription.extend(conn, db.get_user_by_email(conn, "ali@example.com")["id"], 1)
        conn.commit()
        conn.close()
    html = client.get("/ara?kod=DEMO-HF-200").get_data(as_text=True)
    assert html.index("Demo Parça B") < html.index("Demo Parça A") < html.index("Demo Parça C")
    assert "https://demo-b.example/p/200" in html and "En ucuz" in html


def test_post_without_csrf_rejected(app):
    assert app.test_client().post("/kayit", data={"email": "x@y.z", "password": "sifre1234"}).status_code == 400


def test_login_and_open_redirect_blocked(app):
    client = app.test_client()
    register(client)
    client.post("/cikis", data={"csrf": csrf(client, "/")})
    token = csrf(client, "/giris")
    resp = client.post("/giris?next=//evil.example", data={"email": "ali@example.com", "password": "sifre1234", "csrf": token})
    assert resp.headers["Location"] == "/"


def test_vehicle_pages(app):
    client = app.test_client()
    assert "Renault" in client.get("/arac").get_data(as_text=True)
    html = client.get("/arac/Renault").get_data(as_text=True)
    vid = re.search(r"/arac/v/(\d+)", html).group(1)
    assert "DEMO-YF-100" in client.get(f"/arac/v/{vid}").get_data(as_text=True)
    assert client.get("/arac/Yok").status_code == 404


def test_plan_requires_login(app):
    assert app.test_client().get("/abonelik").status_code == 302
