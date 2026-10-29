"""Komut satırı: python -m parcabul <komut>"""

import argparse
import os
import sys

from . import collector, db, subscription
from .codes import format_price
from .sources import load_sources

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_DIR = os.path.join(os.path.dirname(HERE), "ornek")


def main(argv=None):
    p = argparse.ArgumentParser(prog="parcabul", description="Oto yedek parça fiyat karşılaştırma")
    p.add_argument("--db", default=os.environ.get("PARCABUL_DB", "parcabul.db"))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Veritabanını oluştur")

    c = sub.add_parser("topla", help="Satıcı kaynaklarından fiyatları topla")
    c.add_argument("config", help="Kaynak ayar dosyası (JSON)")
    c.add_argument("--kod", nargs="*", help="Sadece bu kodlar")

    c = sub.add_parser("ara", help="Kod ile en ucuz teklifleri listele")
    c.add_argument("kod")

    c = sub.add_parser("uyumluluk", help="Araç uyumluluk CSV'si yükle (code,make,model,year_from,year_to,engine)")
    c.add_argument("csv")

    c = sub.add_parser("muadil", help="Muadil kod CSV'si yükle (code,equivalent)")
    c.add_argument("csv")

    c = sub.add_parser("abonelik-ver", help="Ödeme alınan kullanıcının aboneliğini uzat")
    c.add_argument("email")
    c.add_argument("--ay", type=int, default=1)
    c.add_argument("--ref", help="Ödeme referansı (dekont no vb.)")

    sub.add_parser("demo", help="Örnek verilerle veritabanını doldur")

    c = sub.add_parser("sunucu", help="Web sitesini başlat (geliştirme sunucusu)")
    c.add_argument("--host", default="127.0.0.1")
    c.add_argument("--port", type=int, default=5000)

    args = p.parse_args(argv)
    conn = db.connect(args.db)
    db.init_db(conn)

    if args.cmd == "init":
        print(f"Veritabanı hazır: {args.db}")
    elif args.cmd == "topla":
        total = collector.collect(conn, load_sources(args.config), codes=args.kod)
        print(f"Toplam {total} teklif kaydedildi.")
    elif args.cmd == "ara":
        offers = db.search_offers(conn, args.kod)
        if not offers:
            print("Teklif bulunamadı.")
            return 1
        for i, o in enumerate(offers):
            mark = "EN UCUZ " if i == 0 and o["in_stock"] else ""
            stock = "" if o["in_stock"] else " (stok yok)"
            eq = " [muadil]" if o["is_equivalent"] else ""
            print(f"{mark:8}{format_price(o['price_kurus']):>14}  {o['seller']}  {o['display_code']}{eq}{stock}  {o['url']}")
    elif args.cmd == "uyumluluk":
        print(f"{collector.import_fitment(conn, args.csv)} uyumluluk satırı yüklendi.")
    elif args.cmd == "muadil":
        print(f"{collector.import_equivalents(conn, args.csv)} muadil eşleşmesi yüklendi.")
    elif args.cmd == "abonelik-ver":
        user = db.get_user_by_email(conn, args.email)
        if not user:
            print(f"Kullanıcı bulunamadı: {args.email}", file=sys.stderr)
            return 1
        end = subscription.extend(conn, user["id"], args.ay, args.ref)
        conn.commit()
        print(f"{args.email} aboneliği {end:%d.%m.%Y} tarihine kadar uzatıldı.")
    elif args.cmd == "demo":
        collector.collect(conn, load_sources(os.path.join(DEMO_DIR, "kaynaklar.json")))
        collector.import_fitment(conn, os.path.join(DEMO_DIR, "uyumluluk.csv"))
        collector.import_equivalents(conn, os.path.join(DEMO_DIR, "muadil.csv"))
        print("Demo verisi yüklendi. Deneyin: python -m parcabul ara DEMO-YF-100")
    elif args.cmd == "sunucu":
        from .web import create_app
        conn.close()
        create_app(args.db).run(host=args.host, port=args.port)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
