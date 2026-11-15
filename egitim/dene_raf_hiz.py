"""Raf/ürün tarafının işlemci süreleri (onnxruntime CPU), 4 iş parçacığı ve tüm çekirdekler.

  python egitim/dene_raf_hiz.py

Ölçülenler (medyan):
- raf kontrolü: 1 bölge / 20 göz ve 3 bölge / 60 göz; (a) her göz değişmiş (ilk kontrol ya da ışık değişimi:
  dedektör + tüm gömmeler), (b) hiçbir göz değişmemiş (periyodik kontrolün olağan hâli), (c) tek göz değişmiş
- gömme önbelleği: 50 ürün x 3 görsel soğuk kurulum ve önbellekten yükleme
- bir etiket okuma; tek seferlik işler: gozler (1 bölge), etiketler (10 kutu), urun_tani (10 kutu)
Sonuç: egitim/cikti/raf/hiz_rapor.json
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raf"))

import ortak  # noqa: E402
from raf_motor.etiket import EtiketOkuyucu  # noqa: E402
from raf_motor.gorev import is_etiketler, is_gozler, is_urun_tani  # noqa: E402
from raf_motor.raf import RafIzleyici  # noqa: E402
from raf_motor.raf_modeller import Modeller  # noqa: E402
from raf_motor.urun import UrunKatalogu  # noqa: E402


def ayar_kur(bolge_sayisi: int, goz: int = 20) -> dict:
    bolgeler = []
    for b in range(bolge_sayisi):
        x0, x1 = 0.12 + b * 0.69 / bolge_sayisi, 0.12 + (b + 1) * 0.69 / bolge_sayisi
        y0, y1 = 0.06, 0.76
        gozler = []
        sat, sut = 4, goz // 4
        for i in range(sat):
            for j in range(sut):
                gx0 = x0 + (x1 - x0) * j / sut
                gy0 = y0 + (y1 - y0) * i / sat
                gozler.append({"kimlik": f"g{b}_{i}_{j}", "kutu": [gx0, gy0, gx0 + (x1 - x0) / sut, gy0 + (y1 - y0) / sat],
                               "urun": f"u{(i * sut + j) % 50}", "adet": 2})
        bolgeler.append({"kimlik": f"b{b}", "ad": "Raf", "tur": "raf",
                         "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "gozler": gozler})
    return {"bolgeler": bolgeler, "raf_araligi_sn": 10}


def katalog_kur(veri: str, m) -> list:
    """50 ürün x 3 görsel: test fotoğraflarındaki ürün yüzlerinden."""
    os.makedirs(os.path.join(veri, "urunler", "gorsel"), exist_ok=True)
    yuzler = []
    for ad in ("raf_41", "raf_13", "raf_43", "raf_02"):
        im = ortak.gorsel(ad)
        k, _ = m.urun_bul(im)
        yuzler += [im[int(b[1]):int(b[3]), int(b[0]):int(b[2])] for b in k if (b[2] - b[0]) > 20 and (b[3] - b[1]) > 20]
    urunler = []
    for u in range(50):
        gorseller = []
        for j in range(3):
            d = f"u{u}_{j}.jpg"
            cv2.imwrite(os.path.join(veri, "urunler", "gorsel", d), yuzler[(u * 3 + j) % len(yuzler)])
            gorseller.append(d)
        urunler.append({"kimlik": f"u{u}", "ad": f"Ürün {u}", "gorseller": gorseller})
    with open(os.path.join(veri, "urunler", "urunler.json"), "w", encoding="utf-8") as f:
        json.dump(urunler, f)
    return yuzler


def olc(thread):
    m = Modeller(thread=thread)
    out = {}
    im = ortak.gorsel("raf_41")
    veri = tempfile.mkdtemp(prefix="raf_hiz_")
    katalog_kur(veri, m)
    onb = os.path.join(veri, "urunler", "gomme-onbellek.npz")
    m.gomme([im[:64, :64]])  # oturumu ısıt
    soguk = []
    for _ in range(3):
        if os.path.exists(onb):
            os.remove(onb)
        a = time.perf_counter()
        UrunKatalogu(veri, m).yukle()
        soguk.append((time.perf_counter() - a) * 1000)
    out["katalog_50x3_soguk_ms"] = round(float(np.median(soguk)))
    out["katalog_50x3_onbellek_ms"] = round(ortak.sure_olc(lambda: UrunKatalogu(veri, m).yukle(), 3))
    kat = UrunKatalogu(veri, m)
    kat.yukle()
    for n in (1, 3):
        ayar = ayar_kur(n)
        sure_tum, sure_yok, sure_bir, sure_isik = [], [], [], []
        baska = cv2.resize(ortak.gorsel("raf_13"), (im.shape[1], im.shape[0]))
        for tekrar in range(3):
            iz = RafIzleyici(ayar, m, katalog=kat, referans=im)
            iz.guncelle(im, 0.0)  # referans + ilk kontrol
            a = time.perf_counter()
            iz.guncelle(cv2.convertScaleAbs(im, alpha=0.6, beta=40), 5.0 + 10.0)  # pozlama değişimi (düzeltilir)
            sure_isik.append((time.perf_counter() - a) * 1000)
            a = time.perf_counter()
            iz.guncelle(baska, 30.0)  # bütün gözler değişmiş (başka raf)
            sure_tum.append((time.perf_counter() - a) * 1000)
            iz.guncelle(im, 40.0)
            iz.guncelle(im, 50.0)
            iz.guncelle(im, 20.0 + 40.0)
            a = time.perf_counter()
            iz.guncelle(im, 70.0)
            sure_yok.append((time.perf_counter() - a) * 1000)
            k2 = im.copy()
            g = ayar["bolgeler"][0]["gozler"][5]["kutu"]
            H, W = im.shape[:2]
            k2[int(g[1] * H):int(g[3] * H), int(g[0] * W):int(g[2] * W)] = 128
            a = time.perf_counter()
            iz.guncelle(k2, 80.0)
            sure_bir.append((time.perf_counter() - a) * 1000)
        out[f"kontrol_{n}bolge_{20 * n}goz_hepsi_degismis_ms"] = round(float(np.median(sure_tum)))
        out[f"kontrol_{n}bolge_{20 * n}goz_pozlama_degisimi_ms"] = round(float(np.median(sure_isik)), 1)
        out[f"kontrol_{n}bolge_{20 * n}goz_degisim_yok_ms"] = round(float(np.median(sure_yok)), 1)
        out[f"kontrol_{n}bolge_{20 * n}goz_tek_goz_degismis_ms"] = round(float(np.median(sure_bir)))
    e = EtiketOkuyucu(m)
    im7 = ortak.gorsel("etiket_47")
    H, W = im7.shape[:2]
    kutu = [115 / W, 645 / H, 262 / W, 745 / H]
    out["etiket_okuma_ms"] = round(ortak.sure_olc(lambda: e.oku(im7, kutu), 5), 1)
    out["is_gozler_raf41_ms"] = round(ortak.sure_olc(lambda: is_gozler(
        {"bolgeler": [{"kimlik": "b1", "poly": [[0.12, 0.05], [0.81, 0.05], [0.81, 0.94], [0.12, 0.94]]}]}, m, kare=im), 2))
    kutular = [[0.1 * i, 0.3, 0.1 * i + 0.08, 0.5] for i in range(10)]
    out["is_etiketler_10_ms"] = round(ortak.sure_olc(lambda: is_etiketler({"kutular": kutular}, m, kare=im7), 2))
    out["is_urun_tani_10_ms"] = round(ortak.sure_olc(lambda: is_urun_tani({"kutular": kutular}, m, kat, kare=im), 2))
    shutil.rmtree(veri, ignore_errors=True)
    return out


def main():
    rapor = {"cekirdek": os.cpu_count()}
    for thread in (4, None):
        ad = "thread_4" if thread else "thread_tum"
        rapor[ad] = olc(thread)
        print(ad, json.dumps(rapor[ad], ensure_ascii=False))
    with open(ortak.cikti("hiz_rapor.json"), "w", encoding="utf-8") as f:
        json.dump(rapor, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    if not ortak.gorseller_var():
        print("test görselleri yok: RAF_TEST_GORSELLERI")
        sys.exit(0)
    main()
