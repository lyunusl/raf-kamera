"""Raf/ürün tarafının saf mantığını model olmadan sınar.

  python egitim/dene_raf_mantik.py

- fiyat ayrıştırma (Türk market biçimleri, üst simge kuruş, beklenen fiyatla seçim, birim/yüzde/tarih ayıklama)
- satırlara ayırma ve komşu yüzleri birleştirme (gozler işi)
- kalıcılık (aday durum, süre, kapali), kapsama, kapalı göz
- RafIzleyici + RafOlaylari, sahte modelle (dedektör kutuları ve gömmeler elle verilir): geçişler, olay aç/kapa,
  yüz sayısı değişimi (alma doğrulaması), kayıt biçimi (sözleşme 4.3), geçici referans, etiket teyidi
"""
import os
import sys
import tempfile

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "motor"))

from raf_motor import raf as R  # noqa: E402
from raf_motor.etiket import fiyat_ayristir, karsilastir  # noqa: E402
from raf_motor.gorev import ayni_urun, komsulari_birlestir, satirlara_ayir  # noqa: E402

sonuc = []


def denetle(ad, kosul):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad, flush=True)


# --- fiyat ayrıştırma -----------------------------------------------------------------------------------------------
print("fiyat ayrıştırma")
ORNEKLER = [
    (["34,90"], None, 34.90), (["34.90"], None, 34.90), (["34,90 TL"], None, 34.90), (["TL 34,90"], None, 34.90),
    (["34 90"], None, 34.90), (["14. 90"], None, 14.90), (["1.234,50 TL"], None, 1234.50), (["1.299 TL"], None, 1299.0),
    (["19.990"], None, 19990.0), (["34,-"], None, 34.0), (["125 TL"], None, 125.0), (["125TL"], None, 125.0),
    (["₺34,90"], None, 34.90), (["t34,90"], None, 34.90), (["34,9O"], None, 34.90), (["3l,50"], None, 31.50),
    (["BEYPAZARI", "KURUSU", "19,90", "14.90"], None, 19.90),
    (["1490"], 14.90, 14.90), (["14 90 TL"], 14.90, 14.90), (["19,90 TL/KG", "14,90"], 14.90, 14.90),
    (["500 G", "12,50"], None, 12.50), (["%20", "49,90"], None, 49.90), (["SKT 12.05.2026", "7,50"], None, 7.50),
    (["ÜLKER ÇİKOLATA"], None, None), (["1490"], None, None), (["2 x 10"], None, None), (["1 L"], None, None),
    (["CENA 1 KG", "23 00"], None, 23.00), (["$27.67"], None, 27.67),
]
for satir, bek, beklenen in ORNEKLER:
    r = fiyat_ayristir(satir, bek)
    denetle(f"{satir} (beklenen {bek}) -> {beklenen}  [okunan {r['fiyat']}]", r["fiyat"] == beklenen)
# en büyük yazı seçilir (birim fiyat küçük yazılır)
r = fiyat_ayristir([{"metin": "19,90 TL/KG", "kutu": [0, 0, 50, 10]}, {"metin": "14,90", "kutu": [0, 20, 80, 60]}])
denetle("büyük yazılı fiyat seçilir: 14,90", r["fiyat"] == 14.90)
# üst simge kuruş ayrı satır: büyük "14" + sağ üstte küçük "90"
r = fiyat_ayristir([{"metin": "14", "kutu": [0, 10, 60, 70]}, {"metin": "90", "kutu": [62, 8, 92, 35]}])
denetle("üst simge kuruş birleşir: 14 + 90 -> 14.90", r["fiyat"] == 14.90)
r = fiyat_ayristir([{"metin": "5.", "kutu": [0, 10, 30, 60]}, {"metin": "99", "kutu": [32, 12, 70, 58]}])
denetle("ayraçtan bölünmüş satırlar: '5.' + '99' -> 5.99", r["fiyat"] == 5.99)
denetle("'8.500' beklenen 8.50 ile uygun", fiyat_ayristir(["8.500"], 8.5)["fiyat"] == 8.5)
denetle("'8.500' beklenensiz binlik (8500)", fiyat_ayristir(["8.500"])["fiyat"] == 8500.0)
denetle("karşılaştır uygun", karsilastir(34.9, 34.9) == "uygun")
denetle("karşılaştır farklı", karsilastir(39.9, 34.9) == "farkli")
denetle("düşük güvende farklı denmez", karsilastir(39.9, 34.9, guven=0.5) == "okunamadi")
denetle("beklenen yoksa uygun", karsilastir(39.9, None) == "uygun")

