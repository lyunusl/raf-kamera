"""Yüz gizleme sınaması: Kayitci'ye (son kare, olay karesi, klip) pikselleştirilmemiş bir baş bölgesi ulaşırsa KALIR.

  python egitim/dene_motor_yuz.py                      (yapay bölüm her zaman çalışır)
  set RAF_DENEME_VIDEOLARI=<videoların klasörü>         (varsa gerçek video bölümü de çalışır)

Yapay bölüm: rastgele gürültülü karede Raf Analiz'e elle kişi listesi verilir. Kayitci'ye yalnızca analiz edilen kareler
gider (aradaki karelerde yeni giren kişinin başı bilinmez); analiz edilmeyen kare yalnızca blok çıkışında görünür. Her ikisinde
  - analiz edilen karedeki baş kutuları, - analiz edilmeyen (tahmini, kaydırılmış) karedeki baş kutuları,
  - izi olmayan tespitlerin ("gizle") başları, - "baslar" listesindeki ikinci (yedek) bölge pikselli olmalı;
  - Raf Kişi hata verirse Kayitci'ye hiç kare gitmemeli ve blok çıkışı boş (siyah) olmalı.
Gerçek video bölümü: teras.mp4 ve kasa.mp4'ün ilk saniyeleri önce her karede analiz edilerek (kisi_fps 25) her karenin
baş kutuları çıkarılır; sonra olağan ayarla (kisi_fps 3, aradaki karelerde tahmin) çalıştırılır ve Kayitci'ye giden her
karede o karenin (her karede bulunan) baş kutularının ortası pikselli mi diye bakılır.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from motor_ortak import Zincir, video_klasoru  # noqa: E402

sonuc: list[tuple[str, bool]] = []


def denetle(ad, kosul, ek=""):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad + (f" ({ek})" if ek else ""), flush=True)


def pikselli(fr: np.ndarray, b, ic: float = 0.5, esik: float = 0.6) -> float:
    """Kutunun iç kısmında yatay komşusuyla aynı olan piksel oranı (pikselleştirilmiş bölgede yüksek, doğal görüntüde düşük)."""
    H, W = fr.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in b[:4])
    w, h = x2 - x1, y2 - y1
    a1, b1 = int(max(0, x1 + (1 - ic) / 2 * w)), int(max(0, y1 + (1 - ic) / 2 * h))
    a2, b2 = int(min(W, x2 - (1 - ic) / 2 * w)), int(min(H, y2 - (1 - ic) / 2 * h))
    if a2 - a1 < 3 or b2 - b1 < 2:
        return 1.0
    p = fr[b1:b2, a1:a2].astype(np.int16)
    return float((np.abs(p[:, 1:] - p[:, :-1]).sum(2) == 0).mean())


def kayitciyi_dinle(blok_modulu, kayit: list) -> None:
    Kayitci = sys.modules["raf_motor.kayit"].Kayitci
    asil = Kayitci.kare

    def kare(self, t, cizili, sonuc_, temiz=None, **ek):
        kayit.append((t, cizili.copy()))
        if temiz is not None:  # temiz_kare.jpg kopyası (çizimsiz) da aynı denetimden geçer
            kayit.append((t, temiz.copy()))
        return asil(self, t, cizili, sonuc_, temiz, **ek)

    Kayitci.kare = kare


# ------------------------------------------------------------------------------------------------ yapay
print("Yapay kareler")
z = Zincir("raf_yuz_")
z.kamera("yz", "yok.mp4", [{"kimlik": "r1", "ad": "Raf", "tur": "raf", "poly": [[0.05, 0.05], [0.5, 0.05], [0.5, 0.5], [0.05, 0.5]]}])
# blok modülünü zincirin motor kopyasından yükle
_ = list(z.calistir("yz"))  # video yok: hata durumu, yalnızca modülleri yükler
blok = z.blok()
kayit: list = []
kayitciyi_dinle(blok, kayit)
rng = np.random.default_rng(3)
st: dict = {}
kisi = {"iz": 1, "b": [100, 60, 180, 300], "durum": "izleniyor", "bas": [120, 60, 160, 110], "baslar": [[120, 60, 160, 110], [95, 50, 185, 140]]}
gizle = {"iz": None, "durum": "gizle", "baslar": [[300, 40, 340, 90]]}
for i in range(6):
    yeni = i % 3 == 0
    k = dict(kisi)
    if not yeni:  # tahmini konum: kutu ve baş kaydırılmış
        d = 6 * (i % 3)
        k.update(b=[100 + d, 60, 180 + d, 300], bas=[120 + d, 60, 160 + d, 110], baslar=[[120 + d, 60, 160 + d, 110], [95 + d, 50, 185 + d, 140]])
    js = json.dumps({"sira": i // 3 + 1, "yeni": yeni, "t": i * 0.1, "boyut": [480, 360], "kisiler": [k, gizle]})
    fr = rng.integers(0, 255, (360, 480, 3), dtype=np.uint8)
    n0 = len(kayit)
    cikis = blok.analiz(st, fr, js, '{"sira": 1, "gozler": []}', "yz#y1", i * 0.1, False)
    oran = min(pikselli(cikis[0], b, 0.9) for b in k["baslar"] + gizle["baslar"])
    if yeni:
        oran = min(oran, min(pikselli(kk[1], b, 0.9) for kk in kayit[n0:] for b in k["baslar"] + gizle["baslar"]) if len(kayit) > n0 else 0.0)
        denetle(f"kare {i} (analiz): Kayitci'ye gitti (+ temiz kopya), bütün baş bölgeleri pikselli", len(kayit) == n0 + 2 and oran >= 0.6, f"oran {oran:.2f}")
    else:
        denetle(f"kare {i} (tahmin): Kayitci'ye gitmedi, blok çıkışında baş bölgeleri pikselli", len(kayit) == n0 and oran >= 0.6, f"oran {oran:.2f}")
n_once = len(kayit)
cikis = blok.analiz(st, rng.integers(0, 255, (360, 480, 3), dtype=np.uint8), '{"hata": "kisi yok"}', '{"sira": 1, "gozler": []}', "yz#y1", 1.0, False)
denetle("Raf Kişi hata verirse Kayitci'ye kare gitmez, çıkış boş", len(kayit) == n_once and not cikis[0].any())
blok.kapat(st)
z.temizle()

# ------------------------------------------------------------------------------------------------ gerçek video
kl = video_klasoru()
if kl is None:
    print("Gerçek video bölümü atlandı (RAF_DENEME_VIDEOLARI yok)")
else:
    for ad, sure in (("teras.mp4", 6.0), ("kasa.mp4", 6.0)):
        print(f"Gerçek video: {ad} ({sure:.0f} sn)")
        bolgeler = [{"kimlik": "r1", "ad": "Raf", "tur": "raf", "poly": [[0.3, 0.3], [0.9, 0.3], [0.9, 0.9], [0.3, 0.9]]}]
        # 1) her kare analiz: o karenin baş kutuları
        z = Zincir("raf_yuz_")
        z.kamera("yr", str(kl / ad), bolgeler, kisi_fps=25)
        referans = {}
        for s in z.calistir("yr"):
            if s["v"]["Image"] is None:
                continue
            t = round(float(s["v"]["Zaman"]), 3)
            if t > sure:
                break
            k = json.loads(s["k"]["Kisiler"])
            referans[t] = [p["bas"] for p in k["kisiler"] if p.get("durum") == "izleniyor" and p.get("bas")
                           and (p["bas"][3] - p["bas"][1]) >= 12]
        z.temizle()
        # 2) olağan koşu, Kayitci'ye giden kareler
        z = Zincir("raf_yuz_")
        z.kamera("yr", str(kl / ad), bolgeler, kisi_fps=3)
        kayit = []
        dinlendi = False
        for s in z.calistir("yr"):
            if not dinlendi and "raf_motor.kayit" in sys.modules:
                kayitciyi_dinle(z.blok(), kayit)
                dinlendi = True
            if s["v"]["Image"] is not None and float(s["v"]["Zaman"]) > sure:
                break
        z.temizle()
        kotu, toplam, en_kotu = 0, 0, 1.0
        for t, cz in kayit:
            for b in referans.get(round(t, 3), []):
                toplam += 1
                o = pikselli(cz, b, 0.5)
                en_kotu = min(en_kotu, o)
                kotu += o < 0.6
        denetle(f"{ad}: Kayitci'ye giden {len(kayit)} karede, her karede bulunan {toplam} baş bölgesinin ortası pikselli",
                toplam > 0 and kotu == 0, f"pikselsiz {kotu}, en düşük oran {en_kotu:.2f}")

kalan = [ad for ad, ok in sonuc if not ok]
print(f"\n{len(sonuc) - len(kalan)}/{len(sonuc)} denetim geçti" + (f" · kalanlar: {kalan}" if kalan else ""))
sys.exit(1 if kalan else 0)
