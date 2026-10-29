"""Kaynaklardan teklifleri toplayıp veritabanına yazar."""

import csv

from . import db


def collect(conn, sources, codes=None, log=print):
    """Her kaynağı çalıştırır. Kod listesi verilmezse veritabanındaki tüm kodlar
    (site araması yapan kaynaklar için) kullanılır."""
    total = 0
    for src in sources:
        seller_id = db.get_or_create_seller(conn, src.seller, src.website)
        src_codes = codes
        if src.needs_codes and not src_codes:
            src_codes = db.all_part_codes(conn)
        count = 0
        try:
            for offer in src.offers(src_codes):
                part_id = db.get_or_create_part(conn, offer.code, offer.name, offer.brand)
                db.upsert_offer(conn, part_id, seller_id, offer.url, offer.price_kurus,
                                title=offer.name, in_stock=offer.in_stock)
                count += 1
        except Exception as exc:  # bir satıcı bozuksa diğerleri devam etsin
            log(f"[HATA] {src.seller}: {exc}")
        conn.commit()
        log(f"{src.seller}: {count} teklif")
        total += count
    return total


def import_fitment(conn, path):
    """Araç uyumluluk CSV'si: code,make,model,year_from,year_to,engine"""
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            part_id = db.get_or_create_part(conn, row["code"])
            vehicle_id = db.get_or_create_vehicle(
                conn, row["make"], row["model"],
                int(row["year_from"]) if row.get("year_from") else None,
                int(row["year_to"]) if row.get("year_to") else None,
                row.get("engine", ""),
            )
            db.link_part_vehicle(conn, part_id, vehicle_id)
            n += 1
    conn.commit()
    return n


def import_equivalents(conn, path):
    """Muadil kod CSV'si: code,equivalent"""
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            db.add_equivalent(conn, row["code"], row["equivalent"])
            n += 1
    conn.commit()
    return n