# --- satırlar ve birleştirme ----------------------------------------------------------------------------------------
print("satırlar")
kut = np.array([[10, 10, 50, 100], [55, 12, 95, 98], [100, 8, 140, 102],      # satır 1
                [12, 150, 52, 240], [58, 152, 98, 238], [150, 148, 190, 242],  # satır 2 (arada boşluk)
                [200, 9, 240, 101]], np.float32)
s = satirlara_ayir(kut)
denetle("iki satır", len(s) == 2)
denetle("satır 1 soldan sağa", s[0] == [0, 1, 2, 6])
denetle("satır 2 soldan sağa", s[1] == [3, 4, 5])
yukseklik_farkli = np.array([[0, 0, 40, 100], [45, 60, 85, 100]], np.float32)  # küçük ürün aynı rafta (alt hizalı)
denetle("kısa ürün aynı satırda", len(satirlara_ayir(yukseklik_farkli)) == 1)
denetle("boş girdi", satirlara_ayir(np.zeros((0, 4), np.float32)) == [])
ayni = {(0, 1): True, (1, 2): False, (2, 6): True}
g = komsulari_birlestir(kut, s[0], lambda i, j: ayni.get((i, j), False))
denetle("komşular birleşir, farklı ürün ve uzak kutu ayrı: [0,1] [2] [6]", g == [[0, 1], [2], [6]])
g = komsulari_birlestir(kut, s[0], lambda i, j: True)
denetle("aynı ürün yan yana: [0,1,2] [6]", g == [[0, 1, 2], [6]])
g = komsulari_birlestir(kut, s[1], lambda i, j: True)
denetle("arada boşluk varsa birleşmez: [3,4] [5]", g == [[3, 4], [5]])
denetle("aynı ürün kuralı: gömme 0.62 + renk 0.9", ayni_urun(0.62, 0.9))
denetle("aynı ürün kuralı: gömme 0.85 + renk 0.65", ayni_urun(0.85, 0.65))
denetle("farklı: gömme 0.58 + renk 0.29", not ayni_urun(0.58, 0.29))

# --- kalıcılık ve yardımcılar -----------------------------------------------------------------------------------------
print("kalıcılık")
k = R.Kalicilik()
denetle("bilinmiyor -> dolu hemen", k.gozle("dolu", 0, 20) == ("bilinmiyor", "dolu"))
denetle("tek bos gözlemi kesinleşmez", k.gozle("bos", 10, 30) is None)
denetle("kapali adayı bozmaz", k.gozle("kapali", 20, 30) is None and k.aday == "bos")
denetle("30 sn dolmadan kesinleşmez", k.gozle("bos", 30, 30) is None)
denetle("30 sn sonra bos kesinleşir", k.gozle("bos", 40, 30) == ("dolu", "bos"))
denetle("tek dolu gözlemi yetmez (geri dönüş)", k.gozle("dolu", 50, 20) is None)
denetle("araya az girerse aday sıfırlanır", k.gozle("az", 60, 60) is None and k.aday == "az")
denetle("dolu yeniden aday", k.gozle("dolu", 70, 20) is None and k.aday_t == 70)
denetle("dolu kesinleşir", k.gozle("dolu", 90, 20) == ("bos", "dolu"))
kap, adet = R.kapsama(np.array([[0, 0, 10, 10], [10, 0, 20, 10], [40, 0, 50, 10], [200, 0, 210, 10]], np.float32), [0, 0, 100, 10])
denetle("kapsama 0.3, adet 3", abs(kap - 0.3) < 1e-6 and adet == 3)
denetle("kapalı: kişi kutusu", R.kapali_mi([0, 0, 100, 100], [{"b": [50, 50, 300, 300], "eller": []}], 0.12))
denetle("kapalı değil: az örtüşme", not R.kapali_mi([0, 0, 100, 100], [{"b": [95, 95, 300, 300], "eller": []}], 0.12))
denetle("kapalı: bilek içeride", R.kapali_mi([0, 0, 100, 100], [{"b": [300, 0, 400, 100], "eller": [(50, 50)]}], 0.12))
kc = R.kisileri_coz([{"b": [0.1, 0.1, 0.2, 0.5], "k": [[0, 0, 0]] * 9 + [[0.15, 0.3, 0.9], [0.5, 0.5, 0.1]] + [[0, 0, 0]] * 6}], 1000, 500)
denetle("kişi 0-1 kutu ölçeklenir, güvenli bilek alınır", kc[0]["b"] == [100, 50, 200, 250] and kc[0]["eller"] == [(150, 150)])


