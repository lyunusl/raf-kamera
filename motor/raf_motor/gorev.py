"""Tek seferlik motor işleri (sözleşme bölüm 5): `gozler`, `etiketler`, `urun_tani`.

Panel sahneyi kamera kodu `_gorev` ve `--step` ile çalıştırır; ortam değişkenleri:
  RAF_GOREV        iş adı
  RAF_GOREV_GIRDI  girdi JSON yolu
  RAF_GOREV_CIKTI  çıktı JSON yolu (motor `.tmp` yazıp os.replace ile bırakır; hata olursa {"hata": "..."})

Her iş saf bir işlevdir: `is_gozler(girdi, modeller, ...) -> dict` vb. `ortamdan()` ortamı okuyup işi bir kez koşar.
Koordinatlar her yerde 0-1.
"""
from __future__ import annotations

import json
import os
import time

import cv2
import numpy as np

from .etiket import EtiketOkuyucu, fiyat_ayristir, _dondur_kes
from .urun import renk_ozeti

ORTAM_GOREV = "RAF_GOREV"
ORTAM_GIRDI = "RAF_GOREV_GIRDI"
ORTAM_CIKTI = "RAF_GOREV_CIKTI"
GOREV_KOD = "_gorev"

# Komşu iki yüz aynı göze girer: (gömme >= 0.60 ve renk >= 0.85) ya da (gömme >= 0.80 ve renk >= 0.60).
# renk = HSV (ton x doygunluk) histogramlarının kosinüsü. Ölçüm: raf_41/13/02/43 komşu çiftleri (teslim notu).
BIRLESME_KURAL = ((0.60, 0.85), (0.80, 0.60))
BIRLESME_BOSLUK = 0.6    # komşu yüzler arasındaki boşluk ortalama genişliğin en çok bu katı
BIRLESME_BOY = 0.7       # komşu yüzlerin yükseklik oranı en az bu
SATIR_ORTUSME = 0.45     # bir kutu, satır bandıyla küçük yüksekliğin bu oranı kadar dikey örtüşürse o satırdadır


# --- saf yardımcılar ----------------------------------------------------------------------------------------------------
def satirlara_ayir(kutular: np.ndarray) -> list[list[int]]:
    """Ürün kutularını raf satırlarına ayırır. Dönüş: satırlar yukarıdan aşağı, her satırdaki kutu indeksleri soldan sağa.
    Kural: kutu, mevcut bir satırın bandıyla (üyelerin medyan üst/alt kenarı) küçük yüksekliğin SATIR_ORTUSME oranı
    kadar örtüşürse o satıra girer (en çok örtüşene); yoksa yeni satır açar. Kutular yukarıdan aşağı sırayla işlenir."""
    if not len(kutular):
        return []
    sira = np.argsort((kutular[:, 1] + kutular[:, 3]) / 2)
    satirlar: list[list[int]] = []
    bantlar: list[tuple[float, float]] = []
    for i in sira:
        y1, y2 = float(kutular[i, 1]), float(kutular[i, 3])
        h = max(1e-6, y2 - y1)
        en, en_j = 0.0, -1
        for j, (b1, b2) in enumerate(bantlar):
            ort = max(0.0, min(y2, b2) - max(y1, b1)) / max(1e-6, min(h, b2 - b1))
            if ort > en:
                en, en_j = ort, j
        if en >= SATIR_ORTUSME:
            satirlar[en_j].append(int(i))
            uy = kutular[satirlar[en_j]]
            bantlar[en_j] = (float(np.median(uy[:, 1])), float(np.median(uy[:, 3])))
        else:
            satirlar.append([int(i)])
            bantlar.append((y1, y2))
    sira_s = sorted(range(len(satirlar)), key=lambda j: sum(bantlar[j]) / 2)
    return [sorted(satirlar[j], key=lambda i: float(kutular[i, 0] + kutular[i, 2])) for j in sira_s]


def ayni_urun(gomme: float, renk: float) -> bool:
    return any(gomme >= g and renk >= r for g, r in BIRLESME_KURAL)


