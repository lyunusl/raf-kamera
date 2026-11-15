"""Blok kancaları (raf.analiz / raf.analiz_sonucu / raf.bitir, gorev.calistir) blok.py'nin çağırdığı biçimde.

  python egitim/dene_raf_kanca.py

Raf Ürün ve Raf Analiz'in kanca çağrıları sırayla taklit edilir (2 sn'de bir kare). Kareler raf_43 fotoğrafının
düzenlenmiş hâlidir (gerçek kamera değil): 30. sn'den sonra iki göz boşalır, 10-20 sn arası bir kişi bir gözün önünde
durur, 60. sn'de bir uzanma biter ve o gözden bir yüz eksilir. Referans kayıtlı dosyadan okunur.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raf"))

import ortak  # noqa: E402
import senaryo as S  # noqa: E402
from raf_motor import gorev, raf  # noqa: E402

sonuc = []


def denetle(ad, kosul):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad, flush=True)


if not ortak.gorseller_var():
    print("test görselleri yok: RAF_TEST_GORSELLERI")
    sys.exit(0)

veri = tempfile.mkdtemp(prefix="raf_kanca_")
m = ortak.modeller()
k = S.Kurulum("raf_43", m, veri)
ayar = dict(k.ayar, kod="k1", ozellikler={"bos_raf": {"acik": True, "sure_sn": 20}})
cv2.imwrite(os.path.join(veri, "ayar", "_referans_k1.jpg"), k.im)
bos = k.hedefler(2)
al = next(i for i in k.hedefler(3, en_az_adet=2) if i not in bos)
kisi_goz = next(i for i in range(len(k.gozler)) if i not in bos and i != al)
gid = [g["kimlik"] for g in k.gozler]


def kare(t):
    im = k.im
    if t >= 30:
        for i in bos:
            im = S.bosalt(im, k.bos, k.px(k.gozler[i]["kutu"]))
    if t >= 58:
        n = k.gozler[al]["adet"]
        im = S.bosalt(im, k.bos, k.px(k.gozler[al]["kutu"]), oran_sol=(n - 1) / n)
    return im


def kisi_kutu(i):
    x1, y1, x2, y2 = k.px(k.gozler[i]["kutu"])
    return [x1 - 10, y1 - 30, x2 + 10, y2 + 60]


st_urun, st_an = {}, {}
bas_zaman = dt.datetime(2026, 11, 15, 10, 0, 0)
baslayan, biten, kayitlar, isaretler, jsonlar = [], [], [], [], []
rng = np.random.default_rng(3)
for t in [float(x) for x in range(0, 122, 2)]:
    fr = S.gurultu(kare(t), rng)
    kisiler = [{"iz": 1, "b": kisi_kutu(kisi_goz)}] if 10 <= t <= 20 else []
    if 10 <= t <= 20:
        fr = S.kisi_ciz(fr, kisi_kutu(kisi_goz))
    metin, durum = raf.analiz(st_urun, fr, ayar, t, veri)
    jsonlar.append((t, json.loads(metin)))
    musteri = {"uzanma_biten": [{"bolge": "b1", "goz": gid[al], "bas": 55.0, "son": 58.0}] if t == 58.0 else [],
               "kisiler": kisiler}
    baglam = {"kod": "k1", "bas_zaman": bas_zaman, "boyut": (k.W, k.H), "bolgeler": [], "ayar": ayar, "kisiler": kisiler}
    r = raf.analiz_sonucu(st_an, t, jsonlar[-1][1]["gozler"], jsonlar[-1][1], musteri, baglam)
    baslayan += r["baslayan"]
    biten += r["biten"]
    kayitlar += r["kayitlar"]
    isaretler += r["isaretler"]

ilk = jsonlar[0][1]
denetle("Raf JSON: sira, gozler (4.3 alanları), referans kayitli", ilk["sira"] == 1 and ilk["referans"] == "kayitli"
        and set(ilk["gozler"][0]) == {"bolge", "goz", "durum", "doluluk", "adet", "urun", "gorulen", "benzerlik",
                                        "etiket", "fiyat"})
denetle("kontrol yalnızca 10 sn'de bir (sira artışı)", jsonlar[-1][1]["sira"] <= 14)
kap = [t for t, j in jsonlar if any(g["goz"] == gid[kisi_goz] and g["durum"] == "kapali" for g in j["gozler"])]
denetle(f"kişi önündeyken göz kapali ({kap[:3]}...)", kap and min(kap) <= 22 and max(kap) <= 30)
bos_ol = [o for o in baslayan if o["kural"] == "bos_raf"]
for i in bos + [al, kisi_goz]:
    print("   ", gid[i], [(t, g["durum"], g["doluluk"]) for t, j in jsonlar[::5] for g in j["gozler"] if g["goz"] == gid[i]])
denetle(f"iki bos_raf olayı ({[o['goz'] for o in bos_ol]})", sorted(o["goz"] for o in bos_ol) == sorted(gid[i] for i in bos))
alanlar = {"kimlik", "zaman", "kural", "kural_ad", "kategori", "duzey", "onem", "olasilik", "puan", "ciddi", "sure_sn",
           "x", "y", "aciklama", "bitti", "bolge", "bolge_ad", "goz", "gorev"}
denetle("olay alanları (4.1 + iskelet)", bos_ol and alanlar <= set(bos_ol[0]) and bos_ol[0]["zaman"].startswith("2026-11-15T10:00:")
        and bos_ol[0]["kategori"] == "raf" and bos_ol[0]["gorev"] is True)
raf_k = [x for x in kayitlar if x.get("tur") == "raf"]
denetle(f"raf kayıtları ({len(raf_k)}), tur/zaman/doluluk/uyum/gozler", raf_k and all(
    {"tur", "zaman", "doluluk", "uyum", "gozler", "referans"} <= set(x) for x in raf_k))
denetle("en geç 60 sn'de bir raf kaydı", max(np.diff([0.0] + [float(x["zaman"][-2:]) + 60 * float(x["zaman"][-5:-3])
                                                             for x in raf_k])) <= 62)
denetle(f"alma doğrulandı ({isaretler})", any(i["eylem"] == "aldi" and i["goz"] == gid[al] for i in isaretler))
kapanan = raf.bitir(st_an)
denetle("bitir açık olayları kapatır", len(kapanan) >= 2 and all(o["bitti"] for o in kapanan))
r = gorev.calistir("bilinmeyen", {}, veri)
denetle("gorev.calistir(ad, girdi, veri) kanca biçimi: hata sözlüğü", "hata" in r)

gec = sum(1 for _, k2 in sonuc if k2)
print(f"\n{gec}/{len(sonuc)} geçti")
sys.exit(0 if gec == len(sonuc) else 1)