a = R.ayarlari_coz({"raf_araligi_sn": 15, "ozellikler": {"bos_raf": {"acik": True, "sure_sn": 45},
                                                         "az_stok": {"doluluk_esik": 0.4, "sure_sn": 90},
                                                         "yanlis_urun": {"benzerlik_esik": 0.5},
                                                         "fiyat_farkli": {"fark_tl": 0.5, "sure_sn": 120}}})
denetle("katalog ayarları eşlenir", (a["raf_araligi_sn"], a["bos_sure_sn"], a["az_esik"], a["az_sure_sn"],
                                     a["yanlis_bek_esik"], a["fiyat_tolerans"], a["fiyat_farkli_sure_sn"])
        == (15.0, 45.0, 0.4, 90.0, 0.5, 0.5, 120.0))
denetle("fark_tl toleransı", karsilastir(35.3, 34.9, tolerans=0.5) == "uygun" and karsilastir(35.5, 34.9, tolerans=0.5) == "farkli")

# --- izleyici (sahte model) -------------------------------------------------------------------------------------------
print("izleyici (sahte model)")


class SahteModel:
    """Dedektör kutularını ve gömmeleri dışarıdan alır. `kutular`: kare pikselinde; `vek`: kırpıntı ortalamasından."""
    klasor = tempfile.gettempdir()

    def __init__(self):
        self.kutular = np.zeros((0, 4), np.float32)
        self.cagri = 0

    def var_mi(self, ad):
        return True

    def urun_bul(self, im, parca=True):
        self.cagri += 1
        # bölge kırpıntısı (0,0)'dan başlar: kare = 400x200, bölge çerçevesi kutularla aynı (bkz. ayar), ofset çıkarılır
        return self.kutular - np.array([self.ofset[0], self.ofset[1]] * 2, np.float32), np.ones(len(self.kutular))

    def gomme(self, kirp):
        out = []
        import cv2
        for c in kirp:
            v = cv2.resize(c, (4, 4), interpolation=cv2.INTER_AREA).astype(np.float32).ravel() - 100.0
            out.append(v / max(1e-6, np.linalg.norm(v)))
        return np.stack(out)


W, H = 400, 200
ayar = {"bolgeler": [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": [[0, 0], [1, 0], [1, 1], [0, 1]],
                      "gozler": [{"kimlik": "g1", "kutu": [0.0, 0.0, 0.5, 1.0], "adet": 4},
                                 {"kimlik": "g2", "kutu": [0.5, 0.0, 1.0, 1.0], "adet": 4}]}],
        "raf_araligi_sn": 10, "ozellikler": {"bos_raf": {"sure_sn": 20}}}
m = SahteModel()
m.ofset = (0, 0)
dolu_kutular = np.array([[x, 20, x + 45, 180] for x in range(5, 400, 50)], np.float32)  # 8 yüz, göz başına 4


def kare(renk_sol=(40, 80, 160), renk_sag=(160, 80, 40)):
    k = np.zeros((H, W, 3), np.uint8)
    k[:, :200] = renk_sol
    k[:, 200:] = renk_sag
    k[::7, :] = 255  # doku (kenar yoğunluğu)
    return k


