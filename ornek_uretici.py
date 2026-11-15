"""Örnek veriler: küçük bir market için gerçekçi, kendi içinde tutarlı örnek veri üretir ve panelin GERÇEK yollarından
içeri alır ("Örnek verilerle dene").

  python ornek_uretici.py                # yükle (veri klasörü: RAF_KAMERA_VERI, yoksa ./veri)
  python ornek_uretici.py --kaldir       # yalnızca örnek verileri kaldır

Ne yapar:
  - 4 örnek kamera ayarı (iki raf kamerası, bir koridor, bir kasa + giriş) panelin ayar denetiminden geçerek yazılır;
    kodları "ornek-" önekiyle başlar (gerçek kameralar bu önekle kaydedilemez).
  - 31 ürün katalogdan (panelin ürün işlevleriyle) eklenir; her ürünün yer tutucu görseli bu betikte çizilir.
  - Son 14 günün çalışma saatleri dakika dakika canlandırılır: müşteri trafiği (saat ve gün deseniyle), durma, uzanma,
    alma, raftaki stok, personelin doldurma gecikmesi, yanlış yere konan ürün, fiyat etiketi sorunları, kasa kuyruğu,
    dökülme, tıkalı koridor, açık dolap kapağı. Bunlardan motorun yazacağı kuyruk kayıtları (olay, olcum, raf, etkilesim)
    sözleşmedeki biçimde <VERI>/kuyruk/ klasörüne yazılır ve panelin kuyruk alıcısıyla (kuyruk.al) içeri alınır.
  - Kameraların "son karesi" (yüzsüz, çizilmiş raf görüntüsü) ve olay kareleri çizilir.
Bütün satırlar `ornek = 1` ile işaretlenir; kaldırma yalnızca bu satırları, örnek kameraları ve örnek ürünleri siler.
İsimler uydurmadır: gerçek marka ya da kişi yoktur.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
import os
import random
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

import depo  # noqa: E402
import yollar  # noqa: E402

ON = depo.ORNEK_ON
KOSU = "ornek"
GUN = 14
ORNEK_TESIS = "Örnek Market"

# ad, kategori, fiyat (₺), renk (BGR), biçim, popülerlik (göreli alma sıklığı), kısa yazı
URUNLER = [
    ("Makarna 500 g", "Kuru gıda", 24.5, (40, 160, 230), "kutu", 1.3, "MAK"),
    ("Spagetti 500 g", "Kuru gıda", 26.0, (30, 120, 210), "kutu", 0.9, "SPG"),
    ("Pirinç 1 kg", "Kuru gıda", 79.9, (220, 220, 225), "paket", 1.0, "PRN"),
    ("Bulgur 1 kg", "Kuru gıda", 54.9, (90, 170, 210), "paket", 0.7, "BLG"),
    ("Kırmızı mercimek 1 kg", "Kuru gıda", 69.9, (60, 90, 200), "paket", 0.6, "MRC"),
    ("Nohut 1 kg", "Kuru gıda", 74.5, (120, 190, 220), "paket", 0.5, "NHT"),
    ("Un 2 kg", "Kuru gıda", 64.9, (235, 235, 240), "paket", 0.6, "UN"),
    ("Toz şeker 1 kg", "Kuru gıda", 44.9, (245, 245, 250), "paket", 1.1, "SKR"),
    ("Siyah çay 1 kg", "Kahvaltılık", 189.0, (40, 40, 160), "kutu", 0.8, "CAY"),
    ("Türk kahvesi 100 g", "Kahvaltılık", 59.9, (30, 60, 100), "kutu", 0.5, "KHV"),
    ("Ayçiçek yağı 1 L", "Yağ", 89.9, (60, 200, 240), "sise", 1.0, "AYC"),
    ("Zeytinyağı 1 L", "Yağ", 329.0, (40, 140, 90), "sise", 0.4, "ZYT"),
    ("Domates salçası 830 g", "Konserve", 64.5, (40, 40, 200), "kavanoz", 0.7, "SLC"),
    ("Biber salçası 650 g", "Konserve", 72.0, (30, 70, 180), "kavanoz", 0.4, "BBR"),
    ("Tuz 750 g", "Kuru gıda", 14.9, (200, 160, 90), "paket", 0.4, "TUZ"),
    ("Su 0,5 L", "İçecek", 7.5, (230, 200, 150), "sise", 2.0, "SU"),
    ("Su 1,5 L", "İçecek", 14.0, (220, 190, 140), "sise", 1.4, "SU"),
    ("Maden suyu 200 ml", "İçecek", 9.5, (120, 200, 120), "sise", 1.0, "MDN"),
    ("Kola 1 L", "İçecek", 42.0, (30, 30, 150), "sise", 1.2, "KOL"),
    ("Gazoz 1 L", "İçecek", 34.0, (90, 210, 210), "sise", 0.7, "GZZ"),
    ("Portakal suyu 1 L", "İçecek", 49.9, (40, 150, 245), "kutu", 0.7, "POR"),
    ("Şeftali suyu 1 L", "İçecek", 47.5, (90, 170, 245), "kutu", 0.5, "SFT"),
    ("Soğuk çay 330 ml", "İçecek", 27.5, (40, 120, 170), "kutu", 0.6, "SCY"),
    ("Limonata 1 L", "İçecek", 39.9, (80, 230, 240), "sise", 0.5, "LMN"),
    ("Süt 1 L", "Süt ürünü", 36.5, (245, 240, 230), "kutu", 1.6, "SUT"),
    ("Ayran 1 L", "Süt ürünü", 32.0, (240, 230, 220), "sise", 1.0, "AYR"),
    ("Yoğurt 1 kg", "Süt ürünü", 69.9, (250, 250, 250), "kavanoz", 0.9, "YGR"),
    ("Beyaz peynir 500 g", "Süt ürünü", 149.0, (230, 245, 245), "paket", 0.6, "PYN"),
    ("Kaşar 400 g", "Süt ürünü", 164.0, (80, 200, 240), "paket", 0.5, "KSR"),
    ("Tereyağı 250 g", "Süt ürünü", 119.0, (110, 220, 245), "paket", 0.4, "TRY"),
    ("Kefir 1 L", "Süt ürünü", 54.0, (200, 180, 240), "sise", 0.3, "KFR"),
]
# raflardaki dizilim (ürün sırası URUNLER içindeki indeks): satır satır, soldan sağa
RAF1 = [[0, 0, 1, 2, 3, 4], [5, 6, 7, 7, 14, 8], [9, 10, 10, 11, 12, 13]]          # kuru gıda: 3 × 6
RAF2 = [[15, 15, 17, 17, 22], [16, 16, 18, 18, 19], [20, 21, 23, 15, 16]]          # içecek: 3 × 5
DOLAP = [[24, 24, 25, 26], [27, 28, 29, 30]]                                       # süt dolabı: 2 × 4

KURALLAR = {  # sözleşmedeki özellik kodları (katalog boşsa da olay kendi adını taşır)
    "bos_raf": ("Boş raf", "raf", "yuksek", 4, True), "az_stok": ("Azalan stok", "raf", "orta", 3, True),
    "yanlis_urun": ("Yanlış ürün (planogram)", "raf", "orta", 3, True), "etiket_yok": ("Fiyat etiketi yok", "raf", "dusuk", 2, True),
    "fiyat_farkli": ("Fiyat farklı", "raf", "orta", 3, True), "kasa_kuyrugu": ("Kasa kuyruğu", "operasyon", "yuksek", 3, True),
    "toplu_alma": ("Toplu ürün alma", "operasyon", "dusuk", 2, False), "dolap_acik": ("Açık dolap kapağı", "operasyon", "yuksek", 3, True),
    "dokulme": ("Dökülme", "operasyon", "kritik", 5, True), "tikali_koridor": ("Tıkalı koridor", "operasyon", "yuksek", 3, True),
}
SAAT_DESENI = {8: .35, 9: .5, 10: .62, 11: .75, 12: 1.05, 13: 1.1, 14: .8, 15: .72, 16: .82, 17: 1.0, 18: 1.3, 19: 1.4, 20: 1.1, 21: .6}
GOREVLILER = ["Reyon görevlisi 1", "Reyon görevlisi 2", "Depo sorumlusu", "Kasa şefi"]


# ---------------------------------------------------------------- çizim

def _cv():
    import cv2
    import numpy as np

    return cv2, np


def urun_gorseli(i: int) -> bytes:
    """Ürünün yer tutucu görseli (JPEG): rengi ve biçimi ürüne göre çizilmiş bir ambalaj."""
    cv2, np = _cv()
    ad, _, _, renk, bicim, _, kisa = URUNLER[i]
    img = np.full((320, 240, 3), 246, np.uint8)
    koyu = tuple(int(c * 0.7) for c in renk)
    if bicim == "sise":
        cv2.rectangle(img, (95, 30), (145, 75), koyu, -1)
        cv2.rectangle(img, (70, 75), (170, 290), renk, -1, cv2.LINE_AA)
        cv2.rectangle(img, (70, 150), (170, 220), (255, 255, 255), -1)
    elif bicim == "kavanoz":
        cv2.rectangle(img, (55, 70), (185, 100), koyu, -1)
        cv2.rectangle(img, (50, 100), (190, 290), renk, -1)
        cv2.rectangle(img, (50, 160), (190, 230), (255, 255, 255), -1)
    elif bicim == "paket":
        pts = np.array([[50, 60], [190, 60], [200, 290], [40, 290]], np.int32)
        cv2.fillPoly(img, [pts], renk, cv2.LINE_AA)
        cv2.rectangle(img, (60, 150), (180, 220), (255, 255, 255), -1)
    else:
        cv2.rectangle(img, (45, 40), (195, 290), renk, -1)
        cv2.rectangle(img, (45, 40), (195, 90), koyu, -1)
        cv2.rectangle(img, (60, 150), (180, 220), (255, 255, 255), -1)
    (w, h), _ = cv2.getTextSize(kisa, cv2.FONT_HERSHEY_DUPLEX, 1.3, 2)
    cv2.putText(img, kisa, (120 - w // 2, 185 + h // 2), cv2.FONT_HERSHEY_DUPLEX, 1.3, (40, 40, 40), 2, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (239, 319), (220, 220, 220), 2)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


def raf_karesi(kamera: dict, durumlar: dict, vurgu: str | None = None, W: int = 1280, H: int = 720):
    """Raf kamerasının çizilmiş karesi: gözler doluluğa göre ürünle, boş gözler koyu arka panelle; kişi çizilmez."""
    cv2, np = _cv()
    img = np.zeros((H, W, 3), np.uint8)
    for y in range(H):  # duvar, hafif dikey geçiş
        img[y, :] = (62 + y * 30 // H, 66 + y * 30 // H, 70 + y * 28 // H)
    for b in kamera["bolgeler"]:
        if not b.get("gozler"):
            continue
        poly = np.array([[int(x * W), int(y * H)] for x, y in b["poly"]], np.int32)
        cv2.fillPoly(img, [poly], (52, 50, 48) if b["tur"] == "raf" else (70, 64, 52))
        if b["tur"] == "dolap":
            cv2.polylines(img, [poly], True, (200, 200, 205), 6)
        for g in b["gozler"]:
            x1, y1, x2, y2 = (int(g["kutu"][0] * W), int(g["kutu"][1] * H), int(g["kutu"][2] * W), int(g["kutu"][3] * H))
            cv2.rectangle(img, (x1 - 3, y2), (x2 + 3, y2 + 7), (150, 152, 158), -1)  # raf tahtası
            d = durumlar.get(g["kimlik"], {})
            urun = d.get("goster", g["_i"])
            oran = d.get("oran", 1.0)
            adet = g["adet"]
            gorunen = 0 if oran <= 0 else max(1, round(adet * min(1.0, oran / 0.6)))
            gen = (x2 - x1) / adet
            for k in range(gorunen):
                ax1, ax2 = int(x1 + k * gen + 2), int(x1 + (k + 1) * gen - 2)
                _, _, _, renk, bicim, _, kisa = URUNLER[urun]
                ust = y1 + (y2 - y1) * (0.18 if bicim == "sise" else 0.08)
                cv2.rectangle(img, (ax1, int(ust)), (ax2, y2 - 1), renk, -1)
                if bicim == "sise":
                    cx = (ax1 + ax2) // 2
                    cv2.rectangle(img, (cx - max(2, (ax2 - ax1) // 6), y1 + 2), (cx + max(2, (ax2 - ax1) // 6), int(ust)), renk, -1)
                cv2.rectangle(img, (ax1, int(ust + (y2 - ust) * 0.45)), (ax2, int(ust + (y2 - ust) * 0.7)), (245, 245, 245), -1)
            if g.get("etiket"):
                e = g["etiket"]
                ex1, ey1, ex2, ey2 = int(e[0] * W), int(e[1] * H), int(e[2] * W), int(e[3] * H)
                if d.get("etiket") != "yok":
                    cv2.rectangle(img, (ex1, ey1), (ex2, ey2), (250, 250, 250), -1)
                    fiyat = d.get("fiyat") or g.get("fiyat")
                    if fiyat:
                        cv2.putText(img, f"{fiyat:.2f}", (ex1 + 3, ey2 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (30, 30, 30), 1, cv2.LINE_AA)
            if vurgu == g["kimlik"]:
                cv2.rectangle(img, (x1 - 4, y1 - 4), (x2 + 4, y2 + 4), (60, 60, 230), 3)
    return img


def sahne_karesi(tur: str, W: int = 1280, H: int = 720):
    """Koridor ya da kasa kamerasının çizilmiş karesi (kişi çizilmez)."""
    cv2, np = _cv()
    img = np.zeros((H, W, 3), np.uint8)
    for y in range(H):
        t = y / H
        img[y, :] = (int(150 + 60 * t), int(155 + 60 * t), int(160 + 55 * t)) if y > H * 0.35 else (200, 205, 208)
    if tur == "koridor":
        cv2.fillPoly(img, [np.array([[0, 250], [470, 260], [470, 470], [0, 720]], np.int32)], (70, 90, 120))
        cv2.fillPoly(img, [np.array([[1280, 250], [810, 260], [810, 470], [1280, 720]], np.int32)], (80, 110, 90))
        for k in range(6):
            cv2.line(img, (0, 290 + k * 70), (470, 300 + k * 30), (200, 200, 200), 2)
            cv2.line(img, (1280, 290 + k * 70), (810, 300 + k * 30), (200, 200, 200), 2)
        cv2.rectangle(img, (560, 230), (720, 330), (90, 90, 95), -1)
    else:
        for x in (180, 640):
            cv2.fillPoly(img, [np.array([[x, 420], [x + 330, 420], [x + 360, 560], [x - 30, 560]], np.int32)], (90, 80, 70))
            cv2.rectangle(img, (x + 120, 360), (x + 210, 420), (40, 40, 45), -1)
        cv2.rectangle(img, (980, 140), (1220, 470), (120, 160, 170), -1)
        cv2.rectangle(img, (1000, 160), (1200, 470), (190, 220, 225), -1)
        cv2.line(img, (960, 640), (1260, 560), (60, 200, 255), 4)
    return img


def _jpg(img) -> bytes:
    cv2, _ = _cv()
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tobytes()


# ---------------------------------------------------------------- kamera ayarları

def _izgara_gozler(x1, y1, x2, y2, dizilim, urun_kimligi, fiyatlar, adet_fn):
    gozler = []
    satir_yuk = (y2 - y1) / len(dizilim)
    for r, satir in enumerate(dizilim):
        sutun_gen = (x2 - x1) / len(satir)
        for c, i in enumerate(satir):
            gx1, gx2 = x1 + c * sutun_gen + 0.004, x1 + (c + 1) * sutun_gen - 0.004
            gy1, gy2 = y1 + r * satir_yuk + 0.02, y1 + (r + 1) * satir_yuk - 0.035
            gozler.append({"kutu": [round(gx1, 4), round(gy1, 4), round(gx2, 4), round(gy2, 4)], "urun": urun_kimligi[i], "adet": adet_fn(i),
                           "etiket": [round(gx1 + 0.01, 4), round(gy2 + 0.008, 4), round(min(gx2, gx1 + 0.07), 4), round(gy2 + 0.03, 4)],
                           "fiyat": fiyatlar[i], "_i": i})
    return gozler


def kameralar(urun_kimligi: list[str]) -> list[dict]:
    fiyat = [u[2] for u in URUNLER]
    adet = lambda i: 3 if URUNLER[i][4] in ("kutu", "paket", "kavanoz") else 4  # noqa: E731
    import kurallar

    acik = {k: {"acik": True} for k in KURALLAR if not kurallar.KURALLAR or k in kurallar.KURAL}
    raf1 = {"kod": ON + "raf1", "ad": "Kuru gıda rafı", "kamera": {"tur": "rtsp", "adres": "rtsp://ornek-kamera.invalid/raf1"}, "ozellikler": acik,
            "raf_araligi_sn": 10, "kisi_fps": 3, "bolgeler": [
                {"ad": "Kuru gıda", "tur": "raf", "poly": [[0.05, 0.08], [0.95, 0.08], [0.95, 0.9], [0.05, 0.9]],
                 "gozler": _izgara_gozler(0.06, 0.09, 0.94, 0.89, RAF1, urun_kimligi, fiyat, adet)}]}
    raf2 = {"kod": ON + "raf2", "ad": "İçecek ve süt", "kamera": {"tur": "rtsp", "adres": "rtsp://ornek-kamera.invalid/raf2"}, "ozellikler": acik,
            "raf_araligi_sn": 10, "kisi_fps": 3, "bolgeler": [
                {"ad": "İçecek rafı", "tur": "raf", "poly": [[0.04, 0.08], [0.6, 0.08], [0.6, 0.9], [0.04, 0.9]],
                 "gozler": _izgara_gozler(0.05, 0.09, 0.59, 0.89, RAF2, urun_kimligi, fiyat, adet)},
                {"ad": "Süt dolabı", "tur": "dolap", "poly": [[0.63, 0.12], [0.97, 0.12], [0.97, 0.86], [0.63, 0.86]],
                 "gozler": _izgara_gozler(0.645, 0.14, 0.955, 0.84, DOLAP, urun_kimligi, fiyat, adet)}]}
    koridor = {"kod": ON + "koridor", "ad": "Ana koridor", "kamera": {"tur": "rtsp", "adres": "rtsp://ornek-kamera.invalid/koridor"}, "ozellikler": acik,
               "bolgeler": [
                   {"ad": "Ana koridor", "tur": "koridor", "poly": [[0.37, 0.38], [0.63, 0.38], [0.92, 0.99], [0.08, 0.99]]},
                   {"ad": "Atıştırmalık rafı", "tur": "raf", "poly": [[0.0, 0.35], [0.37, 0.36], [0.37, 0.65], [0.0, 0.99]]},
                   {"ad": "Temizlik rafı", "tur": "raf", "poly": [[0.63, 0.36], [1.0, 0.35], [1.0, 0.99], [0.63, 0.65]]}]}
    kasa = {"kod": ON + "kasa", "ad": "Kasa ve giriş", "kamera": {"tur": "rtsp", "adres": "rtsp://ornek-kamera.invalid/kasa"}, "ozellikler": acik,
            "bolgeler": [
                {"ad": "Kasa 1", "tur": "kasa", "poly": [[0.1, 0.55], [0.42, 0.55], [0.45, 0.99], [0.06, 0.99]], "esik": 4},
                {"ad": "Kasa 2", "tur": "kasa", "poly": [[0.46, 0.55], [0.78, 0.55], [0.8, 0.99], [0.44, 0.99]], "esik": 4},
                {"ad": "Giriş", "tur": "giris", "cizgi": [[0.75, 0.89], [0.98, 0.78]], "ic": [0.8, 0.7]}]}
    return [raf1, raf2, koridor, kasa]


# ---------------------------------------------------------------- canlandırma

class Kuyruk:
    """Kuyruk kayıtlarını motorun yazdığı biçimde (<zaman_ns>_<kod>_<sayaç>.json, önce .tmp) bırakır."""

    def __init__(self, klasor: Path):
        from concurrent.futures import ThreadPoolExecutor

        self.klasor = klasor
        klasor.mkdir(parents=True, exist_ok=True)
        self.sayac = 0
        self.n = 0
        self.havuz = ThreadPoolExecutor(max_workers=12)  # dosya yazımı paralel (sıra dosya adındadır)
        self.isler = []

    @staticmethod
    def _yaz(gecici: Path, hedef: Path, metin: str) -> None:
        gecici.write_text(metin, encoding="utf-8")
        os.replace(gecici, hedef)

    def birak(self, an: dt.datetime, kayit: dict) -> None:
        self.sayac += 1
        self.n += 1
        ns = int(an.timestamp() * 1e9)
        ad = f"{ns:020d}_{kayit['kamera']}_{self.sayac:07d}"
        self.isler.append(self.havuz.submit(self._yaz, self.klasor / (ad + ".tmp"), self.klasor / (ad + ".json"),
                                            json.dumps({**kayit, "kosu": KOSU}, ensure_ascii=False)))

    def bitir(self) -> None:
        for i in self.isler:
            i.result()
        self.isler.clear()
        self.havuz.shutdown()


def _iso(an: dt.datetime) -> str:
    return an.replace(microsecond=0).isoformat()


def _poisson(r: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(r.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= r.random()
        if p <= L:
            return k
        k += 1


def _binom(r: random.Random, n: int, p: float) -> int:
    return sum(1 for _ in range(n) if r.random() < p)


def _izgara(r: random.Random, merkezler: list[tuple[float, float, float, float]], toplam: float) -> list[list[float]]:
    gen, yuk = 32, 18
    hucre = [[0.0] * gen for _ in range(yuk)]
    for y in range(yuk):
        for x in range(gen):
            v = sum(a * math.exp(-(((x + .5) / gen - cx) ** 2 / (2 * s * s) + ((y + .5) / yuk - cy) ** 2 / (2 * s * s * 1.6))) for cx, cy, s, a in merkezler)
            hucre[y][x] = v
    t = sum(map(sum, hucre)) or 1
    return [[round(v * toplam / t * (0.85 + 0.3 * r.random()), 2) for v in s] for s in hucre]


IZGARA_MERKEZ = {
    "raf1": [(0.5, 0.92, 0.18, 1.0), (0.25, 0.85, 0.08, 0.5), (0.7, 0.88, 0.1, 0.6)],
    "raf2": [(0.3, 0.92, 0.12, 1.0), (0.8, 0.9, 0.08, 0.8), (0.55, 0.95, 0.15, 0.4)],
    "koridor": [(0.5, 0.75, 0.12, 1.0), (0.5, 0.5, 0.06, 0.6), (0.3, 0.8, 0.07, 0.5), (0.72, 0.8, 0.07, 0.4)],
}
DURMA_MERKEZ = {
    "raf1": [(0.3, 0.88, 0.07, 1.0), (0.72, 0.9, 0.06, 0.8)],
    "raf2": [(0.25, 0.9, 0.06, 0.8), (0.82, 0.88, 0.05, 1.0)],
    "koridor": [(0.28, 0.75, 0.05, 1.0), (0.74, 0.78, 0.05, 0.7)],
}


def canlandir(kams: list[dict], urun_kimligi: list[str], kuyruk: Kuyruk, simdi: dt.datetime, tohum: int = 7, yaz=print, gun_sayisi: int = GUN) -> dict:
    """Son GUN günün çalışma saatlerini dakika dakika canlandırır ve kuyruk kayıtlarını bırakır."""
    r = random.Random(tohum)
    g = depo.genel()
    acilis, kapanis = depo.calisma_araligi(g)
    if kapanis <= acilis:
        acilis, kapanis = 8 * 60, 22 * 60
    kamera = {k["kod"].replace(ON, ""): k for k in kams}
    # gözlerin stok durumu
    gozler = []
    for kisa in ("raf1", "raf2"):
        for b in kamera[kisa]["bolgeler"]:
            for gz in b.get("gozler") or []:
                kap = gz["adet"] * 2  # önde bir sıra, arkada bir sıra
                gozler.append({"kamera": kisa, "bolge": b["kimlik"], "bolge_ad": b["ad"], "g": gz, "i": urun_kimligi.index(gz["urun"]),
                               "kap": kap, "stok": kap, "durum": "dolu", "etiket": "uygun", "fiyat": gz["fiyat"], "yanlis": None, "yanlis_bit": None,
                               "dolum": None, "olay": None, "etiket_olay": None})
    goz_kimlik = {(x["kamera"], x["g"]["kimlik"]): x for x in gozler}
    # kalıcı etiket sorunları: iki gözde eski fiyat okunuyor, bir gözde etiket yok (son günlerde başlamış)
    eski_fiyat = {("raf1", kamera["raf1"]["bolgeler"][0]["gozler"][3]["kimlik"]): 74.9,   # (kamera, göz) → etiketteki eski fiyat
                  ("raf2", kamera["raf2"]["bolgeler"][0]["gozler"][8]["kimlik"]): 37.5}
    eski_fiyat_gun = {("raf1", kamera["raf1"]["bolgeler"][0]["gozler"][3]["kimlik"]): 9, ("raf2", kamera["raf2"]["bolgeler"][0]["gozler"][8]["kimlik"]): 4}
    etiketsiz = (kamera["raf2"]["bolgeler"][1]["gozler"][5]["kimlik"], "raf2", 2)
    duzelen = (kamera["raf1"]["bolgeler"][0]["gozler"][14]["kimlik"], "raf1", 11, 6)  # 11 gün önce başlayan, 6 gün önce düzelen fiyat farkı
    sayac = {"olay": 0}
    kare_yazildi: set[str] = set()

    def kare_yolu(kisa: str, goz: str | None, ek: str, ciz) -> str:
        ad = f"{ON}{kisa}/olay_{goz or 'genel'}_{ek}.jpg"
        if ad not in kare_yazildi:
            hedef = yollar.CIKTI / ad
            hedef.parent.mkdir(parents=True, exist_ok=True)
            hedef.write_bytes(_jpg(ciz()))
            kare_yazildi.add(ad)
        return ad

    def raf_durum_haritasi(kisa: str) -> dict:
        out = {}
        for x in gozler:
            if x["kamera"] == kisa:
                out[x["g"]["kimlik"]] = {"oran": x["stok"] / x["kap"], "goster": x["yanlis"] if x["yanlis"] is not None and x["stok"] > 0 else x["i"],
                                         "etiket": x["etiket"], "fiyat": x["fiyat"]}
        return out

    def olay_ac(an, kisa, kural, bolge=None, goz=None, x=None, aciklama="", deger=None, beklenen=None, kare=None, urun_i=None):
        sayac["olay"] += 1
        ad, kat, duzey, onem, gorev = KURALLAR[kural]
        k = kamera[kisa]
        olasilik = 3
        kayit = {"tur": "olay", "kimlik": f"{ON}{sayac['olay']:06d}", "zaman": _iso(an), "kamera": k["kod"], "kamera_ad": k["ad"], "kural": kural,
                 "kural_ad": ad, "kategori": kat, "duzey": duzey, "onem": onem, "olasilik": olasilik, "puan": onem * olasilik, "ciddi": duzey == "kritik",
                 "sure_sn": 0, "x": x[0] if x else 0.5, "y": x[1] if x else 0.6, "aciklama": aciklama, "bitti": False, "kare": kare, "klip": None,
                 "gorev": gorev}
        if bolge:
            kayit.update(bolge=bolge["kimlik"], bolge_ad=bolge["ad"])
        if goz:
            kayit["goz"] = goz
        if urun_i is not None:
            kayit.update(urun=urun_kimligi[urun_i], urun_ad=URUNLER[urun_i][0])
        if deger is not None:
            kayit["deger"] = deger
        if beklenen is not None:
            kayit["beklenen"] = beklenen
        kuyruk.birak(an, kayit)
        return {"kayit": kayit, "bas": an}

    def olay_kapat(o, an):
        sure = max(20.0, (an - o["bas"]).total_seconds())
        kuyruk.birak(an, {**o["kayit"], "sure_sn": round(sure), "bitti": True, "olasilik": 4 if sure > 900 else 3,
                          "puan": o["kayit"]["onem"] * (4 if sure > 900 else 3)})

    def raf_kaydi(an, kisa):
        liste = [x for x in gozler if x["kamera"] == kisa]
        kayit_gozler, doluluk, uyum_pay, uyum_payda = [], [], 0, 0
        for x in liste:
            oran = round(x["stok"] / x["kap"], 2)
            durum = x["durum"]
            gorulen = urun_kimligi[x["yanlis"]] if durum == "yanlis" else (urun_kimligi[x["i"]] if x["stok"] > 0 else None)
            kayit_gozler.append({"bolge": x["bolge"], "goz": x["g"]["kimlik"], "durum": durum, "doluluk": oran,
                                 "adet": min(x["g"]["adet"], math.ceil(x["g"]["adet"] * oran / 0.6)) if x["stok"] else 0,
                                 "urun": urun_kimligi[x["i"]], "gorulen": gorulen,
                                 "benzerlik": round(0.82 + 0.1 * r.random(), 2) if durum in ("dolu", "az") else (round(0.3 + 0.15 * r.random(), 2) if durum == "yanlis" else None),
                                 "etiket": x["etiket"], "fiyat": x["fiyat"] if x["etiket"] in ("uygun", "farkli") else None})
            doluluk.append(oran)
            uyum_payda += 1
            uyum_pay += durum in ("dolu", "az")
        kuyruk.birak(an, {"tur": "raf", "kamera": kamera[kisa]["kod"], "kamera_ad": kamera[kisa]["ad"], "zaman": _iso(an),
                          "doluluk": round(sum(doluluk) / len(doluluk), 3), "uyum": round(uyum_pay / uyum_payda, 3), "referans": "kayitli",
                          "gozler": kayit_gozler})

    def goz_durumu(x) -> str:
        if x["stok"] <= 0:
            return "bos"
        if x["yanlis"] is not None:
            return "yanlis"
        return "az" if x["stok"] / x["kap"] < 0.35 else "dolu"

    def merkez(x):
        k = x["g"]["kutu"]
        return ((k[0] + k[2]) / 2, (k[1] + k[3]) / 2)

    def guncelle(an, x) -> bool:
        """Gözün durumunu yeniden hesaplar; değiştiyse olayları açar / kapatır."""
        eski, yeni = x["durum"], goz_durumu(x)
        if eski == yeni:
            return False
        x["durum"] = yeni
        kisa = x["kamera"]
        bolge = next(b for b in kamera[kisa]["bolgeler"] if b["kimlik"] == x["bolge"])
        if x["olay"] and (yeni == "dolu" or x["olay"]["kayit"]["kural"] != {"bos": "bos_raf", "az": "az_stok", "yanlis": "yanlis_urun"}.get(yeni)):
            olay_kapat(x["olay"], an)
            x["olay"] = None
        if yeni in ("bos", "az", "yanlis") and x["olay"] is None:
            kural = {"bos": "bos_raf", "az": "az_stok", "yanlis": "yanlis_urun"}[yeni]
            ad = URUNLER[x["i"]][0]
            aciklama = {"bos": f"{ad} gözü boş.", "az": f"{ad} gözünde stok azaldı.",
                        "yanlis": f"{ad} gözünde başka ürün var ({URUNLER[x['yanlis']][0] if x['yanlis'] is not None else '?'})."}[yeni]
            durumlar = raf_durum_haritasi(kisa)
            kare = kare_yolu(kisa, x["g"]["kimlik"], yeni, lambda: raf_karesi(kamera[kisa], durumlar, x["g"]["kimlik"]))
            x["olay"] = olay_ac(an, kisa, kural, bolge, x["g"]["kimlik"], merkez(x), aciklama, kare=kare, urun_i=x["i"],
                                deger=round(x["stok"] / x["kap"], 2))
        if yeni in ("az", "bos") and x["dolum"] is None:
            # personelin tepki süresi: çoğu 10-40 dk, bazen saatler (yoğun saatte daha geç)
            gecikme = min(300.0, math.exp(r.gauss(math.log(24 if 9 <= an.hour < 17 else 38), 0.8)) * (3 if r.random() < 0.2 else 1))
            x["dolum"] = an + dt.timedelta(minutes=gecikme if yeni == "az" else gecikme * 0.8)
        return True

    def etiket_ayarla(an, x, etiket, fiyat):
        if x["etiket"] == etiket and x["fiyat"] == fiyat:
            return False
        x["etiket"], x["fiyat"] = etiket, fiyat
        kisa = x["kamera"]
        if x["etiket_olay"]:
            olay_kapat(x["etiket_olay"], an)
            x["etiket_olay"] = None
        if etiket in ("farkli", "yok"):
            bolge = next(b for b in kamera[kisa]["bolgeler"] if b["kimlik"] == x["bolge"])
            ad = URUNLER[x["i"]][0]
            durumlar = raf_durum_haritasi(kisa)
            kare = kare_yolu(kisa, x["g"]["kimlik"], "etiket", lambda: raf_karesi(kamera[kisa], durumlar, x["g"]["kimlik"]))
            if etiket == "farkli":
                x["etiket_olay"] = olay_ac(an, kisa, "fiyat_farkli", bolge, x["g"]["kimlik"], merkez(x),
                                           f"{ad}: etikette {fiyat:.2f}, olması gereken {x['g']['fiyat']:.2f}.", deger=fiyat, beklenen=x["g"]["fiyat"],
                                           kare=kare, urun_i=x["i"])
            else:
                x["etiket_olay"] = olay_ac(an, kisa, "etiket_yok", bolge, x["g"]["kimlik"], merkez(x), f"{ad} gözünün fiyat etiketi yok.", kare=kare, urun_i=x["i"])
        return True

    bas_gun = (simdi - dt.timedelta(days=gun_sayisi - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    kasa_q = {"b1": 0.0, "b2": 0.0}
    kasa_olay = {"b1": None, "b2": None}
    kasa_kim = {b["kimlik"]: b for b in kamera["kasa"]["bolgeler"]}
    kasa_b = [b["kimlik"] for b in kamera["kasa"]["bolgeler"] if b["tur"] == "kasa"]
    giris_gecmis: list[int] = []
    son_raf = {"raf1": None, "raf2": None}
    ozet = {"gun": 0, "ziyaretci": 0}
    toplu_gun = {r.randrange(gun_sayisi) for _ in range(5)}
    for gun_no in range(gun_sayisi):
        gun = bas_gun + dt.timedelta(days=gun_no)
        if gun > simdi:
            break
        hafta_sonu = gun.weekday() >= 5
        gun_kati = (1.3 if hafta_sonu else 1.0) * (0.85 + 0.3 * r.random())
        ozet["gun"] += 1
        # sabah: gece doldurulan gözler
        sabah = gun + dt.timedelta(minutes=acilis)
        if sabah + dt.timedelta(minutes=5) > simdi:
            break
        for x in gozler:
            if x["durum"] != "dolu" and r.random() < 0.8:
                x["stok"], x["dolum"] = x["kap"], None
            elif r.random() < 0.5:
                x["stok"] = max(x["stok"], int(x["kap"] * (0.6 + 0.4 * r.random())))
            x["yanlis"] = None
            guncelle(sabah, x)
        # etiketler (gün başında)
        for x in gozler:
            gk = x["g"]["kimlik"]
            gun_geri = gun_sayisi - 1 - gun_no
            if (x["kamera"], gk) in eski_fiyat and gun_geri <= eski_fiyat_gun[(x["kamera"], gk)]:
                etiket_ayarla(sabah + dt.timedelta(minutes=5), x, "farkli", eski_fiyat[(x["kamera"], gk)])
            elif gk == etiketsiz[0] and x["kamera"] == etiketsiz[1] and gun_geri <= etiketsiz[2]:
                etiket_ayarla(sabah + dt.timedelta(minutes=5), x, "yok", None)
            elif gk == duzelen[0] and x["kamera"] == duzelen[1] and duzelen[3] < gun_geri <= duzelen[2]:
                etiket_ayarla(sabah + dt.timedelta(minutes=5), x, "farkli", round(x["g"]["fiyat"] * 0.88, 2))
            else:
                etiket_ayarla(sabah + dt.timedelta(minutes=5), x, "uygun", x["g"]["fiyat"])
        # günün operasyon olayları
        plan = []
        if r.random() < 0.35:
            plan.append(("dokulme", "koridor", r.randint(acilis + 60, kapanis - 90), r.randint(8, 35)))
        if r.random() < 0.45:
            plan.append(("tikali_koridor", "koridor", r.randint(acilis + 30, kapanis - 120), r.randint(12, 55)))
        for _ in range(_poisson(r, 1.2)):
            plan.append(("dolap_acik", "raf2", r.randint(acilis + 10, kapanis - 30), r.randint(2, 7)))
        if gun_no in toplu_gun:
            plan.append(("toplu_alma", "raf2" if r.random() < .5 else "raf1", r.randint(acilis + 120, kapanis - 60), 1))
        for _ in range(_poisson(r, 1.6)):  # müşteri bir ürünü başka göze bırakır
            plan.append(("yanlis", r.choice(["raf1", "raf2"]), r.randint(acilis + 60, kapanis - 120), r.randint(25, 110)))
        acik_plan = []
        olcum = {}  # kamera → pencere toplamları
        for dk in range(acilis, kapanis):
            an = gun + dt.timedelta(minutes=dk)
            if an > simdi:
                break
            saat = an.hour
            lam = 0.78 * SAAT_DESENI.get(saat, 0.4) * gun_kati
            giren = _poisson(r, lam)
            giris_gecmis.append(giren)
            cikan = _poisson(r, sum(giris_gecmis[-25:-15]) / 10 if len(giris_gecmis) > 25 else lam * 0.8)
            ozet["ziyaretci"] += giren
            pencere = (dk - acilis) // 10
            for kisa in kamera:
                o = olcum.setdefault(kisa, {"bas": None, "veri": {}, "kuyruk": [], "pencere": -1, "kisi": 0.0})
                if o["pencere"] != pencere:
                    if o["bas"] is not None:
                        _olcum_birak(kuyruk, kamera[kisa], o, r)
                    o.update(bas=an, veri={}, kuyruk=[], pencere=pencere, kisi=0.0)
            # giriş ve kasa
            v = olcum["kasa"]["veri"]
            v["giren"] = v.get("giren", 0) + giren
            v["cikan"] = v.get("cikan", 0) + cikan
            v["gecen"] = v.get("gecen", 0) + giren + cikan
            for bk in kasa_b:
                hedef = lam * (1.7 if bk == "b1" else 1.0) * (2.4 if 17 <= saat < 21 or 12 <= saat < 14 else 1.2)
                kasa_q[bk] = max(0.0, 0.75 * kasa_q[bk] + 0.25 * _poisson(r, hedef))
                q = round(kasa_q[bk])
                olcum["kasa"]["kuyruk"].append(q)
                v[f"b:{bk}:gecen"] = v.get(f"b:{bk}:gecen", 0) + _poisson(r, lam * 0.45)
                v[f"b:{bk}:bekleme_sn"] = v.get(f"b:{bk}:bekleme_sn", 0) + q * 60
                v[f"b:{bk}:bekleme_sayi"] = v.get(f"b:{bk}:bekleme_sayi", 0) + (1 if q else 0)
                esik = kasa_kim[bk].get("esik", 4)
                if q >= esik and kasa_olay[bk] is None:
                    kasa_olay[bk] = olay_ac(an, "kasa", "kasa_kuyrugu", kasa_kim[bk], None, (0.25 if bk == "b1" else 0.62, 0.78),
                                            f"{kasa_kim[bk]['ad']}: kuyrukta {q} kişi.", deger=q,
                                            kare=kare_yolu("kasa", None, f"kuyruk_{bk}", lambda: sahne_karesi("kasa")))
                elif kasa_olay[bk] is not None and q < esik - 1:
                    olay_kapat(kasa_olay[bk], an)
                    kasa_olay[bk] = None
            olcum["kasa"]["kisi"] += sum(kasa_q.values()) + giren * 0.5
            # koridor
            v = olcum["koridor"]["veri"]
            gecen = _binom(r, giren * 2, 0.42)
            duran = _binom(r, gecen, 0.18)
            v["gecen"] = v.get("gecen", 0) + gecen
            v["duran"] = v.get("duran", 0) + duran
            v["bekleme_sn"] = v.get("bekleme_sn", 0) + sum(min(240, math.exp(r.gauss(2.6, 0.7))) for _ in range(duran))
            v["bekleme_sayi"] = v.get("bekleme_sayi", 0) + duran
            _demografi(r, v, "", gecen)
            for bk, oran in (("b1", 1.0), ("b2", 0.45), ("b3", 0.3)):
                bg = _binom(r, gecen, oran)
                bd = _binom(r, bg, 0.3 if bk != "b1" else 0.12)
                bu = _binom(r, bd, 0.55) if bk != "b1" else 0
                ba = _binom(r, bu, 0.8)
                for ad_, n in (("gecen", bg), ("duran", bd), ("uzanan", bu), ("alan", ba), ("birakan", _binom(r, bu - ba, 0.4)),
                               ("bekleme_sayi", bd), ("bekleme_sn", bd * math.exp(r.gauss(2.8, 0.4))), ("ilgi_sn", bd * 14 * r.random())):
                    v[f"b:{bk}:{ad_}"] = v.get(f"b:{bk}:{ad_}", 0) + n
                _demografi(r, v, f"b:{bk}:", bg)
            olcum["koridor"]["kisi"] += gecen * 0.25
            # raf kameraları: gözlerin önünde durma, uzanma, alma
            for kisa, zon in (("raf1", [("b1", 0.48)]), ("raf2", [("b1", 0.58), ("b2", 0.5)])):
                v = olcum[kisa]["veri"]
                kgecen = 0
                for bk, oran in zon:
                    bg = _binom(r, giren * 2, oran * 0.5)
                    kgecen += bg
                    bd = _binom(r, bg, 0.42)
                    bu = _binom(r, bd, 0.62)
                    ba = 0
                    durmalar = [min(300, math.exp(r.gauss(2.9, 0.75))) for _ in range(bd)]
                    adaylar = [x for x in gozler if x["kamera"] == kisa and x["bolge"] == bk]
                    for sure in durmalar:
                        x = r.choices(adaylar, weights=[URUNLER[z["i"]][5] for z in adaylar])[0]
                        kuyruk.birak(an + dt.timedelta(seconds=r.randint(0, 59)), {"tur": "etkilesim", "kamera": kamera[kisa]["kod"],
                                                                                  "zaman": _iso(an + dt.timedelta(seconds=r.randint(0, 59))), "bolge": bk,
                                                                                  "goz": x["g"]["kimlik"] if r.random() < 0.7 else None, "eylem": "durdu",
                                                                                  "sure_sn": round(sure, 1)})
                    for _ in range(bu):
                        x = r.choices(adaylar, weights=[URUNLER[z["i"]][5] for z in adaylar])[0]
                        t_ = an + dt.timedelta(seconds=r.randint(0, 59))
                        kuyruk.birak(t_, {"tur": "etkilesim", "kamera": kamera[kisa]["kod"], "zaman": _iso(t_), "bolge": bk, "goz": x["g"]["kimlik"],
                                          "eylem": "uzandi", "sure_sn": round(1 + 3 * r.random(), 1)})
                        if r.random() < 0.82 and x["stok"] > 0 and x["durum"] != "yanlis":
                            adet = 1 if r.random() < 0.85 else r.randint(2, 3)
                            x["stok"] = max(0, x["stok"] - adet)
                            ba += 1
                            kuyruk.birak(t_ + dt.timedelta(seconds=2), {"tur": "etkilesim", "kamera": kamera[kisa]["kod"], "zaman": _iso(t_ + dt.timedelta(seconds=2)),
                                                                       "bolge": bk, "goz": x["g"]["kimlik"], "eylem": "aldi", "sure_sn": None})
                            if guncelle(an, x):
                                pass
                        elif r.random() < 0.35:
                            kuyruk.birak(t_ + dt.timedelta(seconds=3), {"tur": "etkilesim", "kamera": kamera[kisa]["kod"], "zaman": _iso(t_ + dt.timedelta(seconds=3)),
                                                                       "bolge": bk, "goz": x["g"]["kimlik"], "eylem": "birakti", "sure_sn": None})
                            v[f"b:{bk}:birakan"] = v.get(f"b:{bk}:birakan", 0) + 1
                            v["birakan"] = v.get("birakan", 0) + 1
                    for ad_, n in (("gecen", bg), ("duran", bd), ("uzanan", bu), ("alan", ba), ("bekleme_sn", sum(durmalar)), ("bekleme_sayi", bd),
                                   ("ilgi_sn", sum(durmalar) * 0.8 + bg * 2)):
                        v[f"b:{bk}:{ad_}"] = v.get(f"b:{bk}:{ad_}", 0) + n
                        if ad_ not in ("gecen", "ilgi_sn"):
                            v[ad_] = v.get(ad_, 0) + n
                    _demografi(r, v, f"b:{bk}:", bg)
                v["gecen"] = v.get("gecen", 0) + round(kgecen * 0.85)
                _demografi(r, v, "", round(kgecen * 0.85))
                olcum[kisa]["kisi"] += kgecen * 0.3
            # personel doldurması
            degisen = set()
            for x in gozler:
                if x["dolum"] is not None and an >= x["dolum"]:
                    x["stok"], x["dolum"] = x["kap"], None
                    if guncelle(an, x):
                        degisen.add(x["kamera"])
                if x["yanlis_bit"] is not None and an >= x["yanlis_bit"]:
                    x["yanlis"], x["yanlis_bit"] = None, None
                    if guncelle(an, x):
                        degisen.add(x["kamera"])
            # planlanan olaylar
            for p in plan:
                if p[2] == dk:
                    tur, kisa, _, sure = p
                    if tur == "yanlis":
                        adaylar_ = [z for z in gozler if z["kamera"] == kisa and z["stok"] > 0 and z["yanlis"] is None]
                        if not adaylar_:
                            continue
                        x = r.choice(adaylar_)
                        x["yanlis"] = r.choice([z["i"] for z in gozler if z["kamera"] == kisa and z["i"] != x["i"]])
                        x["yanlis_bit"] = an + dt.timedelta(minutes=sure)
                        if guncelle(an, x):
                            degisen.add(kisa)
                        continue
                    bolge = kamera[kisa]["bolgeler"][1 if tur == "dolap_acik" else 0]
                    aciklama = {"dokulme": "Koridorda yere dökülmüş sıvı.", "tikali_koridor": "Koridor koli ve palet ile kapalı.",
                                "dolap_acik": "Süt dolabının kapağı açık kaldı.", "toplu_alma": "Bir müşteri aynı üründen çok sayıda aldı."}[tur]
                    kare = kare_yolu(kisa, None, tur, (lambda k=kisa: sahne_karesi("koridor") if k == "koridor" else raf_karesi(kamera[k], raf_durum_haritasi(k))))
                    o = olay_ac(an, kisa, tur, bolge, None, (0.5 + 0.2 * r.random(), 0.7), aciklama, kare=kare,
                                deger=r.randint(6, 12) if tur == "toplu_alma" else None)
                    acik_plan.append((an + dt.timedelta(minutes=sure), o))
            for bitis, o in list(acik_plan):
                if an >= bitis:
                    olay_kapat(o, an)
                    acik_plan.remove((bitis, o))
            # raf kayıtları: durum değişince ve 10 dakikada bir
            for kisa in ("raf1", "raf2"):
                if any(x["kamera"] == kisa and x["durum"] != x.get("_bildirilen") for x in gozler) or kisa in degisen \
                        or son_raf[kisa] is None or (an - son_raf[kisa]).total_seconds() >= 600:
                    raf_kaydi(an + dt.timedelta(seconds=30), kisa)
                    son_raf[kisa] = an
                    for x in gozler:
                        if x["kamera"] == kisa:
                            x["_bildirilen"] = x["durum"]
        # gün sonu: açık ölçüm pencereleri bırakılır; planlı olaylar kapanış saatinde biter
        son_an = min(simdi, gun + dt.timedelta(minutes=kapanis))
        for kisa, o in olcum.items():
            if o["bas"] is not None:
                _olcum_birak(kuyruk, kamera[kisa], o, r, son_an)
        for bitis, o in acik_plan:
            olay_kapat(o, min(bitis, son_an))
        for bk in kasa_b:
            if kasa_olay[bk] is not None and son_an < simdi:
                olay_kapat(kasa_olay[bk], son_an)
                kasa_olay[bk] = None
        yaz(f"  {gun.date().isoformat()} canlandırıldı")
    # son kareler: temiz_kare (çizimsiz) ve son_kare (motorun çizimleriyle: burada alt bilgi şeridi)
    cv2, _np = _cv()
    for kisa, k in kamera.items():
        hedef = yollar.CIKTI / k["kod"] / "son_kare.jpg"
        hedef.parent.mkdir(parents=True, exist_ok=True)
        img = raf_karesi(k, raf_durum_haritasi(kisa)) if kisa in ("raf1", "raf2") else sahne_karesi("koridor" if kisa == "koridor" else "kasa")
        (yollar.CIKTI / k["kod"] / "temiz_kare.jpg").write_bytes(_jpg(img))
        cizimli = img.copy()
        cv2.rectangle(cizimli, (0, cizimli.shape[0] - 34), (cizimli.shape[1], cizimli.shape[0]), (20, 20, 20), -1)
        cv2.putText(cizimli, f"{k['kod']}  ornek", (12, cizimli.shape[0] - 11), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1, cv2.LINE_AA)
        hedef.write_bytes(_jpg(cizimli))
        if kisa in ("raf1", "raf2"):  # referans kare: rafın dolu hâli
            dolu = {x["g"]["kimlik"]: {"oran": 1.0, "goster": x["i"], "etiket": "uygun", "fiyat": x["g"]["fiyat"]} for x in gozler if x["kamera"] == kisa}
            (yollar.AYAR / f"_referans_{k['kod']}.jpg").write_bytes(_jpg(raf_karesi(k, dolu)))
    return ozet


def _demografi(r: random.Random, v: dict, on: str, n: int) -> None:
    """Toplu yaş grubu ve cinsiyet sayıları (kişi bazında hiçbir şey yazılmaz)."""
    if n <= 0:
        return
    kadin = _binom(r, n, 0.56)
    v[on + "kadin"] = v.get(on + "kadin", 0) + kadin
    v[on + "erkek"] = v.get(on + "erkek", 0) + n - kadin
    genc = _binom(r, n, 0.27)
    yasli = _binom(r, n - genc, 0.26)
    v[on + "yas_genc"] = v.get(on + "yas_genc", 0) + genc
    v[on + "yas_yasli"] = v.get(on + "yas_yasli", 0) + yasli
    v[on + "yas_yetiskin"] = v.get(on + "yas_yetiskin", 0) + n - genc - yasli


def _olcum_birak(kuyruk: Kuyruk, kamera: dict, o: dict, r: random.Random, bitis: dt.datetime | None = None) -> None:
    bas = o["bas"]
    sure = ((bitis or bas + dt.timedelta(minutes=10)) - bas).total_seconds()
    sure = max(60.0, min(600.0, sure))
    veri = {a: round(v, 1) if isinstance(v, float) else v for a, v in o["veri"].items()}
    if o["kuyruk"]:
        veri["kuyruk_ort"] = round(sum(o["kuyruk"]) / len(o["kuyruk"]) * 2 / 2, 2)
        veri["kuyruk_en_cok"] = max(o["kuyruk"])
    veri["kisi_ort"] = round(o["kisi"] / max(1, sure / 60), 2)
    kisa = kamera["kod"].replace(ON, "")
    izgara = None
    if kisa in IZGARA_MERKEZ and bas.minute < 10:  # saatte bir ısı haritası parçası
        gecen = sum(v for a, v in veri.items() if a.endswith("gecen")) or 1
        durma = sum(v for a, v in veri.items() if a.endswith("bekleme_sn"))
        izgara = {"gen": 32, "yuk": 18, "katmanlar": {"yogunluk": _izgara(r, IZGARA_MERKEZ[kisa], gecen * 6 * 6),
                                                      "durma": _izgara(r, DURMA_MERKEZ[kisa], durma * 6)}}
    kuyruk.birak(bas + dt.timedelta(seconds=sure), {"tur": "olcum", "kamera": kamera["kod"], "kamera_ad": kamera["ad"], "bas": _iso(bas), "sure_sn": sure,
                                                    "analiz": int(sure * 3), "veri": veri, "izgara": izgara, "son_kare": None})


# ---------------------------------------------------------------- yükle / kaldır

def yukle(ayar_kaydet=None, urun_kaydet=None, gorsel_ekle=None, yaz=print, simdi: dt.datetime | None = None, tohum: int = 7, gun: int = GUN) -> dict:
    """Örnek verileri yükler. İşlevler verilmezse panelin (uygulama.py) kendi işlevleri kullanılır."""
    import kuyruk

    if ayar_kaydet is None or urun_kaydet is None or gorsel_ekle is None:
        import uygulama

        ayar_kaydet = ayar_kaydet or uygulama.ayar_kaydet
        urun_kaydet = urun_kaydet or uygulama.urun_kaydet
        gorsel_ekle = gorsel_ekle or uygulama.urun_gorseli_ekle
    simdi = (simdi or dt.datetime.now()).replace(microsecond=0)
    depo.vt()
    yaz("Ürünler ekleniyor…")
    kimlikler = []
    for i, (ad, kategori, fiyat, *_rest) in enumerate(URUNLER):
        u = urun_kaydet({"ad": ad, "kategori": kategori, "fiyat": fiyat, "barkod": f"2000{i + 1:05d}"}, ornek=True)
        gorsel_ekle({"kimlik": u["kimlik"], "kaynak": "dosya", "veri": "data:image/jpeg;base64," + base64.b64encode(urun_gorseli(i)).decode()})
        kimlikler.append(u["kimlik"])
    yaz("Kameralar ve planogram yazılıyor…")
    kams = kameralar(kimlikler)
    yazilan = []
    for k in kams:
        temiz = json.loads(json.dumps(k))
        for b in temiz["bolgeler"]:
            for gz in b.get("gozler") or []:
                gz.pop("_i", None)
        ayar_kaydet(temiz, ornek=True)
        yazilan.append(json.loads((yollar.AYAR / f"{k['kod']}.json").read_text(encoding="utf-8")))
    for k, y in zip(kams, yazilan):  # kimlikler panelden gelir; çizim için ürün sırası eklenir
        for b, yb in zip(k["bolgeler"], y["bolgeler"]):
            b["kimlik"] = yb["kimlik"]
            for gz, ygz in zip(b.get("gozler") or [], yb.get("gozler") or []):
                gz["kimlik"] = ygz["kimlik"]
    for k in kams:  # referans kare kaydedilmiş sayılır (örnekte yüzsüz çizim)
        a = json.loads((yollar.AYAR / f"{k['kod']}.json").read_text(encoding="utf-8"))
        if any(b.get("gozler") for b in a["bolgeler"]):
            a["referans"] = {"zaman": _iso(simdi - dt.timedelta(days=GUN))}
            a.pop("gozler_degisim", None)
            (yollar.AYAR / f"{k['kod']}.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    yaz(f"Son {gun} gün canlandırılıyor…")
    kq = Kuyruk(yollar.VERI / "kuyruk")
    # Yazım bitene kadar panelin kuyruk alıcısı bekler: dosyalar paralel yazılır, sırayla (ad sırasıyla) işlenmeleri gerekir.
    with kuyruk._KILIT:
        try:
            ozet = canlandir(kams, kimlikler, kq, simdi, tohum=tohum, yaz=yaz, gun_sayisi=gun)
        finally:
            kq.bitir()
    yaz(f"{kq.n} kuyruk kaydı içeri alınıyor…")
    while any((yollar.VERI / "kuyruk").glob(f"*_{ON}*.json")):
        kuyruk.al()
    # personel: açık görevlerin bir kısmı üstlenilmiş
    r = random.Random(tohum + 1)
    for g in depo.sor("SELECT id FROM gorev WHERE ornek = 1 AND durum = 'acik' ORDER BY id"):
        if r.random() < 0.45:
            depo.yaz("UPDATE gorev SET durum = 'suruyor', sorumlu = ?, baslama = ? WHERE id = ?", r.choice(GOREVLILER), depo.simdi(), g["id"])
    for g in depo.sor("SELECT id FROM gorev WHERE ornek = 1 AND durum = 'kapandi' ORDER BY id"):
        if r.random() < 0.6:
            depo.yaz("UPDATE gorev SET sorumlu = ? WHERE id = ?", r.choice(GOREVLILER), g["id"])
    gn = depo.genel()
    ek = {"ornek_veri": {"zaman": depo.simdi(), "onceki_tesis": gn["tesis"]}}
    if gn["tesis"] in ("Mağaza", "Tesis"):
        ek["tesis"] = ORNEK_TESIS
    depo.genel_yaz(ek)
    sayilar = depo.ornek_sayilari()
    yaz(f"Hazır: {ozet['gun']} gün, yaklaşık {ozet['ziyaretci']} ziyaretçi, {sayilar['olay']} uyarı, {sayilar['gorev']} görev.")
    return {**ozet, **sayilar, "urun": len(kimlikler), "kamera": len(kams)}


def kaldir() -> dict:
    import uygulama

    g = depo.genel()
    once = (g.get("ornek_veri") or {}).get("onceki_tesis")
    sonuc = uygulama.ornek_veri_kaldir()
    if g.get("tesis") == ORNEK_TESIS and once:
        depo.genel_yaz({"tesis": once})
    return sonuc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--kaldir" in sys.argv:
        print(kaldir())
    else:
        print(yukle())
