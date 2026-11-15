"""Operasyon uyarılarının mantığı (raf_motor.operasyon, olay) yapay karelerle: model ve video gerekmez.

  python egitim/dene_operasyon_mantik.py

Denetlenenler: kasa kuyruğu olayının sure_sn sonra başlaması, aynı kimlikle sürmesi, eşiğin altına inince kapanması ve
sözleşme 4.1 alanları; toplu alma; tıkalı koridor (koridora konan durağan kutu; yürüyen kişi ve ışık değişimi uyarı
vermez); dökülme (düz/parlak küçük leke); açık dolap (kapalı referans koşu başında öğrenilir, önünde kişi varken karar
verilmez; kayıtlı referans karesi kullanılır). Bu sınama yalnızca mantığı doğrular.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from collections import deque
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "motor"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from raf_motor import olcu  # noqa: E402
from raf_motor.operasyon import Operasyon  # noqa: E402

W, H = 640, 360
BAS = dt.datetime(2026, 11, 15, 10, 0, 0)
sonuc: list[tuple[str, bool]] = []
ALANLAR = {"kimlik", "bitti", "kural", "kural_ad", "kategori", "duzey", "onem", "olasilik", "puan", "ciddi", "gorev", "bolge",
           "bolge_ad", "zaman", "sure_sn", "x", "y", "aciklama"}


def denetle(ad, kosul, ek=""):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad + (f" ({ek})" if ek else ""), flush=True)


def zemin(seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    z = np.full((H, W, 3), 120, np.uint8)
    for _ in range(400):  # desenli zemin (karo)
        x, y = rng.integers(0, W - 8), rng.integers(0, H - 8)
        z[y:y + 6, x:x + 6] = rng.integers(60, 200, 3)
    return z


def kos(op: Operasyon, kareler, kisiler_fn, musteri_fn, t0=0.0, aralik=0.5):
    olaylar = {"baslayan": [], "suren": [], "biten": []}
    t = t0
    for i, fr in enumerate(kareler):
        o = op.adim(t, fr, kisiler_fn(i), musteri_fn(i, t))
        for a in olaylar:
            olaylar[a] += o[a]
        t += aralik
    return olaylar, t


# ------------------------------------------------------------------------------------------------ kasa kuyruğu
print("Kasa kuyruğu")
ayar = {"bolgeler": [{"kimlik": "c1", "ad": "Kasa 1", "tur": "kasa", "poly": [[0, 0], [1, 0], [1, 1], [0, 1]], "esik": 4}],
        "ozellikler": {"kasa_kuyrugu": {"sure_sn": 10}}}
op = Operasyon(olcu.bolgeler(ayar, W, H), ayar, W, H, BAS)
fr = zemin()
kuyruk = lambda i, t: {"kuyruk": {"c1": 5 if 4 <= i < 60 else 2}}  # noqa: E731
ol, t = kos(op, [fr] * 100, lambda i: [], kuyruk)
b = ol["baslayan"]
denetle("olay eşik 10 sn sürünce bir kez başladı", len(b) == 1 and abs(b[0]["sure_sn"] - 10.0) < 0.6, [x["sure_sn"] for x in b])
denetle("sözleşme 4.1 alanları + değer/beklenen, görev açar", b and ALANLAR <= set(b[0]) and b[0]["deger"] == 5 and b[0]["beklenen"] == 4
        and b[0]["gorev"] is True and b[0]["bolge"] == "c1" and b[0]["bolge_ad"] == "Kasa 1" and b[0]["kural"] == "kasa_kuyrugu")
denetle("süren kayıtlar aynı kimlikle", ol["suren"] and all(x["kimlik"] == b[0]["kimlik"] for x in ol["suren"]))
denetle("kuyruk eşiğin altına inince olay kapandı (bitti, aynı kimlik, süre = koşulun sürdüğü 27.5 sn)", len(ol["biten"]) == 1 and ol["biten"][0]["bitti"]
        and ol["biten"][0]["kimlik"] == b[0]["kimlik"] and 27.0 <= ol["biten"][0]["sure_sn"] <= 28.0, ol["biten"][0]["sure_sn"] if ol["biten"] else None)

# ------------------------------------------------------------------------------------------------ toplu alma
print("Toplu alma")
ayar = {"bolgeler": [{"kimlik": "r1", "ad": "Raf", "tur": "raf", "poly": [[0, 0], [1, 0], [1, 0.5], [0, 0.5]]}],
        "ozellikler": {"toplu_alma": {"acik": True, "uzanma_sayi": 4, "pencere_sn": 30}}}
op = Operasyon(olcu.bolgeler(ayar, W, H), ayar, W, H, BAS)
gecmis = {5: deque([(1.0, "r1"), (4.0, "r1"), (8.0, "r1")]), 6: deque([(1.0, "r1"), (2.0, "r1")])}
o1 = op.adim(9.0, fr, [], {"uzanma_gecmis": gecmis})
gecmis[5].append((9.5, "r1"))
o2 = op.adim(10.0, fr, [], {"uzanma_gecmis": gecmis})
denetle("3 uzanmada uyarı yok, 4.'de başladı; kayıtta iz numarası yok", not o1["baslayan"] and len(o2["baslayan"]) == 1
        and o2["baslayan"][0]["deger"] == 4 and "iz" not in o2["baslayan"][0] and o2["baslayan"][0]["gorev"] is False)

# ------------------------------------------------------------------------------------------------ tıkalı koridor, dökülme
print("Tıkalı koridor ve dökülme")
ayar = {"bolgeler": [{"kimlik": "k1", "ad": "Koridor", "tur": "koridor", "poly": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.95], [0.1, 0.95]]}],
        "ozellikler": {"tikali_koridor": {"sure_sn": 20}, "dokulme": {"acik": True, "sure_sn": 20}}}
z = zemin()
kareler, kisiler = [], []
for i in range(120):  # 1 sn aralık
    k = z.copy()
    ks = []
    x = (i * 25) % 500 + 60  # koridorda yürüyen kişi (kutusu maskelenir)
    cv2.rectangle(k, (x, 120), (x + 40, 300), (30, 40, 200), -1)
    ks.append({"iz": 1, "b": [x, 120, x + 40, 300], "durum": "izleniyor"})
    if 40 <= i < 70:
        k = cv2.convertScaleAbs(k, alpha=1.25, beta=0)  # ışık açıldı (kazanç değişimi)
    if i >= 70:
        cv2.rectangle(k, (150, 150), (330, 300), (20, 90, 150), -1)   # koli yığını (desenli değil ama büyük)
        cv2.rectangle(k, (160, 160), (320, 290), (40, 110, 170), 3)
    kareler.append(k)
    kisiler.append(ks)
op = Operasyon(olcu.bolgeler(ayar, W, H), ayar, W, H, BAS)
ol, t = kos(op, kareler, lambda i: kisiler[i], lambda i, t: {}, aralik=1.0)
tik = [x for x in ol["baslayan"] if x["kural"] == "tikali_koridor"]
denetle("yürüyen kişi ve ışık değişimi tıkalı koridor uyarısı vermedi (0-70 sn)", all(x["zaman"] >= "2026-11-15T10:01:10" for x in tik), [x["zaman"] for x in tik])
denetle("koridora konan engel ~20 sn sonra tıkalı koridor uyarısı verdi", len(tik) == 1 and tik[0]["zaman"] <= "2026-11-15T10:01:15", [x["zaman"] for x in tik])

z = zemin(2)
kareler = []
for i in range(80):
    k = z.copy()
    if i >= 30:
        cv2.ellipse(k, (420, 250), (22, 12), 0, 0, 360, (215, 215, 215), -1)  # parlak, düz küçük leke
    kareler.append(k)
op = Operasyon(olcu.bolgeler(ayar, W, H), ayar, W, H, BAS)
ol, _ = kos(op, kareler, lambda i: [], lambda i, t: {}, aralik=1.0)
dok = [x for x in ol["baslayan"] if x["kural"] == "dokulme"]
tik = [x for x in ol["baslayan"] if x["kural"] == "tikali_koridor"]
denetle("küçük parlak leke dökülme uyarısı verdi, tıkalı koridor vermedi", len(dok) == 1 and not tik, ([x["zaman"] for x in dok], len(tik)))

# ------------------------------------------------------------------------------------------------ dolap
print("Açık dolap")
ayar = {"bolgeler": [{"kimlik": "d1", "ad": "Süt dolabı", "tur": "dolap", "poly": [[0.6, 0.1], [0.95, 0.1], [0.95, 0.8], [0.6, 0.8]]}],
        "ozellikler": {"dolap_acik": {"sure_sn": 15}}}
z = zemin(3)
cv2.rectangle(z, (390, 40), (600, 280), (200, 200, 190), -1)   # kapalı kapak
for j in range(4):
    cv2.line(z, (395, 60 + 55 * j), (595, 60 + 55 * j), (90, 90, 90), 3)
acik = z.copy()
cv2.rectangle(acik, (390, 40), (600, 280), (40, 50, 60), -1)    # kapak açık: içi karanlık
for j in range(4):
    cv2.rectangle(acik, (400, 50 + 55 * j), (590, 90 + 55 * j), (60 + 30 * j, 150, 220), -1)
kareler, kisiler = [], []
for i in range(90):
    kareler.append(acik if 20 <= i < 60 else z)
    kisiler.append([{"iz": 3, "b": [380, 60, 520, 330], "durum": "izleniyor"}] if 20 <= i < 26 else [])  # kişi açtı, gitti
op = Operasyon(olcu.bolgeler(ayar, W, H), ayar, W, H, BAS)
ol, _ = kos(op, kareler, lambda i: kisiler[i], lambda i, t: {}, aralik=1.0)
d = [x for x in ol["baslayan"] if x["kural"] == "dolap_acik"]
db = [x for x in ol["biten"] if x["kural"] == "dolap_acik"]
denetle("referans koşu başında öğrenildi (geçici)", op.dolap_referansi() == {"d1": "gecici"})
denetle("kapak açık kalınca bir uyarı, kapanınca kapandı", len(d) == 1 and len(db) == 1, (len(d), len(db)))
denetle("önünde kişi varken (20-26 sn) uyarı başlamadı", d and d[0]["zaman"] >= "2026-11-15T10:00:20", d[0]["zaman"] if d else None)
with tempfile.TemporaryDirectory() as g:
    yol = str(Path(g) / "_referans_x.jpg")
    cv2.imwrite(yol, z)
    op = Operasyon(olcu.bolgeler(ayar, W, H), ayar, W, H, BAS, yol)
    ol, _ = kos(op, [acik] * 30, lambda i: [], lambda i, t: {}, aralik=1.0)
    denetle("kayıtlı referans karesiyle baştan açık olan kapak da yakalanır", op.dolap_referansi() == {"d1": "kayitli"}
            and len([x for x in ol["baslayan"] if x["kural"] == "dolap_acik"]) == 1)

# ------------------------------------------------------------------------------------------------ örnek kliplerden (2026-11-15)
print("Kısa klipte dökülme ve palet (kayıtlı koridor referansı)")
# Koridor referansı koşu başında 8 kişisiz örnekle öğrenilirse 10 sn'lik klipte hiçbir şey görülmez. Kayıtlı referans karesi
# (ve o karedeki kişi kutuları: altı bilinmiyor sayılır, kişisiz görülünce öğrenilir) baştan kullanılır. Döken kişi 15 sn
# beklenmeden (kisi_sn) ayrıldıktan kısa süre sonra leke görülür; parça parça görünen palet dökülme sayılmaz.
ayar = {"bolgeler": [{"kimlik": "k1", "ad": "Koridor", "tur": "koridor", "poly": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.95], [0.1, 0.95]]}],
        "ozellikler": {"tikali_koridor": {"sure_sn": 2}, "dokulme": {"acik": True, "sure_sn": 2, "kisi_sn": 2}}}
z = zemin(4)
ref = z.copy()
cv2.rectangle(ref, (100, 200), (140, 320), (30, 40, 200), -1)  # referans karesinde bir kişi duruyor
kareler, kisiler = [], []
for i in range(24):  # 0,5 sn aralıkla 12 sn
    k = z.copy()
    ks = []
    if i < 8:   # kişi lekenin yanında, sonra çıkar
        cv2.rectangle(k, (380, 180), (420, 300), (30, 40, 200), -1)
        ks.append({"iz": 1, "b": [380, 180, 420, 300], "durum": "izleniyor"})
    if i >= 2:
        cv2.ellipse(k, (440, 270), (24, 12), 0, 0, 360, (30, 60, 90), -1)   # koyu düz leke (dökülen içecek)
    if i >= 12:  # palet: birkaç ayrı koli yüzü, aralarında şerit
        for x in (180, 215, 250):
            cv2.rectangle(k, (x, 120), (x + 30, 200), (60, 130, 190), -1)
    kareler.append(k)
    kisiler.append(ks)
with tempfile.TemporaryDirectory() as g:
    yol = str(Path(g) / "_referans_k.jpg")
    cv2.imwrite(yol, ref)
    (Path(g) / "_referans_k.json").write_text('{"kisiler": [[%f, %f, %f, %f]]}' % (100 / W, 200 / H, 140 / W, 320 / H), encoding="utf-8")
    op = Operasyon(olcu.bolgeler(ayar, W, H), ayar, W, H, BAS, yol)
    ol, _ = kos(op, kareler, lambda i: kisiler[i], lambda i, t: {}, aralik=0.5)
dok = [x for x in ol["baslayan"] if x["kural"] == "dokulme"]
tik = [x for x in ol["baslayan"] if x["kural"] == "tikali_koridor"]
denetle("kayıtlı referansla koridor ilk karede hazır", op.koridorlar[0].kaynak == "kayitli")
denetle("referanstaki kişinin yeri sahte leke/engel vermedi; tek dökülme uyarısı (kişi gittikten ~3-4 sn sonra)",
        len(dok) == 1 and "10:00:03" <= dok[0]["zaman"][11:] <= "10:00:08", [x["zaman"] for x in dok])
denetle("parça parça palet ikinci bir dökülme sayılmadı", len(dok) == 1)

kalan = [ad for ad, ok in sonuc if not ok]
print(f"\n{len(sonuc) - len(kalan)}/{len(sonuc)} denetim geçti" + (f" · kalanlar: {kalan}" if kalan else ""))
sys.exit(1 if kalan else 0)
