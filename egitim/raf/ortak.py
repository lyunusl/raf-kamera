"""Raf/ürün denemelerinin ortak yardımcıları.

Test fotoğrafları depoya kopyalanmaz: `RAF_TEST_GORSELLERI` ortam değişkeni ya da depo klasörünün yanındaki
`raf-kamera-modeller/test-gorselleri` kullanılır. Çizimler `egitim/cikti/raf/` altına yazılır (git dışı).
Not: bu fotoğraflar el kamerasıyla çekilmiş durağan Commons fotoğraflarıdır; zaman içindeki değişimler fotoğraf
üzerinde düzenlenerek (yama, takas, örtme, parlaklık) taklit edilir. Gerçek mağaza kamerası görüntüsü değildir.
"""
from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOTOR = os.path.join(KOK, "motor")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

GORSELLER = os.environ.get("RAF_TEST_GORSELLERI") or os.path.join(os.path.dirname(KOK), "raf-kamera-modeller",
                                                                   "test-gorselleri")
CIKTI = os.path.join(KOK, "egitim", "cikti", "raf")


def gorsel(ad: str) -> np.ndarray:
    yol = os.path.join(GORSELLER, ad if ad.endswith(".jpg") else ad + ".jpg")
    im = cv2.imread(yol)
    if im is None:
        raise SystemExit(f"test görseli yok: {ad} (RAF_TEST_GORSELLERI ayarlayın)")
    return im


def gorseller_var() -> bool:
    return os.path.isdir(GORSELLER)


def cikti(ad: str) -> str:
    os.makedirs(CIKTI, exist_ok=True)
    return os.path.join(CIKTI, ad)


def modeller(thread: int | None = None):
    from raf_motor.raf_modeller import Modeller

    return Modeller(thread=thread)


def sure_olc(fn, tekrar: int = 5, isinma: int = 1) -> float:
    for _ in range(isinma):
        fn()
    t = []
    for _ in range(tekrar):
        a = time.perf_counter()
        fn()
        t.append((time.perf_counter() - a) * 1000)
    return float(np.median(t))


def ciz_kutular(im: np.ndarray, kutular, renk=(0, 220, 0), yazi=None, kalin=2) -> np.ndarray:
    H, W = im.shape[:2]
    for i, k in enumerate(kutular):
        x1, y1, x2, y2 = int(k[0] * W), int(k[1] * H), int(k[2] * W), int(k[3] * H)
        cv2.rectangle(im, (x1, y1), (x2, y2), renk, kalin)
        if yazi is not None:
            t = str(yazi[i])
            cv2.putText(im, t, (x1 + 2, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
            cv2.putText(im, t, (x1 + 2, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return im
