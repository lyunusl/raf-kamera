"""Fiyat etiketi okuma ve fiyat ayrıştırma.

`fiyat_ayristir` saf işlevdir (model gerektirmez). Türk market etiketlerindeki biçimler: "34,90", "34.90", "34 90"
(üst simge kuruş ayrı satır ya da boşlukla), "1.234,50", "34,-", "TL" önde/arkada ya da hiç yok. "₺" okuyucunun
karakter listesinde yoktur; yanlış okunursa (ör. "b", "t") rakamın yanındaki tek harf olarak atılır.

Okuma seyrek yapılır (etiketler seyrek değişir): koşu başında, gözün durumu değiştiğinde ve `etiket_araligi_sn`
aralıkla (bkz. raf.RafIzleyici). Bir etiket okuması ~100-300 ms sürer.
"""
from __future__ import annotations

import re
import time

import cv2
import numpy as np

from .raf_modeller import kirp

# ayrıştırma
_BIRIM = r"(?:K?GR?|KG|GRAM|M?L|LT|CL|ML|ADET|AD|PCS|CM|MM|M2|KM)\b"
_PARA = re.compile(r"(?<![A-ZÇĞİÖŞÜ])(?:Y?TL|TRY)(?![A-ZÇĞİÖŞÜ])|₺")
_SAYI_KURUS = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d{1,5})\s?([.,]|\s)\s?(\d{2})(?![\d])")
_BINLIK = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?![\d,]|\.\d)")
_SAYI_TIRE = re.compile(r"(?<![\d.,])(\d{1,5})\s?[.,]\s?-")
_SAYI_TEK = re.compile(r"(?<![\d.,])(\d{1,5})[.,](\d)(?![\d])")
_SAYI = re.compile(r"(?<![\d.,])(\d{1,5})(?![\d.,]?\d)")
_TARIH = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")

# karşılaştırma
FIYAT_TOLERANS = 0.01   # TL: okunan ile beklenen arasındaki bu kadar fark "aynı" sayılır
GUVEN_ESIK = 0.75       # okuyucunun ortalama güveni bunun altındaysa fiyat "farklı" diye raporlanmaz (okunamadı sayılır)


def _sadele(metin: str) -> str:
    m = metin.upper().replace("İ", "I")
    # rakamların arasındaki tipik karışıklıklar
    m = re.sub(r"(?<=\d)[OÖ](?=\d|\b)", "0", m)
    m = re.sub(r"(?<=\d)[IL|](?=[\d,.])", "1", m)
    m = re.sub(r"(?<=\d)[,.]\s+(?=\d{2}\b)", ",", m)
    return m


def _adaylar(satir: str, yukseklik: float) -> list[dict]:
    """Bir satırdaki fiyat adayları: {"fiyat", "puan", "bicim"}."""
    m = _sadele(satir)
    para = bool(_PARA.search(m))
    temiz = _PARA.sub(" ", m)
    temiz = _TARIH.sub(" ", temiz)
    out = []
    kullanildi = []

    def birim_var(son: int) -> bool:
        return re.match(r"\s*" + _BIRIM, temiz[son:]) is not None

    def yuzde_var(bas: int, son: int) -> bool:
        return "%" in temiz[max(0, bas - 1):bas] or temiz[son:son + 2].strip().startswith("%")

    for r in _SAYI_KURUS.finditer(temiz):
        if birim_var(r.end()) or yuzde_var(r.start(), r.end()):
            kullanildi.append((r.start(), r.end()))
            continue
        tam = int(r.group(1).replace(".", ""))
        ayrac = r.group(2)
        puan = 3.0 if ayrac in ",." else 2.2  # boşlukla ayrılmış kuruş (üst simge) biraz daha belirsiz
        out.append({"fiyat": round(tam + int(r.group(3)) / 100, 2), "puan": puan + para, "bicim": "kurus"})
        kullanildi.append((r.start(), r.end()))
    for r in _BINLIK.finditer(temiz):  # "1.299" / "19.990": binlik ayraçlı tam sayı (fiyatta üç ondalık hane olmaz)
        if any(a <= r.start() < b for a, b in kullanildi) or birim_var(r.end()):
            continue
        out.append({"fiyat": float(int(r.group(0).replace(".", ""))), "puan": 2.0 + para, "bicim": "binlik"})
        kullanildi.append((r.start(), r.end()))
    for r in _SAYI_TIRE.finditer(temiz):
        out.append({"fiyat": float(int(r.group(1))), "puan": 2.5 + para, "bicim": "tire"})
        kullanildi.append((r.start(), r.end()))
    for r in _SAYI_TEK.finditer(temiz):
        if any(a <= r.start() < b for a, b in kullanildi) or birim_var(r.end()) or yuzde_var(r.start(), r.end()):
            continue
        out.append({"fiyat": round(int(r.group(1)) + int(r.group(2)) / 10, 2), "puan": 1.2 + para, "bicim": "tek"})
        kullanildi.append((r.start(), r.end()))
    for r in _SAYI.finditer(temiz):
        if any(a <= r.start() < b for a, b in kullanildi) or birim_var(r.end()) or yuzde_var(r.start(), r.end()):
            continue
        n = int(r.group(1))
        if n == 0:
            continue
        out.append({"fiyat": float(n), "puan": (1.5 if para else 0.6), "bicim": "tam", "rakam": len(r.group(1))})
    for a in out:
        a["yukseklik"] = yukseklik
    return out