def komsulari_birlestir(kutular: np.ndarray, satir: list[int], ayni) -> list[list[int]]:
    """Bir satırdaki soldan sağa kutuları, komşu ve aynı ürün olanları birleştirerek gruplar.
    `ayni(i, j)`: iki kutu aynı ürün mü (bool). Dönüş: gruplar (kutu indeksleri)."""
    gruplar: list[list[int]] = []
    for i in satir:
        if gruplar:
            j = gruplar[-1][-1]
            a, b = kutular[j], kutular[i]
            wa, wb = a[2] - a[0], b[2] - b[0]
            ha, hb = a[3] - a[1], b[3] - b[1]
            bosluk = b[0] - a[2]
            if bosluk <= BIRLESME_BOSLUK * (wa + wb) / 2 and min(ha, hb) / max(ha, hb, 1e-6) >= BIRLESME_BOY \
                    and ayni(j, i):
                gruplar[-1].append(i)
                continue
        gruplar.append([i])
    return gruplar


def _poly_ici(poly_px: np.ndarray, x: float, y: float) -> bool:
    return cv2.pointPolygonTest(poly_px.astype(np.float32), (float(x), float(y)), False) >= 0


def _oku_kare(yol: str) -> np.ndarray:
    try:
        v = np.fromfile(yol, np.uint8)
    except OSError:
        raise ValueError("kare okunamadı (dosya yok)") from None  # yol hata metnine girmesin
    im = cv2.imdecode(v, cv2.IMREAD_COLOR) if v.size else None
    if im is None:
        raise ValueError("kare okunamadı")
    return im


def _yuvarla(k) -> list[float]:
    return [round(float(v), 4) for v in k]


# --- işler -------------------------------------------------------------------------------------------------------------
def is_gozler(girdi: dict, modeller, etiket_ara: bool = True, kare: np.ndarray | None = None) -> dict:
    """Raf bölgelerinde ürün yüzlerinden göz önerir. Girdi {"kare": yol, "bolgeler": [{"kimlik", "poly"}]}.
    Çıktı {"gozler": [{"bolge", "kutu", "skor", "etiket", "adet"}]} (bölge bölge, satır satır, soldan sağa)."""
    im = kare if kare is not None else _oku_kare(girdi["kare"])
    H, W = im.shape[:2]
    out = []
    for b in girdi.get("bolgeler") or []:
        poly = np.asarray(b.get("poly") or [], np.float32)
        if poly.ndim != 2 or len(poly) < 3:
            continue
        pp = poly * np.array([W, H], np.float32)
        X1, Y1 = int(max(0, pp[:, 0].min())), int(max(0, pp[:, 1].min()))
        X2, Y2 = int(min(W, np.ceil(pp[:, 0].max()))), int(min(H, np.ceil(pp[:, 1].max())))
        if X2 - X1 < 16 or Y2 - Y1 < 16:
            continue
        k, s = modeller.urun_bul(im[Y1:Y2, X1:X2])
        if not len(k):
            continue
        k = k + np.array([X1, Y1, X1, Y1], np.float32)
        ic = [i for i in range(len(k)) if _poly_ici(pp, (k[i, 0] + k[i, 2]) / 2, (k[i, 1] + k[i, 3]) / 2)]
        k, s = k[ic], s[ic]
        if not len(k):
            continue
        kirpintilar = [im[int(a[1]):int(a[3]), int(a[0]):int(a[2])] for a in k]
        kirpintilar = [c if c.size and min(c.shape[:2]) >= 4 else np.zeros((8, 8, 3), np.uint8) for c in kirpintilar]
        v = modeller.gomme(kirpintilar)
        S = v @ v.T
        R = np.stack([renk_ozeti(c) for c in kirpintilar])
        R = R @ R.T
        gozler = []
        for satir in satirlara_ayir(k):
            for grup in komsulari_birlestir(k, satir, lambda i, j: ayni_urun(float(S[i, j]), float(R[i, j]))):
                g = k[grup]
                kutu = [g[:, 0].min(), g[:, 1].min(), g[:, 2].max(), g[:, 3].max()]
                gozler.append({"bolge": b.get("kimlik"), "kutu_px": kutu, "skor": round(float(s[grup].mean()), 3),
                               "adet": len(grup)})
        if etiket_ara and gozler:
            _etiket_kutulari(im, gozler, modeller, (X1, Y1, X2, Y2))
        for g in gozler:
            x1, y1, x2, y2 = g.pop("kutu_px")
            g["kutu"] = _yuvarla([x1 / W, y1 / H, x2 / W, y2 / H])
            e = g.get("etiket")
            g["etiket"] = None if e is None else _yuvarla([e[0] / W, e[1] / H, e[2] / W, e[3] / H])
            out.append(g)
    return {"gozler": out}