ref = kare()
iz = R.RafIzleyici(ayar, m, referans=ref)
ol = R.RafOlaylari(iz)
m.kutular = dolu_kutular
r = iz.guncelle(kare(), 0.0)
denetle("ilk kontrol yapıldı, kayıt var", r["kontrol"] and r["kayit"] is not None)
kay = r["kayit"]
denetle("kayıt alanları (4.3)", set(kay) >= {"doluluk", "uyum", "gozler", "referans", "zaman"} and kay["referans"] == "kayitli")
denetle("göz alanları (4.3)", set(kay["gozler"][0]) == {"bolge", "goz", "durum", "doluluk", "adet", "urun", "gorulen",
                                                          "benzerlik", "etiket", "fiyat"})
denetle("iki göz dolu", [g["durum"] for g in kay["gozler"]] == ["dolu", "dolu"])
denetle("aradaki karede kontrol yok", not iz.guncelle(kare(), 5.0)["kontrol"])
r = iz.guncelle(kare(), 10.0)
denetle("değişmeyen karede dedektör atlanır, kayıt yok", m.cagri == 2 and r["kayit"] is None)
# g2 boşalır: kutular yalnız solda
m.kutular = dolu_kutular[:4]
bos_kare = kare(renk_sag=(90, 90, 90))
bos_kare[:, 200:][::7, :] = 90  # doku kalkar
gecisler, olaylar = [], []
for t in (20.0, 30.0, 40.0, 50.0):
    r = iz.guncelle(bos_kare, t)
    gecisler += r["gecisler"]
    o = ol.guncelle(r, t)
    olaylar += o["baslayan"]
denetle("g2 bos geçişi süre dolunca (t=40)", [(g["goz"], g["once"], g["sonra"], g["t"]) for g in gecisler] == [("g2", "dolu", "bos", 40.0)])
denetle("bos_raf olayı açıldı", len(olaylar) == 1 and olaylar[0]["kural"] == "bos_raf" and olaylar[0]["goz"] == "g2"
        and olaylar[0]["gorev"] is True and not olaylar[0]["bitti"])
# kişi önünde: kapali, geçiş yok, olay sürer
r = iz.guncelle(kare(), 60.0, kisiler=[{"b": [210, 0, 390, 200]}])
denetle("kişi önündeyken kapali, geçiş yok", r["gecisler"] == [] and
        [g["durum"] for g in r["kayit"]["gozler"]] == ["dolu", "kapali"])
o = ol.guncelle(r, 60.0)
denetle("kapali olayı kapatmaz", o["biten"] == [] and len(o["suren"]) == 1)
# yeniden dolu
m.kutular = dolu_kutular
biten = []
for t in (70.0, 80.0, 90.0, 100.0):
    r = iz.guncelle(kare(), t)
    biten += ol.guncelle(r, t)["biten"]
denetle("dolu olunca olay kapanır", len(biten) == 1 and biten[0]["bitti"] and biten[0]["kural"] == "bos_raf"
        and biten[0]["sure_sn"] >= 40)
# az: g1'de 4 yüzden 1'i kalır
m.kutular = np.concatenate([dolu_kutular[:1], dolu_kutular[4:]])
az_kare = kare()
az_kare[:, 50:200] = (90, 90, 90)
gec = []
for t in (110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0):
    gec += iz.guncelle(az_kare, t)["gecisler"]
denetle("g1 az (60 sn kalıcılık)", [(g["goz"], g["sonra"]) for g in gec] == [("g1", "az")])
# alma doğrulaması: tetikten sonra yüz sayısı 1 -> 0
m.kutular = dolu_kutular[4:]
r1 = iz.guncelle(kare(renk_sol=(90, 90, 90)), 171.0, tetik=[("b1", "g1")])
r2 = iz.guncelle(kare(renk_sol=(90, 90, 90)), 173.5)
ad = r1["adet_degisimleri"] + r2["adet_degisimleri"]
denetle("tetikli iki bakışta yüz sayısı değişimi 1 -> 0", [(a["goz"], a["once"], a["sonra"], a["tetik"]) for a in ad]
        == [("g1", 1, 0, True)])