def _ust_simge(satirlar: list[dict]) -> list[dict]:
    """Büyük tam sayı + sağ üstünde küçük iki hane (üst simge kuruş) ayrı satır okunduysa birleştirir."""
    out = []
    for a in satirlar:
        ma = re.fullmatch(r"\s*(\d{1,5})\s*([.,]?)\s*", _PARA.sub(" ", _sadele(a["metin"])))
        if not ma or a.get("kutu") is None:
            continue
        ax1, ay1, ax2, ay2 = a["kutu"]
        ah = ay2 - ay1
        for b in satirlar:
            if b is a or b.get("kutu") is None:
                continue
            mb = re.fullmatch(r"\s*[.,]?\s*(\d{2})\s*(?:Y?TL|[A-Z₺])?\s*", _sadele(b["metin"]))
            if not mb:
                continue
            bx1, by1, bx2, by2 = b["kutu"]
            bh = by2 - by1
            fiyat = round(int(ma.group(1)) + int(mb.group(1)) / 100, 2)
            if bh < 0.85 * ah and -0.6 * ah < bx1 - ax2 < 0.8 * ah and by1 < ay1 + 0.6 * ah:
                out.append({"fiyat": fiyat, "puan": 3.2, "bicim": "ust_simge", "yukseklik": ah})
            elif ma.group(2) and -0.3 * ah < bx1 - ax2 < 0.8 * ah and min(ay2, by2) - max(ay1, by1) > 0.5 * min(ah, bh):
                # "5." ve "99" aynı hizada iki ayrı satır okunmuş (ayraçtan sonra kesilmiş)
                out.append({"fiyat": fiyat, "puan": 3.0, "bicim": "bolunmus", "yukseklik": max(ah, bh)})
    return out


def fiyat_ayristir(satirlar, beklenen: float | None = None) -> dict:
    """Okunan satırlardan fiyatı seçer.

    `satirlar`: metin listesi ya da {"metin", "kutu": [x1,y1,x2,y2] (isteğe bağlı), "guven"} sözlükleri.
    Dönüş: {"fiyat": float | None, "metin": "satırlar | ile", "adaylar": [..]}.
    Seçim: beklenen fiyata eşit aday varsa o (son iki hanesi kuruş sayılarak "1490" -> 14.90 dahil); yoksa en yüksek
    puanlı aday (kuruşlu biçim > tire > TL'li tam sayı > tek haneli kuruş > çıplak sayı), eşitlikte en büyük yazı.
    Çıplak sayı (TL'siz, ayraçsız) tek başına fiyat sayılmaz."""
    ss = [{"metin": s} if isinstance(s, str) else dict(s) for s in satirlar or []]
    yuks = [((s["kutu"][3] - s["kutu"][1]) if s.get("kutu") is not None else 1.0) for s in ss]
    enb = max(yuks) if yuks else 1.0
    adaylar = []
    for s, y in zip(ss, yuks):
        adaylar += _adaylar(s.get("metin") or "", y / max(enb, 1e-6))
    adaylar += [dict(a, yukseklik=a["yukseklik"] / max(enb, 1e-6)) for a in _ust_simge(ss)]
    metin = " | ".join(s.get("metin") or "" for s in ss if s.get("metin"))
    if beklenen is not None and beklenen > 0:
        for a in sorted(adaylar, key=lambda a: -a["puan"]):
            if abs(a["fiyat"] - beklenen) <= FIYAT_TOLERANS:
                return {"fiyat": round(beklenen, 2), "metin": metin, "adaylar": adaylar}
        for a in adaylar:
            # "1490" gibi ayraçsız okuma: son iki hane kuruş. "8.500": üst simge "50"nin yanına bir harf/rakam
            # karışmış (binlik sanılır); beklenen fiyatın tam 1000 katıysa kuruşlu okuma sayılır.
            if (a["bicim"] == "tam" and a.get("rakam", 0) >= 3 and abs(a["fiyat"] / 100 - beklenen) <= FIYAT_TOLERANS) \
                    or (a["bicim"] == "binlik" and abs(a["fiyat"] / 1000 - beklenen) <= FIYAT_TOLERANS):
                return {"fiyat": round(beklenen, 2), "metin": metin, "adaylar": adaylar}
    uygun = [a for a in adaylar if a["puan"] >= 1.2]
    if not uygun:
        return {"fiyat": None, "metin": metin, "adaylar": adaylar}
    en = max(uygun, key=lambda a: (a["puan"] + 1.5 * a["yukseklik"], a["yukseklik"]))
    return {"fiyat": en["fiyat"], "metin": metin, "adaylar": adaylar}


