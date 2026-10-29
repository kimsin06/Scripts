"""Satıcı kaynakları: ürün feed'leri (XML/JSON/CSV) ve site içi kod araması (HTML).

Cimri gibi siteler fiyatların çoğunu satıcıların verdiği XML/JSON ürün
feed'lerinden alır; bu en güvenilir ve hukuken temiz yoldur. Feed'i olmayan
satıcılar için "html_search" kaynağı satıcının arama sayfasında parça kodunu
aratır, robots.txt'ye uyar ve istekler arasında bekler.
"""

import csv
import io
import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from .codes import normalize_code, parse_price

USER_AGENT = "ParcaBulBot/0.1 (+fiyat karsilastirma; iletisim icin sitemize bakin)"


@dataclass
class Offer:
    code: str
    price_kurus: int
    url: str
    name: str = None
    brand: str = None
    in_stock: bool = True


def fetch(url, timeout=20):
    """URL'den (veya yerel dosyadan) içerik getirir."""
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        with open(parsed.path if parsed.scheme else url, "rb") as f:
            return f.read()
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


_STOCK_FALSE = {"0", "false", "hayir", "hayır", "yok", "no", "tukendi", "tükendi", "stokta yok", "out of stock"}


def _parse_stock(value):
    if value is None or value == "":
        return True
    text = str(value).strip().lower()
    if text in _STOCK_FALSE:
        return False
    try:
        return float(text.replace(",", ".")) > 0
    except ValueError:
        return True


class FeedSource:
    """Satıcının ürün feed'i. fields: feed alan adlarını bizim alanlara eşler.

    {"type": "feed", "seller": "...", "url": "...", "format": "xml|json|csv",
     "item_path": "product", "fields": {"code": "oem", "price": "fiyat", "url": "link",
     "name": "baslik", "brand": "marka", "stock": "stok"}}
    """

    needs_codes = False

    def __init__(self, cfg, base_dir="."):
        self.seller = cfg["seller"]
        self.website = cfg.get("website")
        self.url = cfg["url"]
        if urlparse(self.url).scheme == "" and not os.path.isabs(self.url):
            self.url = os.path.join(base_dir, self.url)
        self.format = cfg.get("format", "xml").lower()
        self.item_path = cfg.get("item_path", "product")
        self.fields = {"code": "code", "price": "price", "url": "url",
                       "name": "name", "brand": "brand", "stock": "stock"}
        self.fields.update(cfg.get("fields", {}))

    def _items(self, data):
        if self.format == "xml":
            root = ET.fromstring(data)
            for el in root.iter(self.item_path):
                yield lambda key, el=el: (el.findtext(key) or "").strip() or None
        elif self.format == "json":
            items = json.loads(data)
            if isinstance(items, dict):
                for key in filter(None, self.item_path.split(".")):
                    items = items[key]
            for item in items:
                yield lambda key, item=item: item.get(key)
        elif self.format == "csv":
            text = data.decode("utf-8-sig")
            delimiter = ";" if text.count(";") > text.count(",") else ","
            for row in csv.DictReader(io.StringIO(text), delimiter=delimiter):
                yield lambda key, row=row: (row.get(key) or "").strip() or None
        else:
            raise ValueError(f"Bilinmeyen feed formatı: {self.format}")

    def offers(self, codes=None):
        wanted = {normalize_code(c) for c in codes} if codes else None
        f = self.fields
        for get in self._items(fetch(self.url)):
            code, price = get(f["code"]), parse_price(get(f["price"]))
            url = get(f["url"])
            if not code or not normalize_code(code) or price is None or not url:
                continue
            if wanted is not None and normalize_code(code) not in wanted:
                continue
            yield Offer(code=str(code), price_kurus=price, url=url, name=get(f["name"]),
                        brand=get(f["brand"]), in_stock=_parse_stock(get(f["stock"])))


class HtmlSearchSource:
    """Satıcının sitesinde parça kodunu aratır ve sonuç sayfasını CSS seçicilerle okur.

    {"type": "html_search", "seller": "...", "search_url": "https://site/ara?q={code}",
     "delay": 3, "selectors": {"item": ".urun", "name": ".baslik", "price": ".fiyat",
     "url": "a@href", "code": ".oem-kodu", "stock": ".stok"}}

    "code" seçicisi yoksa, aranan kod ürün başlığında geçmiyorsa sonuç atlanır
    (sitelerin alakasız "benzer ürün" sonuçlarını elemek için).
    """

    needs_codes = True

    def __init__(self, cfg, base_dir="."):
        self.seller = cfg["seller"]
        self.website = cfg.get("website")
        self.search_url = cfg["search_url"]
        self.selectors = cfg["selectors"]
        self.delay = float(cfg.get("delay", 3))
        self._robots = {}
        self._last_request = 0.0

    def _allowed(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return True
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._robots:
            rp = RobotFileParser(host + "/robots.txt")
            try:
                rp.parse(fetch(host + "/robots.txt").decode("utf-8", "replace").splitlines())
            except Exception:
                rp.parse([])  # robots.txt yoksa her şey serbest
            self._robots[host] = rp
        return self._robots[host].can_fetch(USER_AGENT, url)

    def _select(self, el, selector):
        if not selector:
            return None
        css, _, attr = selector.partition("@")
        node = el.select_one(css) if css else el
        if node is None:
            return None
        value = node.get(attr) if attr else node.get_text(" ", strip=True)
        return value.strip() if isinstance(value, str) else value

    def offers(self, codes=None):
        from bs4 import BeautifulSoup  # yalnızca bu kaynak tipi bs4 ister
        for code in codes or []:
            url = self.search_url.replace("{code}", quote(str(code)))
            if not self._allowed(url):
                continue
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                html = fetch(url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            s = self.selectors
            for item in soup.select(s["item"]):
                name = self._select(item, s.get("name"))
                price = parse_price(self._select(item, s.get("price")))
                link = self._select(item, s.get("url"))
                if price is None or not link:
                    continue
                if s.get("code"):
                    found = self._select(item, s["code"])
                    if normalize_code(found) != normalize_code(code):
                        continue
                elif normalize_code(code) not in normalize_code(name or ""):
                    continue
                stock = self._select(item, s.get("stock")) if s.get("stock") else None
                yield Offer(code=str(code), price_kurus=price, url=urljoin(url, link),
                            name=name, in_stock=_parse_stock(stock))


SOURCE_TYPES = {"feed": FeedSource, "html_search": HtmlSearchSource}


def load_sources(config_path):
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(config_path))
    return [SOURCE_TYPES[s["type"]](s, base_dir) for s in cfg["sources"] if s.get("enabled", True)]
