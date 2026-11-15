"""Gerçek raf fotoğraflarından göz ayarı, ürün kataloğu ve düzenlenmiş kare dizileri kurar.

UYARI: bunlar durağan fotoğraflar üzerinde yapılan düzenlemelerdir (gerçek kamera akışı değildir):
- boşaltma: aynı fotoğraftaki gerçek boş raf/arka panel alanından alınan yama göze döşenir (BOS_KAYNAK)
- azaltma: gözün sağdaki yüzleri aynı yamayla örtülür
- yanlış ürün: başka bir gözün kırpıntısı bu göze ölçeklenip yapıştırılır
- kapalı: göze kişi biçimli koyu bir leke çizilir ve Raf Kişi çıktısı gibi bir kişi kutusu verilir
- ışık: kazanç/ofset/gama değişimi; her kareye hafif gürültü + JPEG sıkıştırma eklenir
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np

import ortak
from raf_motor.gorev import ayni_urun, is_gozler, renk_ozeti

# fotoğraf: raf bölgesi (0-1) ve aynı fotoğraftaki gerçek boş alan (piksel x1,y1,x2,y2) — elle seçildi
FOTOLAR = {
    "raf_41": {"poly": [[0.12, 0.05], [0.81, 0.05], [0.81, 0.77], [0.12, 0.77]], "bos": None},
    "raf_43": {"poly": [[0.36, 0.1], [1.0, 0.1], [1.0, 0.75], [0.36, 0.75]], "bos": (585, 290, 660, 343)},
    "raf_44": {"poly": [[0.57, 0.0], [1.0, 0.0], [1.0, 1.0], [0.57, 1.0]], "bos": (1092, 296, 1108, 540)},
    "raf_08": {"poly": [[0.07, 0.15], [0.9, 0.15], [0.9, 0.95], [0.07, 0.95]], "bos": (880, 480, 1060, 545)},
    "raf_13": {"poly": [[0.2, 0.1], [0.82, 0.1], [0.82, 0.7], [0.2, 0.7]], "bos": None},
}


def gurultu(im: np.ndarray, rng: np.random.Generator, sigma: float = 2.0, q: int = 85) -> np.ndarray:
    k = np.clip(im.astype(np.float32) + rng.normal(0, sigma, im.shape), 0, 255).astype(np.uint8)
    ok, j = cv2.imencode(".jpg", k, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(j, cv2.IMREAD_COLOR)


def isik(im: np.ndarray, kazanc: float = 1.0, ofset: float = 0.0, gama: float = 1.0) -> np.ndarray:
    x = im.astype(np.float32) / 255.0
    x = np.power(np.clip(x, 0, 1), gama) * kazanc + ofset / 255.0
    return np.clip(x * 255, 0, 255).astype(np.uint8)


def bos_yama(im: np.ndarray, kaynak, w: int, h: int) -> np.ndarray:
    x1, y1, x2, y2 = kaynak
    p = im[y1:y2, x1:x2]
    p = cv2.resize(p, (p.shape[1], h), interpolation=cv2.INTER_LINEAR)
    n = int(np.ceil(w / p.shape[1]))
    return np.hstack([p] * n)[:, :w]


def bosalt(im: np.ndarray, kaynak, kutu_px, oran_sol: float = 0.0) -> np.ndarray:
    """Kutunun (piksel) [oran_sol, 1] yatay kısmını boş yamayla örter."""
    out = im.copy()
    x1, y1, x2, y2 = (int(v) for v in kutu_px)
    xa = int(x1 + (x2 - x1) * oran_sol)
    if x2 - xa < 2 or y2 - y1 < 2:
        return out
    out[y1:y2, xa:x2] = bos_yama(im, kaynak, x2 - xa, y2 - y1)
    return out


def yapistir(im: np.ndarray, kaynak_px, hedef_px) -> np.ndarray:
    out = im.copy()
    a = [int(v) for v in kaynak_px]
    b = [int(v) for v in hedef_px]
    c = im[a[1]:a[3], a[0]:a[2]]
    out[b[1]:b[3], b[0]:b[2]] = cv2.resize(c, (b[2] - b[0], b[3] - b[1]), interpolation=cv2.INTER_AREA)
    return out


def kisi_ciz(im: np.ndarray, kutu_px) -> np.ndarray:
    """Kişi biçimli koyu leke (baş + gövde), kişi kutusunun içinde."""
    out = im.copy()
    x1, y1, x2, y2 = (int(v) for v in kutu_px)
    w, h = x2 - x1, y2 - y1
    renk = (70, 60, 55)
    cv2.ellipse(out, (x1 + w // 2, y1 + h // 8), (max(2, w // 6), max(2, h // 9)), 0, 0, 360, (90, 110, 150), -1)
    cv2.rectangle(out, (x1 + w // 5, y1 + h // 5), (x2 - w // 5, y1 + int(h * 0.65)), renk, -1)
    cv2.rectangle(out, (x1 + w // 4, y1 + int(h * 0.65)), (x2 - w // 4, y2), (50, 45, 60), -1)
    return out


class Kurulum:
    """Bir fotoğraf için kamera ayarı, katalog (geçici VERI) ve göz bilgileri."""

    def __init__(self, ad: str, m, veri: str):
        self.ad, self.m, self.veri = ad, m, veri
        self.im = ortak.gorsel(ad)
        self.H, self.W = self.im.shape[:2]
        f = FOTOLAR[ad]
        self.bos = f["bos"]
        r = is_gozler({"bolgeler": [{"kimlik": "b1", "poly": f["poly"]}]}, m, etiket_ara=False, kare=self.im)
        gozler = [g for g in r["gozler"] if (g["kutu"][2] - g["kutu"][0]) * self.W >= 20 and
                  (g["kutu"][3] - g["kutu"][1]) * self.H >= 20]
        self.gozler = []
        # katalog: her gözün ilk yüzü; aynı ürün kuralına uyan gözler aynı ürün kimliğini paylaşır
        os.makedirs(os.path.join(veri, "urunler", "gorsel"), exist_ok=True)
        os.makedirs(os.path.join(veri, "ayar"), exist_ok=True)
        yuzler = []
        for g in gozler:
            px = self.px(g["kutu"])
            w1 = (px[2] - px[0]) / g["adet"]
            yuzler.append(self.im[int(px[1]):int(px[3]), int(px[0]):int(px[0] + w1)])
        v = m.gomme(yuzler)
        rk = [renk_ozeti(y) for y in yuzler]
        urunler, kimlik = [], []
        for i, g in enumerate(gozler):
            u = None
            for j in range(i):
                if ayni_urun(float(v[i] @ v[j]), float(rk[i] @ rk[j])):
                    u = kimlik[j]
                    break
            if u is None:
                u = f"u{i}"
                dosya = f"{ad}_{u}.jpg"
                cv2.imwrite(os.path.join(veri, "urunler", "gorsel", dosya), yuzler[i])
                urunler.append({"kimlik": u, "ad": f"{ad} ürün {i}", "fiyat": None, "gorseller": [dosya]})
            kimlik.append(u)
            self.gozler.append({"kimlik": f"g{i}", "kutu": g["kutu"], "urun": u, "adet": g["adet"], "etiket": None,
                                "fiyat": None})
        with open(os.path.join(veri, "urunler", "urunler.json"), "w", encoding="utf-8") as fh:
            json.dump(urunler, fh, ensure_ascii=False)
        self.urun_sayisi = len(urunler)
        self.ayar = {"kod": ad, "ad": ad, "bolgeler": [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": f["poly"],
                                                         "gozler": self.gozler}],
                     "raf_araligi_sn": 10, "ozellikler": {}}

    def px(self, k):
        return [k[0] * self.W, k[1] * self.H, k[2] * self.W, k[3] * self.H]

    def hedefler(self, n: int, en_az_adet: int = 1, farkli_urun: bool = False) -> list[int]:
        """Birbirinden uzak `n` göz (yeterince geniş)."""
        aday = [i for i, g in enumerate(self.gozler) if g["adet"] >= en_az_adet]
        if not aday:
            return []
        sec = [aday[len(aday) // (n + 1) * (k + 1) % len(aday)] for k in range(n)]
        return sorted(set(sec))
