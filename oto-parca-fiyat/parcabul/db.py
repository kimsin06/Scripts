"""SQLite veritabanı: satıcılar, parçalar, teklifler, araçlar, kullanıcılar, abonelikler."""

import sqlite3
from datetime import datetime, timedelta, timezone

from .codes import normalize_code

SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    website TEXT
);

CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,          -- normalize edilmiş kod (aramada kullanılır)
    display_code TEXT NOT NULL,         -- ilk görülen yazılış
    name TEXT,
    brand TEXT
);

-- OEM kodu <-> muadil (yan sanayi) kodu eşleşmeleri. Aramada ikisi de listelenir.
CREATE TABLE IF NOT EXISTS code_equivalents (
    code_a TEXT NOT NULL,
    code_b TEXT NOT NULL,
    PRIMARY KEY (code_a, code_b)
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    part_id INTEGER NOT NULL REFERENCES parts(id),
    seller_id INTEGER NOT NULL REFERENCES sellers(id),
    url TEXT NOT NULL,
    title TEXT,
    price_kurus INTEGER NOT NULL,
    in_stock INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE (part_id, seller_id, url)
);

CREATE TABLE IF NOT EXISTS price_history (
    offer_id INTEGER NOT NULL REFERENCES offers(id),
    price_kurus INTEGER NOT NULL,
    seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year_from INTEGER,
    year_to INTEGER,
    engine TEXT NOT NULL DEFAULT '',
    UNIQUE (make, model, year_from, year_to, engine)
);

CREATE TABLE IF NOT EXISTS part_vehicles (
    part_id INTEGER NOT NULL REFERENCES parts(id),
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    PRIMARY KEY (part_id, vehicle_id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    amount_kurus INTEGER NOT NULL,
    payment_ref TEXT
);

CREATE INDEX IF NOT EXISTS idx_offers_part ON offers(part_id);
CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);
"""


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


# --- Satıcı / parça / teklif ---------------------------------------------

def get_or_create_seller(conn, name, website=None):
    row = conn.execute("SELECT id FROM sellers WHERE name = ?", (name,)).fetchone()
    if row:
        if website:
            conn.execute("UPDATE sellers SET website = ? WHERE id = ?", (website, row["id"]))
        return row["id"]
    return conn.execute(
        "INSERT INTO sellers (name, website) VALUES (?, ?)", (name, website)
    ).lastrowid


def get_or_create_part(conn, code, name=None, brand=None):
    norm = normalize_code(code)
    if not norm:
        raise ValueError(f"Geçersiz parça kodu: {code!r}")
    row = conn.execute("SELECT id, name, brand FROM parts WHERE code = ?", (norm,)).fetchone()
    if row:
        if (name and not row["name"]) or (brand and not row["brand"]):
            conn.execute(
                "UPDATE parts SET name = COALESCE(name, ?), brand = COALESCE(brand, ?) WHERE id = ?",
                (name, brand, row["id"]),
            )
        return row["id"]
    return conn.execute(
        "INSERT INTO parts (code, display_code, name, brand) VALUES (?, ?, ?, ?)",
        (norm, str(code).strip(), name, brand),
    ).lastrowid


def upsert_offer(conn, part_id, seller_id, url, price_kurus, title=None, in_stock=True, now=None):
    """Teklifi ekler/günceller. Fiyat değiştiyse fiyat geçmişine yazar."""
    now = iso(now or utcnow())
    row = conn.execute(
        "SELECT id, price_kurus FROM offers WHERE part_id = ? AND seller_id = ? AND url = ?",
        (part_id, seller_id, url),
    ).fetchone()
    if row:
        offer_id = row["id"]
        conn.execute(
            "UPDATE offers SET price_kurus = ?, title = ?, in_stock = ?, updated_at = ? WHERE id = ?",
            (price_kurus, title, int(bool(in_stock)), now, offer_id),
        )
        changed = row["price_kurus"] != price_kurus
    else:
        offer_id = conn.execute(
            "INSERT INTO offers (part_id, seller_id, url, title, price_kurus, in_stock, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (part_id, seller_id, url, title, price_kurus, int(bool(in_stock)), now),
        ).lastrowid
        changed = True
    if changed:
        conn.execute(
            "INSERT INTO price_history (offer_id, price_kurus, seen_at) VALUES (?, ?, ?)",
            (offer_id, price_kurus, now),
        )
    return offer_id


def add_equivalent(conn, code_a, code_b):
    a, b = normalize_code(code_a), normalize_code(code_b)
    if not a or not b or a == b:
        raise ValueError("İki farklı, geçerli kod gerekli")
    conn.execute("INSERT OR IGNORE INTO code_equivalents VALUES (?, ?)", (a, b))
    conn.execute("INSERT OR IGNORE INTO code_equivalents VALUES (?, ?)", (b, a))


def equivalent_codes(conn, code):
    norm = normalize_code(code)
    rows = conn.execute("SELECT code_b FROM code_equivalents WHERE code_a = ?", (norm,))
    return [norm] + sorted(r["code_b"] for r in rows)


def search_offers(conn, code, max_age_days=7, now=None):
    """Kod (ve muadilleri) için güncel teklifler; stoktakiler önce, ucuzdan pahalıya."""
    codes = equivalent_codes(conn, code)
    if not codes[0]:
        return []
    cutoff = iso((now or utcnow()) - timedelta(days=max_age_days))
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""
        SELECT o.id, o.url, o.title, o.price_kurus, o.in_stock, o.updated_at,
               s.name AS seller, s.website,
               p.code, p.display_code, p.name AS part_name, p.brand,
               (p.code != ?) AS is_equivalent
        FROM offers o
        JOIN parts p ON p.id = o.part_id
        JOIN sellers s ON s.id = o.seller_id
        WHERE p.code IN ({marks}) AND o.updated_at >= ?
        ORDER BY o.in_stock DESC, o.price_kurus ASC, s.name ASC
        """,
        (codes[0], *codes, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def price_history(conn, offer_id):
    return [dict(r) for r in conn.execute(
        "SELECT price_kurus, seen_at FROM price_history WHERE offer_id = ? ORDER BY seen_at",
        (offer_id,),
    )]


def all_part_codes(conn):
    return [r["code"] for r in conn.execute("SELECT code FROM parts ORDER BY code")]


# --- Araç uyumluluğu -----------------------------------------------------

def get_or_create_vehicle(conn, make, model, year_from=None, year_to=None, engine=""):
    make, model, engine = make.strip(), model.strip(), (engine or "").strip()
    row = conn.execute(
        "SELECT id FROM vehicles WHERE make = ? AND model = ? AND year_from IS ? AND year_to IS ? AND engine = ?",
        (make, model, year_from, year_to, engine),
    ).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO vehicles (make, model, year_from, year_to, engine) VALUES (?, ?, ?, ?, ?)",
        (make, model, year_from, year_to, engine),
    ).lastrowid


