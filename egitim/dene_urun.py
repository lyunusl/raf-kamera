"""Ürün eşleme (urun.py) gerçek raf fotoğraflarında.

  python egitim/dene_urun.py

Kurulum: her fotoğrafta raf bölgesi `gozler` mantığıyla gözlere ayrılır (dedektör + satır + komşu birleştirme).
Birden çok yüzü olan her gözün ilk yüzü katalog ürünü olur (tek görsel), diğer yüzleri sorgudur (aynı ürünün başka
fiziksel paketi). Tek yüzlü gözler yalnızca katalogda (karıştırıcı) bulunur. Sorgular ayrıca kaydırılmış (%10),
büyütülmüş (%15), küçültülmüş (%10), uzaktan (0.4 ölçek) ve karartılmış (0.7) kırpıntılarla denenir.
Ölçülenler: ilk-1 doğru / yanlış / boş (null), aynı ve farklı ürün benzerlik dağılımı, benzer çeşitlerde (en yakın
başka ürün >= 0.75) ikinci aşama (SIFT) açık/kapalı, katalogda olmayan ürünün reddi (kendi ürünü çıkarılınca null).
Not: göz birleştirme hatası olan gözlerde "aynı ürün" etiketi gürültülüdür; aynı ürünün iki ayrı gözü varsa
diğer gözün ürününe eşleşme "yanlış" sayılır (alt sınır).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raf"))

import ortak  # noqa: E402
import senaryo as S  # noqa: E402
from raf_motor import urun as U  # noqa: E402
from raf_motor.gorev import ayni_urun, komsulari_birlestir, renk_ozeti, satirlara_ayir  # noqa: E402

FOTOLAR = ["raf_41", "raf_13", "raf_43", "raf_44", "raf_08", "raf_02"]
DONUSUM = ["asil", "kayik", "buyuk", "kucuk", "uzak", "karanlik"]


def yuz_gruplari(m, im, poly):
    H, W = im.shape[:2]
    pp = np.array(poly, np.float32) * [W, H]
    X1, Y1, X2, Y2 = int(pp[:, 0].min()), int(pp[:, 1].min()), int(pp[:, 0].max()), int(pp[:, 1].max())
    k, _ = m.urun_bul(im[Y1:Y2, X1:X2])
    k = k + np.array([X1, Y1, X1, Y1], np.float32)
    cr = [im[int(a[1]):int(a[3]), int(a[0]):int(a[2])] for a in k]
    v = m.gomme(cr)
    R = np.stack([renk_ozeti(c) for c in cr])
    S_, RR = v @ v.T, R @ R.T
    gruplar = []
    for satir in satirlara_ayir(k):
        gruplar += komsulari_birlestir(k, satir, lambda i, j: ayni_urun(float(S_[i, j]), float(RR[i, j])))
    return k, gruplar


def donustur(im, b, tur):
    H, W = im.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in b)
    w, h = x2 - x1, y2 - y1
    if tur == "kayik":
        x1, x2, y1, y2 = x1 + 0.1 * w, x2 + 0.1 * w, y1 + 0.05 * h, y2 + 0.05 * h
    elif tur == "buyuk":
        x1, x2, y1, y2 = x1 - 0.15 * w, x2 + 0.15 * w, y1 - 0.15 * h, y2 + 0.15 * h
    elif tur == "kucuk":
        x1, x2, y1, y2 = x1 + 0.1 * w, x2 - 0.1 * w, y1 + 0.1 * h, y2 - 0.1 * h
    x1, y1, x2, y2 = int(max(0, x1)), int(max(0, y1)), int(min(W, x2)), int(min(H, y2))
    c = im[y1:y2, x1:x2]
    if tur == "uzak":
        c = cv2.resize(c, (max(8, int(c.shape[1] * 0.4)), max(8, int(c.shape[0] * 0.4))), interpolation=cv2.INTER_AREA)
    elif tur == "karanlik":
        c = S.isik(c, 0.7)
    return c


def main():
    m = ortak.modeller()
    veri = tempfile.mkdtemp(prefix="raf_urun_")
    os.makedirs(os.path.join(veri, "urunler", "gorsel"))
    urunler, sorgular = [], []  # sorgu: (ürün kimliği, foto, kutu)
    for ad in FOTOLAR:
        im = ortak.gorsel(ad)
        poly = S.FOTOLAR.get(ad, {}).get("poly", [[0, 0], [1, 0], [1, 1], [0, 1]])
        k, gruplar = yuz_gruplari(m, im, poly)
        for gi, grup in enumerate(gruplar):
            b = k[grup[0]]
            c = im[int(b[1]):int(b[3]), int(b[0]):int(b[2])]
            if min(c.shape[:2]) < 12:
                continue
            u = f"{ad}_{gi}"
            cv2.imwrite(os.path.join(veri, "urunler", "gorsel", u + ".jpg"), c)
            urunler.append({"kimlik": u, "ad": u, "gorseller": [u + ".jpg"]})
            for j in grup[1:4]:
                sorgular.append((u, ad, k[j]))
    with open(os.path.join(veri, "urunler", "urunler.json"), "w", encoding="utf-8") as f:
        json.dump(urunler, f)
    kat = U.UrunKatalogu(veri, m)
    a = time.perf_counter()
    st = kat.yukle()
    print(f"katalog: {st} ({(time.perf_counter() - a) * 1000:.0f} ms), sorgu yüzü: {len(sorgular)}")
    a = time.perf_counter()
    st2 = U.UrunKatalogu(veri, m).yukle()
    print(f"önbellekten yeniden yükleme: {st2} ({(time.perf_counter() - a) * 1000:.0f} ms)")

    imler = {ad: ortak.gorsel(ad) for ad in FOTOLAR}
    rapor = {"katalog": st, "sorgu": len(sorgular)}
    ayni_s, fark_s = [], []
    for tur in DONUSUM:
        kirp = [donustur(imler[ad], b, tur) for _, ad, b in sorgular]
        v = m.gomme(kirp)
        sk = kat.urun_benzerlikleri(v, np.stack([U.renk_ozeti(c) for c in kirp]))
        sonuc = {}
        for asama in (True, False):
            kat.ikinci_asama = asama
            d = y = n = 0
            benzer = {"d": 0, "y": 0, "n": 0, "toplam": 0}
            for i, (u, ad, b) in enumerate(sorgular):
                e = kat.eslestir(v[i], kirp[i])
                p = kat.kimlikler.index(u)
                diger = np.delete(sk[i], p).max() if sk.shape[1] > 1 else -1
                r = "d" if e["urun"] == u else ("n" if e["urun"] is None else "y")
                d += r == "d"
                y += r == "y"
                n += r == "n"
                if diger >= 0.75:
                    benzer["toplam"] += 1
                    benzer[r] += 1
                if tur == "asil" and asama:
                    ayni_s.append(float(sk[i, p]))
                    fark_s.append(float(diger))
            sonuc["sift" if asama else "yalniz_gomme"] = {"dogru": d, "yanlis": y, "bos": n, "benzer_cesit": benzer}
        # katalogda olmayan ürün: kendi ürünü çıkarılınca null dönmeli (varsayılan ayar: ikinci aşama kapalı)
        kat.ikinci_asama = False
        sahip0 = kat.sahip.copy()
        iddia = 0
        for i, (u, ad, b) in enumerate(sorgular):
            p = kat.kimlikler.index(u)
            kat.sahip = np.where(sahip0 == p, -1, sahip0)
            if kat.eslestir(v[i], kirp[i])["urun"] is not None:
                iddia += 1
        kat.sahip = sahip0
        sonuc["katalogda_yok_iddia"] = iddia
        rapor[tur] = sonuc
        print(tur, json.dumps(sonuc, ensure_ascii=False))
    a, f = np.array(ayni_s), np.array(fark_s)
    rapor["benzerlik"] = {"ayni_ort": round(a.mean(), 3), "ayni_min": round(a.min(), 3), "ayni_p5": round(np.percentile(a, 5), 3),
                          "fark_en_yakin_ort": round(f.mean(), 3), "fark_en_yakin_max": round(f.max(), 3),
                          "fark_en_yakin_p95": round(np.percentile(f, 95), 3),
                          "not": "puan = 0.7 gömme + 0.3 renk",
                          "ayni_esik_ustu": round(float((a >= U.ESIK).mean()), 3),
                          "fark_esik_ustu": round(float((f >= U.ESIK).mean()), 3)}
    print("benzerlik:", rapor["benzerlik"])
    with open(ortak.cikti("urun_rapor.json"), "w", encoding="utf-8") as fh:
        json.dump(rapor, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    if not ortak.gorseller_var():
        print("test görselleri yok: RAF_TEST_GORSELLERI")
        sys.exit(0)
    main()
