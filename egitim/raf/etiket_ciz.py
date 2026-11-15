"""Bir fotoğrafın tamamında metin satırlarını bulup okur, numaralı kutularla çizer (etiket kutularını elle seçmek için).

Kullanım: python egitim/raf/etiket_ciz.py etiket_30 raf_08 ...  -> egitim/cikti/raf/metin_<ad>.jpg + satır listesi
"""
from __future__ import annotations

import sys

import cv2

import ortak
from raf_motor.etiket import _dondur_kes, fiyat_ayristir

sys.stdout.reconfigure(encoding="utf-8")


def main(adlar):
    m = ortak.modeller()
    for ad in adlar:
        im = ortak.gorsel(ad)
        kutular, _ = m.metin_bul(im, uzun=1280)
        okunan = m.metin_oku([_dondur_kes(im, b) for b in kutular])
        c = im.copy()
        print(f"## {ad}")
        for i, (b, (t, g)) in enumerate(zip(kutular, okunan)):
            x1, y1, x2, y2 = int(b[:, 0].min()), int(b[:, 1].min()), int(b[:, 0].max()), int(b[:, 1].max())
            f = fiyat_ayristir([t])["fiyat"]
            renk = (0, 0, 255) if f is not None else (255, 150, 0)
            cv2.rectangle(c, (x1, y1), (x2, y2), renk, 1)
            cv2.putText(c, str(i), (x1, max(10, y1 - 2)), 0, 0.45, renk, 1)
            if f is not None or g > 0.8:
                print(f"  {i}: [{x1},{y1},{x2},{y2}] {t!r} g={g:.2f} fiyat={f}")
        cv2.imwrite(ortak.cikti(f"metin_{ad}.jpg"), c)


if __name__ == "__main__":
    main(sys.argv[1:])