# geçici referans: dosya yok, ilk kontroller referans olur
m2 = SahteModel()
m2.ofset = (0, 0)
m2.kutular = dolu_kutular
iz2 = R.RafIzleyici(ayar, m2, referans=None)
r = iz2.guncelle(kare(), 0.0)
denetle("geçici referans toplanırken kayıt yok", r["kayit"] is None)
iz2.guncelle(kare(), 1.0)
r = iz2.guncelle(kare(), 2.0)
denetle("geçici referans hazır, kayıtta 'gecici'", r["kayit"] is not None and r["kayit"]["referans"] == "gecici"
        and [g["durum"] for g in r["kayit"]["gozler"]] == ["dolu", "dolu"])

# --- örnek mağaza kliplerinde bulunan hatalar (2026-11-15) -----------------------------------------------------------
print("örnek kliplerden gelen hatalar")
ayar5 = {"bolgeler": [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": [[0, 0], [1, 0], [1, 1], [0, 1]], "gozler": [
    {"kimlik": "g1", "kutu": [0.0, 0.0, 0.25, 1.0], "adet": 2}, {"kimlik": "g2", "kutu": [0.25, 0.0, 0.5, 1.0], "adet": 2},
    {"kimlik": "g3", "kutu": [0.5, 0.0, 0.75, 1.0], "adet": 2}, {"kimlik": "g4", "kutu": [0.75, 0.0, 1.0, 1.0], "adet": 1}]}],
    "raf_araligi_sn": 1, "ozellikler": {"bos_raf": {"sure_sn": 1}}}
kutu4 = np.array([[5, 20, 45, 180], [55, 20, 95, 180], [105, 20, 145, 180], [155, 20, 195, 180]], np.float32)


def raf_kare(g3_dolu=False, g1_renk=(40, 80, 160)):
    k = np.zeros((H, W, 3), np.uint8)
    k[:, :100] = g1_renk
    k[:, 100:200] = (160, 80, 40)
    k[:, :200][::7, :] = 255                      # g1, g2: dokulu ürünler
    k[:, 200:300] = (200, 200, 205)               # g3: boş raf (gri-beyaz, düz)
    k[:, 200:300][::25, :] = 185
    if g3_dolu:
        k[:, 200:300] = (40, 160, 80)
        k[:, 200:300][::7, :] = 255
    k[:, 300:] = (0, 220, 240)                    # g4: sarı koli (dedektör bulmuyor), kenarları ve yazısı var
    k[:, 300:][::30, :] = (0, 150, 170)
    return k


m5 = SahteModel()
m5.ofset = (0, 0)
m5.kutular = kutu4
iz5 = R.RafIzleyici(ayar5, m5, referans=raf_kare())
durum5 = {}
for t in (0.0, 1.0, 2.0, 3.0):
    r = iz5.guncelle(raf_kare(), t)
    durum5 = {g["goz"]: g["durum"] for g in (r["kayit"] or {"gozler": []})["gozler"]} or durum5
denetle("referansta zaten boş göz (gri, dokusuz, ürün yok) boş bildirilir", durum5.get("g3") == "bos")
denetle("dedektörün görmediği düz renkli koli referansta boş sayılmaz", durum5.get("g4") == "dolu")
denetle("dolu gözler dolu", durum5.get("g1") == durum5.get("g2") == "dolu")
gec = []
iz5.a["dolu_sure_sn"] = 1.0
for t in (4.0, 5.0, 6.0, 7.0):
    gec += iz5.guncelle(raf_kare(g3_dolu=True), t)["gecisler"]
denetle("referansta boş göze ürün konunca dolu olur", ("g3", "bos", "dolu") in [(g["goz"], g["once"], g["sonra"]) for g in gec])
# kimse dokunmadan sayının oynaması alma değildir
m5.kutular = kutu4[1:]
ad = []
for t in (8.0, 9.0, 10.0, 11.0):
    ad += iz5.guncelle(raf_kare(g1_renk=(42, 80, 160)), t)["adet_degisimleri"]
denetle("kimse değmeden g1'de 2->1: alma adayı değil (gürültü)", ad == [])
# kişi g1'e değer (kısmen, %12'nin altında): karar ve sayım yapılmaz; ayrılınca düşüş alma adayıdır
m5.kutular = kutu4[2:]
r = iz5.guncelle(raf_kare(g1_renk=(44, 80, 160)), 12.0, kisiler=[{"b": [90, 150, 160, 200]}])
denetle("kişi değen gözde durum kararı verilmez (kapali gibi)", r["gecisler"] == [])
ad = []
for t in (13.0, 14.0, 15.0):  # son ürün alındı: gözün görünümü değişti
    ad += iz5.guncelle(raf_kare(g1_renk=(120, 120, 120)), t)["adet_degisimleri"]