def _etiket_kutulari(im: np.ndarray, gozler: list[dict], modeller, cerceve) -> None:
    """Her gözün altındaki fiyat etiketini arar: bölge (biraz aşağı uzatılmış) üzerinde metin bulucu, gözün altındaki
    satırlar okunur; fiyat ayrıştırılabilen satırların birleşimi etiket kutusu olur. Bulunmazsa etiket None."""
    H, W = im.shape[:2]
    X1, Y1, X2, Y2 = cerceve
    ort_h = float(np.median([g["kutu_px"][3] - g["kutu_px"][1] for g in gozler]))
    Y2e = int(min(H, Y2 + 0.5 * ort_h))
    alan = im[Y1:Y2e, X1:X2]
    uzun = int(min(1280, max(640, round(max(alan.shape[:2]) / 32) * 32)))
    kutular, _ = modeller.metin_bul(alan, uzun=uzun)
    if not kutular:
        for g in gozler:
            g["etiket"] = None
        return
    rect = np.array([[b[:, 0].min() + X1, b[:, 1].min() + Y1, b[:, 0].max() + X1, b[:, 1].max() + Y1] for b in kutular])
    aday_ind = set()
    for g in gozler:
        x1, y1, x2, y2 = g["kutu_px"]
        h, w = y2 - y1, x2 - x1
        cx = (rect[:, 0] + rect[:, 2]) / 2
        m = (cx >= x1 - 0.1 * w) & (cx <= x2 + 0.1 * w) & (rect[:, 1] >= y2 - 0.25 * h) & (rect[:, 1] <= y2 + 0.6 * h)
        g["_aday"] = list(np.where(m)[0])
        aday_ind |= set(g["_aday"])
    aday_ind = sorted(aday_ind)
    okunan = dict(zip(aday_ind, modeller.metin_oku([_dondur_kes(alan, kutular[i]) for i in aday_ind]))) if aday_ind else {}
    for g in gozler:
        fiyatli = [i for i in g.pop("_aday") if okunan.get(i, ("", 0))[1] >= 0.5
                   and fiyat_ayristir([okunan[i][0]])["fiyat"] is not None]
        if not fiyatli:
            g["etiket"] = None
            continue
        # gözün altına en yakın satırın çevresindeki fiyatlı satırlar: tek etiket
        en_ust = min(rect[i, 1] for i in fiyatli)
        sec = [i for i in fiyatli if rect[i, 1] <= en_ust + 0.35 * (g["kutu_px"][3] - g["kutu_px"][1])]
        r = rect[sec]
        e = [r[:, 0].min(), r[:, 1].min(), r[:, 2].max(), r[:, 3].max()]
        pw, ph = (e[2] - e[0]) * 0.15, (e[3] - e[1]) * 0.25
        g["etiket"] = [max(0, e[0] - pw), max(0, e[1] - ph), min(W, e[2] + pw), min(H, e[3] + ph)]


def is_etiketler(girdi: dict, modeller, kare: np.ndarray | None = None) -> dict:
    """Girdi {"kare", "kutular": [[x1,y1,x2,y2], ...]} -> {"etiketler": [{"kutu", "metin", "fiyat", "durum"}]}."""
    im = kare if kare is not None else _oku_kare(girdi["kare"])
    ok = EtiketOkuyucu(modeller)
    out = []
    for k in girdi.get("kutular") or []:
        r = ok.oku(im, k)
        out.append({"kutu": _yuvarla(k), "metin": r["metin"], "fiyat": r["fiyat"], "durum": r["durum"]})
    return {"etiketler": out}


