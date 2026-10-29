"""Parça kodu ve fiyat metni normalizasyonu."""

import re

_TR_MAP = str.maketrans({
    "ı": "I", "İ": "I", "i": "I", "ş": "S", "Ş": "S", "ğ": "G", "Ğ": "G",
    "ü": "U", "Ü": "U", "ö": "O", "Ö": "O", "ç": "C", "Ç": "C",
})


def normalize_code(code):
    """Parça kodunu karşılaştırılabilir hale getirir.

    Satıcılar aynı kodu farklı yazar: "8200 768 913", "8200-768-913",
    "8200.768.913". Hepsi "8200768913" olur.
    """
    if code is None:
        return ""
    return re.sub(r"[^0-9A-Z]", "", str(code).translate(_TR_MAP).upper())


def parse_price(text):
    """Fiyat metnini kuruş cinsinden tam sayıya çevirir. Okunamazsa None.

    "1.234,56 TL" -> 123456, "₺899,90" -> 89990, "1234.5" -> 123450,
    "1,234.56" -> 123456, "2.500" -> 250000
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(round(float(text) * 100))
    s = re.sub(r"[^0-9.,]", "", str(text))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thousands = "." if dec == "," else ","
        s = s.replace(thousands, "").replace(dec, ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if len(tail) == 3 and s.count(",") >= 1 and head:
            s = s.replace(",", "")  # binlik ayırıcı: "2,500"
        else:
            s = head.replace(",", "") + "." + tail
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if len(tail) == 3 and head:
            s = s.replace(".", "")  # binlik ayırıcı: "2.500"
        else:
            s = head.replace(".", "") + "." + tail
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None


def format_price(kurus):
    """123456 -> "1.234,56 TL" """
    if kurus is None:
        return "-"
    lira, kr = divmod(int(kurus), 100)
    return f"{lira:,}".replace(",", ".") + f",{kr:02d} TL"
