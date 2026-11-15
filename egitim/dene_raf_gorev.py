"""Tek seferlik işlerin çalıştırıcısı (gorev.py): ortam değişkenleri, atomik çıktı, hata çıktısı, üç işin çıktı biçimi.

  python egitim/dene_raf_gorev.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import cv2

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raf"))

import ortak  # noqa: E402
from raf_motor import gorev  # noqa: E402

sonuc = []


def denetle(ad, kosul):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad, flush=True)


if not ortak.gorseller_var():
    print("test görselleri yok: RAF_TEST_GORSELLERI")
    sys.exit(0)

m = ortak.modeller()
d = tempfile.mkdtemp(prefix="raf_gorev_")
kare = os.path.join(d, "kare.jpg")
cv2.imwrite(kare, ortak.gorsel("raf_13"))
girdi, cikti = os.path.join(d, "girdi.json"), os.path.join(d, "cikti.json")

# gozler (ortam değişkenleriyle, Studio'daki gibi)
with open(girdi, "w", encoding="utf-8") as f:
    json.dump({"kare": kare, "bolgeler": [{"kimlik": "b1", "poly": [[0.2, 0.1], [0.82, 0.1], [0.82, 0.7], [0.2, 0.7]]}]}, f)
os.environ.update({gorev.ORTAM_GOREV: "gozler", gorev.ORTAM_GIRDI: girdi, gorev.ORTAM_CIKTI: cikti})
r = gorev.ortamdan(m, d)
with open(cikti, encoding="utf-8") as f:
    yaz = json.load(f)
denetle("gozler: çıktı yazıldı, .tmp kalmadı", yaz.get("gozler") and not os.path.exists(cikti + ".tmp"))
g = yaz["gozler"][0]
denetle("gozler: alanlar bolge/kutu/skor/etiket(/adet)", {"bolge", "kutu", "skor", "etiket", "adet"} <= set(g)
        and g["bolge"] == "b1" and len(g["kutu"]) == 4 and all(0 <= v <= 1 for v in g["kutu"]))
denetle(f"gozler: {len(yaz['gozler'])} göz önerildi, {sum(1 for x in yaz['gozler'] if x['etiket'])} etiketli",
        len(yaz["gozler"]) >= 10)

# etiketler
cv2.imwrite(kare, ortak.gorsel("etiket_47"))
H, W = 813, 1280
with open(girdi, "w", encoding="utf-8") as f:
    json.dump({"kare": kare, "kutular": [[115 / W, 645 / H, 262 / W, 745 / H], [25 / W, 645 / H, 135 / W, 735 / H]]}, f)
r = gorev.calistir_dosya("etiketler", girdi, cikti, m, d)
denetle("etiketler: 12.79 ve 6.40", [e["fiyat"] for e in r.get("etiketler", [])] == [12.79, 6.4]
        and {"kutu", "metin", "fiyat"} <= set(r["etiketler"][0]))

# urun_tani (katalog: raf_13'ten iki ürün)
im = ortak.gorsel("raf_13")
os.makedirs(os.path.join(d, "urunler", "gorsel"))
cv2.imwrite(os.path.join(d, "urunler", "gorsel", "nerds.jpg"), im[100:225, 260:350])
cv2.imwrite(os.path.join(d, "urunler", "gorsel", "haribo.jpg"), im[100:210, 860:965])
with open(os.path.join(d, "urunler", "urunler.json"), "w", encoding="utf-8") as f:
    json.dump([{"kimlik": "u1", "ad": "Nerds", "gorseller": ["nerds.jpg"]},
               {"kimlik": "u2", "ad": "Haribo", "gorseller": ["haribo.jpg"]}], f)
cv2.imwrite(kare, im)
Wi, Hi = im.shape[1], im.shape[0]
with open(girdi, "w", encoding="utf-8") as f:
    json.dump({"kare": kare, "kutular": [[255 / Wi, 95 / Hi, 355 / Wi, 230 / Hi], [970 / Wi, 95 / Hi, 1092 / Wi, 270 / Hi]]}, f)
r = gorev.calistir_dosya("urun_tani", girdi, cikti, m, d)
u = r.get("urunler", [])
denetle(f"urun_tani: Nerds -> u1, katalogda olmayan Haribo Twin Snakes -> null ({u})",
        len(u) == 2 and u[0]["urun"] == "u1" and u[1]["urun"] is None)
denetle("urun_tani: önbellek dosyası yazıldı", os.path.isfile(os.path.join(d, "urunler", "gomme-onbellek.npz")))

# hata
r = gorev.calistir_dosya("gozler", os.path.join(d, "yok.json"), cikti, m, d)
with open(cikti, encoding="utf-8") as f:
    denetle("hata: {\"hata\": ...} yazılır", "hata" in json.load(f) and "hata" in r)
r = gorev.calistir_dosya("bilinmeyen", girdi, cikti, m, d)
denetle("bilinmeyen iş: hata", "hata" in r)
for k in (gorev.ORTAM_GOREV, gorev.ORTAM_GIRDI, gorev.ORTAM_CIKTI):
    os.environ.pop(k)
denetle("ortam yoksa iş koşmaz", gorev.ortamdan(m, d) is None)

gec = sum(1 for _, k in sonuc if k)
print(f"\n{gec}/{len(sonuc)} geçti")
sys.exit(0 if gec == len(sonuc) else 1)