def is_urun_tani(girdi: dict, modeller, katalog, kare: np.ndarray | None = None) -> dict:
    """Girdi {"kare", "kutular"} -> {"urunler": [{"kutu", "urun" | None, "benzerlik"}]}.
    Kutu birden çok yüz içeriyorsa dedektörün bulduğu en büyük üç yüz oylanır; yoksa kutunun kendisi eşlenir."""
    im = kare if kare is not None else _oku_kare(girdi["kare"])
    H, W = im.shape[:2]
    if katalog is not None:
        katalog.yukle()
    out = []
    for k in girdi.get("kutular") or []:
        x1, y1, x2, y2 = int(k[0] * W), int(k[1] * H), int(np.ceil(k[2] * W)), int(np.ceil(k[3] * H))
        c = im[max(0, y1):min(H, y2), max(0, x1):min(W, x2)]
        if katalog is None or not len(katalog.kimlikler) or c.size == 0 or min(c.shape[:2]) < 8:
            out.append({"kutu": _yuvarla(k), "urun": None, "benzerlik": 0.0})
            continue
        yuzler = [c]
        if min(c.shape[:2]) >= 32:
            kb, _ = modeller.urun_bul(c)
            if len(kb) >= 2:
                kb = kb[np.argsort(-(kb[:, 2] - kb[:, 0]) * (kb[:, 3] - kb[:, 1]))][:3]
                yuzler = [c[int(b[1]):int(b[3]), int(b[0]):int(b[2])] for b in kb]
                yuzler = [y for y in yuzler if y.size and min(y.shape[:2]) >= 8] or [c]
        v = modeller.gomme(yuzler)
        oy, en = {}, 0.0
        for vv, y in zip(v, yuzler):
            e = katalog.eslestir(vv, y)
            en = max(en, e["benzerlik"])
            if e["urun"]:
                oy[e["urun"]] = oy.get(e["urun"], 0.0) + e["benzerlik"]
        if oy:
            u = max(oy, key=oy.get)
            b = float(katalog.urun_benzerlikleri(v, np.stack([renk_ozeti(y) for y in yuzler]))[
                :, katalog.kimlikler.index(u)].max())
            out.append({"kutu": _yuvarla(k), "urun": u, "benzerlik": round(b, 3)})
        else:
            out.append({"kutu": _yuvarla(k), "urun": None, "benzerlik": round(float(en), 3)})
    return {"urunler": out}


# --- çalıştırıcı -------------------------------------------------------------------------------------------------------
def _yaz(yol: str, veri: dict) -> None:
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False)
    os.replace(gecici, yol)


def calistir(ad: str, girdi: dict, veri: str | None = None, modeller=None) -> dict:
    """blok._gorev_kancasi'nın çağırdığı biçim: işi koşar, sonucu döndürür (dosyayı kanca yazar). Hata olursa
    {"hata": "..."}. `modeller` verilmezse süreçteki ortak Modeller kullanılır."""
    if modeller is None:
        from .raf_modeller import paylasilan

        modeller = paylasilan()
    bas = time.perf_counter()
    try:
        if not isinstance(girdi, dict):
            raise ValueError("girdi bir JSON nesnesi olmalı")
        if ad == "gozler":
            sonuc = is_gozler(girdi, modeller)
        elif ad == "etiketler":
            sonuc = is_etiketler(girdi, modeller)
        elif ad == "urun_tani":
            from .urun import UrunKatalogu

            if not veri:
                raise ValueError("veri klasörü bilinmiyor")
            sonuc = is_urun_tani(girdi, modeller, UrunKatalogu(veri, modeller))
        else:
            raise ValueError(f"bilinmeyen iş: {ad}")
        sonuc["sure_ms"] = round((time.perf_counter() - bas) * 1000, 1)
    except Exception as e:  # panel hatayı kullanıcıya kısa metinle gösterir
        sonuc = {"hata": f"{type(e).__name__}: {e}"}
    return sonuc


def calistir_dosya(ad: str, girdi_yolu: str, cikti_yolu: str, modeller=None, veri: str | None = None) -> dict:
    """Girdi JSON dosyasını okur, işi koşar, çıktıyı `.tmp` + os.replace ile yazar. Dönüş: yazılan sözlük."""
    try:
        with open(girdi_yolu, encoding="utf-8") as f:
            girdi = json.load(f)
    except (OSError, ValueError) as e:
        sonuc = {"hata": f"girdi okunamadı: {type(e).__name__}"}
    else:
        sonuc = calistir(ad, girdi, veri, modeller)
    _yaz(cikti_yolu, sonuc)
    return sonuc


def ortamdan(modeller=None, veri: str | None = None) -> dict | None:
    """RAF_GOREV* ortam değişkenleri varsa işi koşar ve çıktıyı yazar (bir kez çağrılmalı). Yoksa None."""
    ad, girdi, cikti = os.environ.get(ORTAM_GOREV), os.environ.get(ORTAM_GIRDI), os.environ.get(ORTAM_CIKTI)
    if not (ad and girdi and cikti):
        return None
    return calistir_dosya(ad, girdi, cikti, modeller, veri)