denetle("kişi değdikten sonra g1'de 1->0 düşüş alma adayı", [(a["goz"], a["once"], a["sonra"]) for a in ad] == [("g1", 1, 0)])
# çok yüzlü gözde +1 geri koyma sayılmaz; boş göze konan sayılır
g = iz5.gozler[1]
g.ref_adet, g.adet_kararli, g.adet_gecmis, g.dokunma_t = 6, 6, [6, 6, 6], 20.0
sonuc_ = {"adet_degisimleri": []}
for t in (21.0, 22.0, 23.0):
    iz5._sayim(g, {"adet": 7}, t, sonuc_)
denetle("6 yüzlü gözde 6->7 (dedektör oynaması) geri koyma sayılmaz", sonuc_["adet_degisimleri"] == [] and g.adet_kararli == 7)
g.adet_kararli, g.adet_gecmis = 0, [0, 0, 0]
for t in (24.0, 25.0):
    iz5._sayim(g, {"adet": 1}, t, sonuc_)
denetle("artış bir gözlem fazlasını ister", sonuc_["adet_degisimleri"] == [])
iz5._sayim(g, {"adet": 1}, 26.0, sonuc_)
denetle("boş göze konan ürün geri koyma adayı (0->1)", [(a["once"], a["sonra"]) for a in sonuc_["adet_degisimleri"]] == [(0, 1)])


# etiket teyidi (sahte okuyucu)
class SahteEtiket:
    def __init__(self):
        self.sira = []

    def oku(self, kare, kutu, beklenen, tolerans=0.01):
        d = self.sira.pop(0) if len(self.sira) > 1 else self.sira[0]
        return {"durum": "okundu" if d in ("uygun", "farkli") else d, "etiket": d, "metin": "x",
                "fiyat": 39.9 if d == "farkli" else (34.9 if d == "uygun" else None)}


ayar3 = {"bolgeler": [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": [[0, 0], [1, 0], [1, 1], [0, 1]],
                       "gozler": [{"kimlik": "g1", "kutu": [0.0, 0.0, 0.5, 0.8], "adet": 4, "etiket": [0.1, 0.85, 0.3, 0.95],
                                   "fiyat": 34.9}]}], "raf_araligi_sn": 10}
et = SahteEtiket()
et.sira = ["uygun", "farkli", "farkli", "farkli"]
m3 = SahteModel()
m3.ofset = (0, 0)
m3.kutular = dolu_kutular[:4]
iz3 = R.RafIzleyici(ayar3, m3, referans=ref, etiketci=et)
iz3.a["etiket_araligi_sn"] = 30
iz3.a["fiyat_farkli_sure_sn"] = 50
ol3 = R.RafOlaylari(iz3)
eg, ob = [], []
for t in range(0, 200, 10):
    r = iz3.guncelle(kare(), float(t))
    eg += r["etiket_gecisleri"]
    ob += ol3.guncelle(r, float(t))["baslayan"]
denetle("etiket: uygun hemen; farkli en az iki okuma ve 50 sn sonra (t=90) kesinleşir",
        [(e["once"], e["sonra"], e["t"]) for e in eg] == [("bakilmadi", "uygun", 0.0), ("uygun", "farkli", 90.0)])
denetle("fiyat_farkli olayı (deger 39.9, beklenen 34.9)", len(ob) == 1 and ob[0]["kural"] == "fiyat_farkli"
        and ob[0]["deger"] == 39.9 and ob[0]["beklenen"] == 34.9)
denetle("kayıtta etiket farkli ve fiyat", iz3.kayit()["gozler"][0]["etiket"] == "farkli" and iz3.kayit()["gozler"][0]["fiyat"] == 39.9)

gec = sum(1 for _, k in sonuc if k)
print(f"\n{gec}/{len(sonuc)} geçti")
sys.exit(0 if gec == len(sonuc) else 1)
