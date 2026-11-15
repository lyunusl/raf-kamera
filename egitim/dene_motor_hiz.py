"""Bütün zincirin (Raf Video → Kişi → Ürün → Analiz) işlemcide hızı: 1280x720 karede 1, 5 ve 10 kişi.

  set RAF_DENEME_VIDEOLARI=<videoların klasörü>     (teras.mp4'ten arka plan ve kişi kırpıntısı alınır)
  python egitim/dene_motor_hiz.py [iş parçacığı sayısı ...] [giris=640 ...]   ör. "0 4 giris=480" (0 = onnxruntime'ın seçtiği)

Kişiler gerçek bir kareden kırpılıp boş zemine yapıştırılır, hepsi bir raf bölgesinin yanında durur (iskelet ve uzanma
her kişide çalışır: en kötü durum); demografi açıktır. Her kare analiz edilir (kisi_fps 25, video 3 kare/sn).
Ölçülen: analiz edilen kare/sn (bütün bloklar dahil) ve Raf Kişi bloğunun kare başına süresi.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from motor_ortak import Zincir, video_klasoru  # noqa: E402


def kareler(n: int, sayi: int = 24) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video_klasoru() / "teras.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 24)
    ok, fr = cap.read()
    cap.release()
    fr = cv2.resize(fr, (1280, 720))
    kisi = fr[190:340, 230:330].copy()       # oturan kişi (teras.mp4, ~1 sn)
    zemin = fr.copy()
    zemin[150:720, 0:1280] = cv2.resize(fr[560:720, 380:700], (1280, 570))  # kişisiz zemin
    out = []
    for i in range(sayi):
        k = zemin.copy()
        for j in range(n):
            x = 40 + (j % 5) * 240 + (i % 3) * 4
            y = 200 + (j // 5) * 250
            k[y:y + 150, x:x + 100] = kisi
        out.append(k)
    return out


def olc(n: int, is_parcacigi: int, giris: int = 640) -> dict:
    z = Zincir("raf_hiz_")
    try:
        yol = z.veri / "hiz.mp4"
        yaz = cv2.VideoWriter(str(yol), cv2.VideoWriter_fourcc(*"mp4v"), 3, (1280, 720))
        for k in kareler(n):
            yaz.write(k)
        yaz.release()
        if is_parcacigi:
            os.environ["RAF_IS_PARCACIGI"] = str(is_parcacigi)
        else:
            os.environ.pop("RAF_IS_PARCACIGI", None)
        bolgeler = [{"kimlik": "r1", "ad": "Raf", "tur": "raf", "poly": [[0.0, 0.2], [1.0, 0.2], [1.0, 0.95], [0.0, 0.95]]},
                    {"kimlik": "k1", "ad": "Koridor", "tur": "koridor", "poly": [[0.0, 0.2], [1.0, 0.2], [1.0, 1.0], [0.0, 1.0]]}]
        z.kamera("hiz", str(yol), bolgeler, {"demografi": {"acik": True}, "tikali_koridor": {"acik": True}}, kisi_fps=25,
                  kisi_giris=giris)
        sureler, kisi_ms, sayilar = [], [], []
        son = time.perf_counter()
        for s in z.calistir("hiz"):
            if s["v"]["Image"] is None:
                continue
            simdi = time.perf_counter()
            sureler.append(simdi - son)
            son = simdi
            d = s["k"]["Durum"]
            try:
                kisi_ms.append(float(d.split("·")[1].strip().split(" ")[0]))
                sayilar.append(int(d.split(" ")[1]))
            except (IndexError, ValueError):
                pass
        sureler = sureler[4:]  # ısınma (model yükleme) atlanır
        return {"kisi": n, "is_parcacigi": is_parcacigi or "ort", "giris": giris, "gorulen_kisi": int(np.median(sayilar[4:])) if sayilar else 0,
                "kare_sn": round(1.0 / float(np.median(sureler)), 2), "zincir_ms": round(1000 * float(np.median(sureler)), 1),
                "kisi_blok_ms": round(float(np.median(kisi_ms[4:])), 1)}
    finally:
        os.environ.pop("RAF_IS_PARCACIGI", None)
        z.temizle()


if __name__ == "__main__":
    if video_klasoru() is None:
        print("atlandı: RAF_DENEME_VIDEOLARI verilmedi")
        sys.exit(0)
    ipler = [int(a) for a in sys.argv[1:] if not a.startswith("giris=")] or [0, 4]
    girisler = [int(a[6:]) for a in sys.argv[1:] if a.startswith("giris=")] or [640]
    for g in girisler:
        for ip in ipler:
            for n in (1, 5, 10):
                print(json.dumps(olc(n, ip, g), ensure_ascii=False), flush=True)
