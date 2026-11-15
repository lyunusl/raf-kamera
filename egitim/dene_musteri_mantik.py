"""Müşteri analizinin mantığı (raf_motor.musteri, olcu) yapay izlerle: model ve video gerekmez.

  python egitim/dene_musteri_mantik.py

Kişiler elle çizilmiş kutulardır (ve gerekiyorsa elle verilmiş iskelet noktaları). Denetlenenler: geçen/duran sayıları,
bekleme süresi, uzanma (bilek rafta ve kol gövdeden ayrık; sarkan kol sayılmaz), gövde yönü ve ilgi süresi, giriş çizgisi
(içeri/dışarı), kasa kuyruğu, demografinin iz başına bir kez sayılması, etkileşim kayıtlarında iz/yaş/cinsiyet olmaması,
kapalı özelliğin anahtarının ölçüme yazılmaması, ısı haritası.
Bu sınama yalnızca mantığı doğrular; özelliklerin gerçek görüntüdeki durumu için dene_musteri_video.py'ye bakın.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "motor"))

import numpy as np  # noqa: E402

from raf_motor import olcu  # noqa: E402
from raf_motor.musteri import Musteri  # noqa: E402

W, H = 1280, 720
BAS = dt.datetime(2026, 11, 15, 10, 0, 0)
sonuc: list[tuple[str, bool]] = []


def denetle(ad, kosul, ek=""):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad + (f" ({ek})" if ek else ""), flush=True)


def ayar(bolgeler, **oz):
    return {"bolgeler": bolgeler, "ozellikler": oz}


def kisi(iz, cx, ayak_y, boy=300, k=None, oz=None):
    return {"iz": iz, "b": [cx - boy * 0.2, ayak_y - boy, cx + boy * 0.2, ayak_y], "durum": "izleniyor", "k": k, "oz": oz}


def iskelet(cx, ayak_y, boy=300, sag_bilek=None, sol_bilek=None, kameraya_donuk=False, yuz=False):
    """Basit insan: omuzlar boyun %20'sinde, kalçalar %50'sinde. Sırtı kameraya dönükse sol omuz görüntünün solundadır."""
    ust = ayak_y - boy
    k = [[0.0, 0.0, 0.0] for _ in range(17)]
    yon = -1 if kameraya_donuk else 1  # sol omuz (5) x'i
    k[5] = [cx + yon * -0.15 * boy, ust + 0.2 * boy, 0.9]
    k[6] = [cx + yon * 0.15 * boy, ust + 0.2 * boy, 0.9]
    k[5][0], k[6][0] = (cx - 0.15 * boy, cx + 0.15 * boy) if not kameraya_donuk else (cx + 0.15 * boy, cx - 0.15 * boy)
    k[11] = [k[5][0] * 0.7 + cx * 0.3, ust + 0.5 * boy, 0.9]
    k[12] = [k[6][0] * 0.7 + cx * 0.3, ust + 0.5 * boy, 0.9]
    k[9] = list(sol_bilek) + [0.9] if sol_bilek else [k[5][0], ust + 0.52 * boy, 0.9]   # sarkan kol
    k[10] = list(sag_bilek) + [0.9] if sag_bilek else [k[6][0], ust + 0.52 * boy, 0.9]
    if yuz:
        k[0] = [cx, ust + 0.08 * boy, 0.9]
        k[1] = [cx - 0.03 * boy, ust + 0.06 * boy, 0.9]
        k[2] = [cx + 0.03 * boy, ust + 0.06 * boy, 0.9]
    return k


def kos(m: Musteri, adimlar, t0=0.0, aralik=1 / 3):
    """adimlar: her analiz karesi için kişi listesi. Dönüş: bütün etkileşimler, son adım sonucu."""
    etk, t, son = [], t0, None
    for kisiler in adimlar:
        son = m.adim(t, aralik, kisiler)
        etk += son["etkilesim"]
        t += aralik
    return etk, son, t


# ------------------------------------------------------------------------------------------------ geçen, durma, bekleme
print("Geçen, durma, bekleme")
koridor = {"kimlik": "k1", "ad": "Koridor", "tur": "koridor", "poly": [[0.0, 0.6], [1.0, 0.6], [1.0, 1.0], [0.0, 1.0]]}
raf = {"kimlik": "r1", "ad": "Raf", "tur": "raf", "poly": [[0.3, 0.05], [0.7, 0.05], [0.7, 0.4], [0.3, 0.4]]}
a = ayar([koridor, raf])
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
adimlar = []
for i in range(45):  # 15 sn: iz 1 koridordan yürüyerek geçer; iz 2 raf önünde 9 sn durur, sonra gider
    ks = [kisi(1, 50 + i * 60, 650)]   # 0.6 boy/sn: yürüyor
    if i < 3:
        ks.append(kisi(2, 640, 650 - (3 - i) * 60))
    elif i < 30:
        ks.append(kisi(2, 640 + (i % 2) * 2, 380))   # ayak rafın alt kenarına yakın (0.4*720 = 288 → 92 px < 0.35 × 300)
    elif i < 36:
        ks.append(kisi(2, 640 + (i - 30) * 60, 600))
    adimlar.append(ks)
etk, _, t = kos(m, adimlar)
for _ in range(6):  # herkes gitti: ziyaretler kapanır
    son = m.adim(t, 1 / 3, [])
    etk += son["etkilesim"]
    t += 1 / 3
v, izgara = m.olcum()
denetle("geçen = 2 (iki farklı iz)", v["gecen"] == 2, v["gecen"])
denetle("yalnızca rafta bekleyen durdu sayıldı (koridordan yürüyen değil)", v["duran"] == 1 and v["b:r1:duran"] == 1 and v["b:k1:duran"] == 0, v)
denetle("bekleme süresi ~9 sn (raf önü ziyareti)", 8.0 <= v["b:r1:bekleme_sn"] <= 11.0 and v["bekleme_sayi"] >= 1, v["b:r1:bekleme_sn"])
durdu = [e for e in etk if e["eylem"] == "durdu"]
denetle("raf için bir 'durdu' etkileşimi; iz, yaş, cinsiyet alanı yok",
        len(durdu) == 1 and durdu[0]["bolge"] == "r1" and set(durdu[0]) == {"tur", "zaman", "bolge", "goz", "eylem", "sure_sn"}, durdu)
denetle("ısı haritası 32x18, toplam kişi-saniye ≈ görünen süre", izgara["gen"] == 32 and izgara["yuk"] == 18
        and abs(np.sum(izgara["katmanlar"]["yogunluk"]) - (45 + 36) / 3) < 1.5, round(float(np.sum(izgara["katmanlar"]["yogunluk"])), 1))
denetle("durma haritası yalnızca duran kişiden", 5 <= np.sum(izgara["katmanlar"]["durma"]) <= 9.5, round(float(np.sum(izgara["katmanlar"]["durma"])), 1))
denetle("pencere sıfırlandı", m.olcum()[0]["gecen"] == 0)

# ------------------------------------------------------------------------------------------------ uzanma ve ilgi
print("Uzanma ve ilgi")
raf2 = {"kimlik": "r2", "ad": "Raf", "tur": "raf", "poly": [[0.3, 0.05], [0.7, 0.05], [0.7, 0.45], [0.3, 0.45]],
        "gozler": [{"kimlik": "g1", "kutu": [0.55, 0.1, 0.7, 0.3]}]}
a = ayar([raf2], toplu_alma={"acik": True})
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
cx, ay = 640, 560  # ayak rafın 0.45*720=324 alt kenarına 236 px: boy 400 * 0.35 = 140 → değil; bu yüzden boy 700
adimlar = []
for i in range(30):
    if 10 <= i < 14:   # sağ el yukarı-sağa uzanıyor, göz g1'in içinde
        k = iskelet(cx, ay, 700, sag_bilek=(860, 100))
    else:              # kollar sarkık, sırtı kameraya dönük (rafa bakıyor)
        k = iskelet(cx, ay, 700)
    adimlar.append([kisi(7, cx, ay, 700, k)])
etk, son, t = kos(m, adimlar)
gecmis = any(len(g) for g in son["uzanma_gecmis"].values())
for _ in range(6):
    etk += m.adim(t, 1 / 3, [])["etkilesim"]
    t += 1 / 3
v, _ = m.olcum()
uz = [e for e in etk if e["eylem"] == "uzandi"]
denetle("bir uzanma, göz g1 ile; sarkan kol uzanma sayılmadı", len(uz) == 1 and uz[0]["goz"] == "g1" and v["uzanan"] == 1 and v["b:r2:uzanan"] == 1, uz)
denetle("uzanma süresi ~1 sn", 0.6 <= uz[0]["sure_sn"] <= 1.6 if uz else False, uz[0]["sure_sn"] if uz else None)
denetle("sırtı kameraya dönük (rafa dönük) duran kişide ilgi süresi ≈ bekleme", v["b:r2:ilgi_sn"] >= 8.0, v["b:r2:ilgi_sn"])
denetle("toplu alma için uzanma geçmişi tutuldu", gecmis)

m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
adimlar = [[kisi(8, cx, ay, 700, iskelet(cx, ay, 700, kameraya_donuk=True, yuz=True))] for _ in range(30)]
kos(m, adimlar)
v, _ = m.olcum()
denetle("kameraya (raftan öteye) dönük duran kişide ilgi yok", v["b:r2:ilgi_sn"] == 0 and v["b:r2:duran"] == 1, v["b:r2:ilgi_sn"])
denetle("gövde yönü: sırtı dönük → yukarı, yüzü dönük → aşağı",
        olcu.govde_yonu(iskelet(cx, ay, 700), [0, 0, 0, 700])[1] < -0.9
        and olcu.govde_yonu(iskelet(cx, ay, 700, kameraya_donuk=True, yuz=True), [0, 0, 0, 700])[1] > 0.9)

# ------------------------------------------------------------------------------------------------ giriş
print("Giriş-çıkış sayımı")
giris = {"kimlik": "g", "ad": "Kapı", "tur": "giris", "cizgi": [[0.4, 0.5], [0.6, 0.5]], "ic": [0.5, 0.8]}
a = ayar([giris])
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
adimlar = []
for i in range(20):
    adimlar.append([kisi(1, 640, 250 + i * 25, 200),      # yukarıdan aşağı: içeri
                    kisi(2, 600, 650 - i * 25, 200),      # aşağıdan yukarı: dışarı
                    kisi(3, 100, 250 + i * 25, 200)])     # çizginin dışından geçen: sayılmaz
kos(m, adimlar)
v, _ = m.olcum()
denetle("giren 1, çıkan 1 (çizgi parçasının dışından geçen sayılmadı)", v["giren"] == 1 and v["cikan"] == 1, (v["giren"], v["cikan"]))

# ------------------------------------------------------------------------------------------------ kasa kuyruğu
print("Kasa kuyruğu")
kasa = {"kimlik": "c1", "ad": "Kasa", "tur": "kasa", "poly": [[0.0, 0.3], [1.0, 0.3], [1.0, 1.0], [0.0, 1.0]], "esik": 3}
a = ayar([kasa])
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
adimlar = [[kisi(j, 200 + j * 150, 600) for j in range(1, 5)] + [kisi(9, 50 + i * 60, 400)] for i in range(18)]
_, son, _ = kos(m, adimlar)
v, _ = m.olcum()
denetle("kuyrukta 4 kişi (bölgeden yürüyerek geçen sayılmaz)", son["kuyruk"]["c1"] == 4 and v["kuyruk_en_cok"] == 4, son["kuyruk"])

# ------------------------------------------------------------------------------------------------ demografi
print("Demografi")
a = ayar([raf], demografi={"acik": True})
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
oz_k = {"n": 10, "kadin": 0.9, "yas": {"genc": 0.05, "yetiskin": 0.9, "yasli": 0.05}}
oz_e = {"n": 2, "kadin": 0.1, "yas": {"genc": 0.05, "yetiskin": 0.9, "yasli": 0.05}}
oz_kararsiz = {"n": 10, "kadin": 0.55, "yas": {"genc": 0.3, "yetiskin": 0.4, "yasli": 0.3}}
adimlar = [[kisi(1, 640, 380, oz=oz_k), kisi(2, 300, 650, oz=oz_e), kisi(3, 900, 650, oz=oz_kararsiz)] for _ in range(12)]
kos(m, adimlar)
v1, _ = m.olcum()
_, son, _ = kos(m, [[]] * 4, 4.0)
v2, _ = m.olcum()
toplam = {a_: v1[a_] + v2[a_] for a_ in ("kadin", "erkek", "yas_yetiskin", "yas_genc", "yas_yasli")}
denetle("kadın 1 (kesinleşince sayıldı); 2 örnekli erkek iz sayılmadı (en az 3 örnek)", toplam["kadin"] == 1 and toplam["erkek"] == 0, toplam)
denetle("kararsız iz cinsiyette sayılmaz; yaş yalnızca eşiği geçenlerde", toplam["yas_yetiskin"] == 1 and toplam["yas_genc"] == 0, toplam)
denetle("bölge bazında demografi (raf önündeki kadın)", v1["b:r1:kadin"] + v2["b:r1:kadin"] == 1)
a = ayar([raf])
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
kos(m, adimlar)
v, _ = m.olcum()
denetle("demografi kapalıyken anahtarları ölçüme yazılmaz", "kadin" not in v and "b:r1:kadin" not in v)
denetle("raf tarafı alma bildirmeden alan/birakan yazılmaz", "alan" not in v)
e = m.raf_isareti("aldi", "r1", "g1", 3.0, 1.2)
v, _ = m.olcum()
denetle("raf tarafı alma bildirince alan sayılır ve etkileşim kaydı döner", v["alan"] == 1 and v["b:r1:alan"] == 1 and e["eylem"] == "aldi")

# ------------------------------------------------------------------------------------------------ gerçek kliplerden gelen hatalar
print("Örnek mağaza kliplerinde bulunan hatalar (2026-11-15)")
# toplu: arkadan bakan kamerada kişi kutuları tek tek alıyor; kol kısa görünür, bilek omuz hizasında. Uzanmalar arasında
# 0,5-0,7 sn bilek raf dışındadır: her biri ayrı uzanma olmalı (eskiden boşluk 1 sn idi ve kapanış kontrolü yeni
# gözlemden sonra yapıldığı için hepsi tek uzanmada birleşiyordu).
raf3 = {"kimlik": "r3", "ad": "Koli", "tur": "raf", "poly": [[0.3, 0.35], [0.72, 0.35], [0.72, 0.545], [0.3, 0.545]]}
a = ayar([raf3], uzanma={"acik": True, "en_az_kare": 2})
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
cx, ay, boy = 620, 715, 470  # kutu 0.34-0.99 (gerçek klipteki gibi), omuz y ≈ 0.48
adimlar = []
for i in range(60):  # 10 sn, 6 analiz karesi/sn; her 1,0 sn'de 0,5 sn bilek rafta (omuz hizasında, gövdeye yakın)
    rafta = (i % 6) < 3
    bilek = (700, 330) if rafta else (700, 470)   # rafta: y 0.46 (omuz hizası); değil: kutuyu tutuyor, y 0.65
    adimlar.append([kisi(1, cx, ay, boy, iskelet(cx, ay, boy, sag_bilek=bilek))])
etk, _, t = kos(m, adimlar, aralik=1 / 6)
uz = [e for e in etk if e["eylem"] == "uzandi"]
denetle("art arda 10 alış ~10 ayrı uzanma (birleşmez)", 8 <= len(uz) <= 10, len(uz))
denetle("omuz hizasındaki kısa görünen kol uzanma sayılır",
        bool(olcu.bilek_uzaniyor(iskelet(cx, ay, boy, sag_bilek=(700, 330)), [cx - 94, ay - boy, cx + 94, ay])))
denetle("kutuyu önünde tutan kol (bilek bel hizasında) uzanma değil",
        not olcu.bilek_uzaniyor(iskelet(cx, ay, boy, sag_bilek=(670, 470)), [cx - 94, ay - boy, cx + 94, ay]))
# koridor: kameradan uzaklaşarak yürüyen kişinin ayağı görüntüde az kayar, boyu küçülür: duruyor sayılmamalı
kor = {"kimlik": "k9", "ad": "Koridor", "tur": "koridor", "poly": [[0.0, 0.2], [1.0, 0.2], [1.0, 1.0], [0.0, 1.0]]}
a = ayar([kor], bekleme={"acik": True, "esik_sn": 2})
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
adimlar = [[kisi(1, 640, 700 - i * 6, 380 * (0.93 ** i))] for i in range(30)]   # 10 sn: boy 380 → ~46 px, ayak 174 px
kos(m, adimlar)
v, _ = m.olcum()
denetle("kameradan uzaklaşarak yürüyen kişi duran sayılmaz (boy değişimi hız sayılır)", v["duran"] == 0, v["duran"])
m = Musteri(olcu.bolgeler(a, W, H), a, W, H, BAS)
kos(m, [[kisi(1, 640 + (i % 2) * 2, 600, 300 + (i % 3) * 4)] for i in range(30)])
v, _ = m.olcum()
denetle("yerinde duran kişi (boyu ±%2 oynuyor) duran sayılır", v["duran"] == 1, v["duran"])

kalan = [ad for ad, ok in sonuc if not ok]
print(f"\n{len(sonuc) - len(kalan)}/{len(sonuc)} denetim geçti" + (f" · kalanlar: {kalan}" if kalan else ""))
sys.exit(1 if kalan else 0)
