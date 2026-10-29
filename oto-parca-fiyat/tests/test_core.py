import os
from datetime import datetime, timedelta, timezone

import pytest

from parcabul import collector, db, subscription
from parcabul.sources import HtmlSearchSource, load_sources

ORNEK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ornek")


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def demo(conn):
    collector.collect(conn, load_sources(os.path.join(ORNEK, "kaynaklar.json")), log=lambda *_: None)
    collector.import_fitment(conn, os.path.join(ORNEK, "uyumluluk.csv"))
    collector.import_equivalents(conn, os.path.join(ORNEK, "muadil.csv"))
    return conn


def test_cheapest_across_feeds_and_code_spellings(demo):
    offers = db.search_offers(demo, "demo hf 200")
    # C stokta yok -> fiyatı yüksek olmasa da en sona düşer
    assert [(o["seller"], o["price_kurus"], o["in_stock"]) for o in offers] == [
        ("Demo Parça B", 114990, 1), ("Demo Parça A", 124900, 1), ("Demo Parça C", 129900, 0),
    ]


def test_out_of_stock_not_cheapest(demo):
    offers = db.search_offers(demo, "DEMO-BB-300")
    assert offers[0]["seller"] == "Demo Parça B"
    assert offers[-1]["seller"] == "Demo Parça A" and not offers[-1]["in_stock"]


def test_equivalent_codes_included(demo):
    offers = db.search_offers(demo, "DEMO-YF-100")
    assert offers[0]["code"] == "MUADILYF900" and offers[0]["is_equivalent"]
    assert {o["seller"] for o in offers if not o["is_equivalent"]} == {"Demo Parça A", "Demo Parça B", "Demo Parça C"}


def test_stale_offers_hidden(demo):
    later = datetime.now(timezone.utc) + timedelta(days=30)
    assert db.search_offers(demo, "DEMO-YF-100", now=later) == []


def test_price_history_records_changes(conn):
    seller = db.get_or_create_seller(conn, "S")
    part = db.get_or_create_part(conn, "X-1")
    oid = db.upsert_offer(conn, part, seller, "u", 1000)
    db.upsert_offer(conn, part, seller, "u", 1000)
    db.upsert_offer(conn, part, seller, "u", 900)
    assert [h["price_kurus"] for h in db.price_history(conn, oid)] == [1000, 900]


def test_parts_for_vehicle(demo):
    clio = next(v for v in db.list_vehicles(demo, "Renault") if v["model"] == "Clio")
    parts = {p["code"]: p for p in db.parts_for_vehicle(demo, clio["id"])}
    assert set(parts) == {"DEMOYF100", "DEMOHF200", "DEMOBB300"}
    assert parts["DEMOYF100"]["min_price"] == 36500
    assert parts["DEMOHF200"]["seller_count"] == 3
    assert db.list_makes(demo) == ["Dacia", "Fiat", "Renault"]


def test_subscription_extends_from_end(conn):
    uid = db.create_user(conn, "a@b.c", "x")
    now = datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert not subscription.is_active(conn, uid, now)
    assert subscription.extend(conn, uid, 1, now=now) == datetime(2026, 2, 28, tzinfo=timezone.utc)
    assert subscription.extend(conn, uid, 2, now=now) == datetime(2026, 4, 28, tzinfo=timezone.utc)
    assert subscription.is_active(conn, uid, datetime(2026, 4, 27, tzinfo=timezone.utc))
    assert not subscription.is_active(conn, uid, datetime(2026, 4, 29, tzinfo=timezone.utc))


def test_html_search_source(tmp_path):
    page = tmp_path / "ara.html"
    page.write_text("""
      <div class="p"><span class="t">Yağ Filtresi 8200 768 913</span><span class="f">1.050,00 TL</span><a href="/u/1">x</a></div>
      <div class="p"><span class="t">Benzer ürün 1111</span><span class="f">10,00 TL</span><a href="/u/2">x</a></div>
      <div class="p"><span class="t">8200-768-913 Stokta yok</span><span class="f">900 TL</span><a href="/u/3">x</a><i class="s">Tükendi</i></div>
    """, encoding="utf-8")
    src = HtmlSearchSource({
        "seller": "Site", "search_url": str(page), "delay": 0,
        "selectors": {"item": ".p", "name": ".t", "price": ".f", "url": "a@href", "stock": ".s"},
    })
    offers = list(src.offers(["8200768913"]))
    assert [(o.price_kurus, o.in_stock) for o in offers] == [(105000, True), (90000, False)]