def karsilastir(fiyat: float | None, beklenen: float | None, guven: float = 1.0,
                tolerans: float = FIYAT_TOLERANS) -> str:
    """Kayıttaki `etiket` alanı (okunduysa): "uygun" | "farkli" | "okunamadi"."""
    if fiyat is None:
        return "okunamadi"
    if beklenen is None or beklenen <= 0:
        return "uygun"
    if abs(fiyat - beklenen) <= max(tolerans, FIYAT_TOLERANS):
        return "uygun"
    return "farkli" if guven >= GUVEN_ESIK else "okunamadi"


class EtiketOkuyucu:
    """Göz etiket kutusunu okur. `modeller`: raf_modeller.Modeller."""

    YOK_OLASILIK = 0.30  # metin olasılık haritasının en yüksek değeri bunun altındaysa "metin yok" -> etiket yok

    def __init__(self, modeller):
        self.m = modeller

    def oku(self, kare: np.ndarray, kutu, beklenen: float | None = None, tolerans: float = FIYAT_TOLERANS) -> dict:
        """`kutu`: 0-1 [x1,y1,x2,y2]. Dönüş: {"durum": "okundu" | "okunamadi" | "yok", "etiket": kayıttaki değer,
        "metin", "fiyat", "guven", "sure_ms"}."""
        bas = time.perf_counter()
        c = kirp(kare, kutu, pay=0.12)
        if c is None:
            return {"durum": "okunamadi", "etiket": "okunamadi", "metin": "", "fiyat": None, "guven": 0.0, "sure_ms": 0.0}
        sonuc = self.oku_kirpinti(c, beklenen, tolerans)
        sonuc["sure_ms"] = round((time.perf_counter() - bas) * 1000, 1)
        return sonuc

    def oku_kirpinti(self, c: np.ndarray, beklenen: float | None = None, tolerans: float = FIYAT_TOLERANS) -> dict:
        h, w = c.shape[:2]
        uzun = int(min(960, max(320, round(max(h, w) * 1.5 / 32) * 32)))
        kutular, enb = self.m.metin_bul(c, uzun=uzun)
        if not kutular:
            # metin bulucunun olasılık haritası hiçbir yerde YOK_OLASILIK'a ulaşmıyorsa kutuda yazı yok: etiket yok.
            # Bulanık/uzak etiket de bazen böyle görünebilir; raf.RafIzleyici bunu iki ardışık okumayla teyit eder.
            d = "yok" if enb < self.YOK_OLASILIK else "okunamadi"
            return {"durum": d, "etiket": d, "metin": "", "fiyat": None, "guven": 0.0}
        kirpintilar = [_dondur_kes(c, b) for b in kutular]
        okunan = self.m.metin_oku(kirpintilar)
        satirlar = []
        for b, (metin, g) in zip(kutular, okunan):
            if metin.strip() and g >= 0.4:
                satirlar.append({"metin": metin, "guven": g, "kutu": [float(b[:, 0].min()), float(b[:, 1].min()),
                                                                       float(b[:, 0].max()), float(b[:, 1].max())]})
        p = fiyat_ayristir(satirlar, beklenen)
        guven = float(np.mean([s["guven"] for s in satirlar])) if satirlar else 0.0
        if p["fiyat"] is None:
            return {"durum": "okunamadi", "etiket": "okunamadi", "metin": p["metin"], "fiyat": None, "guven": guven}
        return {"durum": "okundu", "etiket": karsilastir(p["fiyat"], beklenen, guven, tolerans),"metin": p["metin"],
                "fiyat": p["fiyat"], "guven": round(guven, 3)}


def _dondur_kes(im: np.ndarray, b: np.ndarray) -> np.ndarray:
    s = b.sum(1)
    d = np.diff(b, axis=1).ravel()
    tl, br, tr, bl = b[np.argmin(s)], b[np.argmax(s)], b[np.argmin(d)], b[np.argmax(d)]
    W = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    H = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    M = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
    c = cv2.warpPerspective(im, M, (max(W, 1), max(H, 1)), borderMode=cv2.BORDER_REPLICATE)
    if H > 1.5 * W:
        c = np.ascontiguousarray(np.rot90(c))
    return c