def link_part_vehicle(conn, part_id, vehicle_id):
    conn.execute("INSERT OR IGNORE INTO part_vehicles VALUES (?, ?)", (part_id, vehicle_id))


def list_makes(conn):
    return [r["make"] for r in conn.execute("SELECT DISTINCT make FROM vehicles ORDER BY make")]


def list_vehicles(conn, make):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM vehicles WHERE make = ? ORDER BY model, year_from, engine", (make,)
    )]


def get_vehicle(conn, vehicle_id):
    row = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    return dict(row) if row else None


def parts_for_vehicle(conn, vehicle_id, max_age_days=7, now=None):
    """Araca uyan parçalar ve her birinin en ucuz stoktaki fiyatı."""
    cutoff = iso((now or utcnow()) - timedelta(days=max_age_days))
    return [dict(r) for r in conn.execute(
        """
        SELECT p.id, p.code, p.display_code, p.name, p.brand,
               MIN(CASE WHEN o.in_stock = 1 AND o.updated_at >= ? THEN o.price_kurus END) AS min_price,
               COUNT(DISTINCT CASE WHEN o.updated_at >= ? THEN o.seller_id END) AS seller_count
        FROM part_vehicles pv
        JOIN parts p ON p.id = pv.part_id
        LEFT JOIN offers o ON o.part_id = p.id
        WHERE pv.vehicle_id = ?
        GROUP BY p.id
        ORDER BY p.name, p.code
        """,
        (cutoff, cutoff, vehicle_id),
    )]


# --- Kullanıcı / abonelik ------------------------------------------------

def create_user(conn, email, password_hash, is_admin=False):
    return conn.execute(
        "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (email.strip().lower(), password_hash, int(is_admin), iso(utcnow())),
    ).lastrowid


def get_user_by_email(conn, email):
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


def get_user(conn, user_id):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None
