"""`gozler` işini test fotoğraflarında koşar ve önerilen gözleri (yeşil, adet), etiket kutularını (sarı) ve ham
dedektör kutularını (ince mavi) çizer: egitim/cikti/raf/gozler_<ad>.jpg. Göz kontrolü için.

Kullanım: python egitim/raf/goz_oner_ciz.py raf_41 raf_13 ...   (bölge: tüm kare ya da BOLGELER içindeki poligon)
"""
from __future__ import annotations

import json
import sys
import time

import cv2
import numpy as np

import ortak
from raf_motor.gorev import is_gozler

# fotoğraf başına raf bölgesi (0-1 poligon); verilmeyen fotoğrafta tüm kare
BOLGELER = {
    "raf_41": [[0.12, 0.05], [0.81, 0.05], [0.81, 0.94], [0.12, 0.94]],
    "raf_43": [[0.36, 0.08], [1.0, 0.0], [1.0, 1.0], [0.36, 1.0]],
    "raf_44": [[0.0, 0.0], [0.53, 0.0], [0.53, 1.0], [0.0, 1.0]],
}


def main(adlar):
    m = ortak.modeller()
    rapor = {}
    for ad in adlar:
        im = ortak.gorsel(ad)
        poly = BOLGELER.get(ad, [[0, 0], [1, 0], [1, 1], [0, 1]])
        a = time.perf_counter()
        r = is_gozler({"bolgeler": [{"kimlik": "b1", "poly": poly}]}, m, kare=im)
        ms = (time.perf_counter() - a) * 1000
        k, _ = m.urun_bul(im)
        c = im.copy()
        H, W = c.shape[:2]
        for b in k:
            cv2.rectangle(c, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (255, 120, 0), 1)
        g = r["gozler"]
        ortak.ciz_kutular(c, [x["kutu"] for x in g], (0, 220, 0), [f"{i}:{x['adet']}" for i, x in enumerate(g)])
        ortak.ciz_kutular(c, [x["etiket"] for x in g if x["etiket"]], (0, 230, 255))
        cv2.polylines(c, [(np.array(poly) * [W, H]).astype(np.int32)], True, (0, 0, 255), 2)
        cv2.imwrite(ortak.cikti(f"gozler_{ad}.jpg"), c, [cv2.IMWRITE_JPEG_QUALITY, 85])
        rapor[ad] = {"goz": len(g), "yuz": int(sum(x["adet"] for x in g)), "etiketli": sum(1 for x in g if x["etiket"]),
                     "ms": round(ms)}
        print(ad, rapor[ad])
    with open(ortak.cikti("gozler_rapor.json"), "w", encoding="utf-8") as f:
        json.dump(rapor, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ["raf_41", "raf_13", "raf_44", "raf_02", "raf_08", "raf_43", "raf_07", "etiket_47"])
