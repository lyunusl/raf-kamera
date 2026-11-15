"""Panelin veri tarafını AugeLab Studio olmadan sınar: kuyruk alımı, türetilen ölçüler, görevler, doğrulama, göç.

  python egitim/dene_panel.py

Veri klasörü geçicidir (RAF_KAMERA_VERI). Denetlenenler:
  - eski veritabanı yeni sütunlarla güvenle güncellenir (satırlar kalır)
  - raf kaydı: göz geçmişi yalnızca değişiklikte yazılır, son durum güncellenir, geç gelen eski kayıt son durumu ezmez
  - etkileşim kaydı; bozuk ya da eksik alanlı kayıt diğerlerini durdurmaz
  - görev açan olay görevi açar, olay kapanınca görev kapanır ve tepki süresi yazılır
  - elle hesaplanmış küçük örnekte: boş süre, doldurma tepki süresi, kayıp satış (göz ve bölge yöntemi), saate göre tükenme,
    huni, bekleme, şimdiki doluluk ve planogram uyumu, çalışma saatine göre kırpma
  - bölge / göz / ürün / özellik girdisinin sunucu tarafı doğrulaması (Türkçe ileti, kimlikler korunur)
  - saklama süresi dolan kayıtların temizliği
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
kok = Path(__file__).resolve().parent.parent
VERI = Path(tempfile.mkdtemp(prefix="raf_dene_panel_"))
os.environ["RAF_KAMERA_VERI"] = str(VERI)
sys.path.insert(0, str(kok))

import yollar  # noqa: E402

yollar.hazirla()

# --- 1. göç: iskeletin eski şemasıyla bir veritabanı (yeni sütunlar yok)
ESKI = """
CREATE TABLE olay (id INTEGER PRIMARY KEY AUTOINCREMENT, kimlik TEXT, suruyor INTEGER NOT NULL DEFAULT 0, zaman TEXT NOT NULL, kamera TEXT NOT NULL,
  kamera_ad TEXT NOT NULL, kural TEXT NOT NULL, kural_ad TEXT NOT NULL, kategori TEXT NOT NULL, duzey TEXT NOT NULL, bolge TEXT, onem INTEGER NOT NULL,
  olasilik INTEGER NOT NULL, puan INTEGER NOT NULL, ciddi INTEGER NOT NULL, sure_sn REAL NOT NULL, x REAL, y REAL, klip TEXT, kare TEXT, aciklama TEXT,
  ornek INTEGER NOT NULL DEFAULT 0, durum TEXT NOT NULL DEFAULT 'acik', ustlenen TEXT, notlar TEXT, durum_zamani TEXT);
CREATE TABLE gorev (id INTEGER PRIMARY KEY AUTOINCREMENT, baslik TEXT NOT NULL, aciklama TEXT, sorumlu TEXT, son_tarih TEXT,
  durum TEXT NOT NULL DEFAULT 'acik', kamera TEXT, kural TEXT, bolge TEXT, olusturma TEXT NOT NULL, kapanma TEXT);
INSERT INTO olay (kimlik, zaman, kamera, kamera_ad, kural, kural_ad, kategori, duzey, onem, olasilik, puan, ciddi, sure_sn)
  VALUES ('eski1', '2025-12-01T10:00:00', 'k0', 'Eski', 'bos_raf', 'Boş raf', 'raf', 'yuksek', 3, 3, 9, 0, 40);
INSERT INTO gorev (baslik, olusturma) VALUES ('Eski görev', '2025-12-01T10:00:00');
"""
c = sqlite3.connect(yollar.VT)
c.executescript(ESKI)
c.commit()
c.close()

import depo  # noqa: E402
import kuyruk  # noqa: E402
import rapor  # noqa: E402
import uygulama  # noqa: E402

sonuc: list[tuple[str, bool]] = []


def kontrol(ad: str, kosul: bool, ayrinti="") -> None:
    sonuc.append((ad, bool(kosul)))
    print(("  ok  " if kosul else "  HATA ") + ad + ("" if kosul else f"  ({ayrinti})"))


depo.vt()
sutunlar = {r["name"] for r in depo.sor("PRAGMA table_info(olay)")}
kontrol("göç: olay tablosuna yeni sütunlar eklendi", {"goz", "urun", "gorev", "bitis", "bolge_kimlik"} <= sutunlar)
kontrol("göç: gorev tablosuna yeni sütunlar eklendi", {"olay", "otomatik", "tepki_sn", "baslama", "notlar", "ornek"} <= {r["name"] for r in depo.sor("PRAGMA table_info(gorev)")})
kontrol("göç: eski satırlar korundu", depo.sor("SELECT COUNT(*) AS n FROM olay WHERE kimlik = 'eski1'")[0]["n"] == 1
        and depo.sor("SELECT COUNT(*) AS n FROM gorev")[0]["n"] == 1)
depo.kapat()
depo.vt()  # ikinci açılış: göç yeniden çalışır ama hiçbir şey değiştirmez
kontrol("göç: ikinci açılış hatasız", depo.sor("SELECT COUNT(*) AS n FROM olay")[0]["n"] == 1)
depo.yaz("DELETE FROM olay")
depo.yaz("DELETE FROM gorev")

# --- ürün ve kamera (gerçek doğrulama yollarından)
u1 = uygulama.urun_kaydet({"ad": "Deneme suyu", "fiyat": "10", "barkod": "1234567"})
u2 = uygulama.urun_kaydet({"ad": "Deneme kola", "fiyat": 20})
# canlı kamera: kayıt bırakmayı kestiğinde son durum en çok ESKI_SN uzatılır (video dosyasında uzatılmaz: aşağıda)
uygulama.ayar_kaydet({"kod": "rafk", "ad": "Raf K", "kamera": {"tur": "rtsp", "adres": "rtsp://10.0.0.9/a"}, "bolgeler": [
    {"ad": "Raf 1", "tur": "raf", "poly": [[0, 0], [1, 0], [1, 0.5], [0, 0.5]], "gozler": [
        {"kutu": [0.1, 0.1, 0.3, 0.4], "urun": u1["kimlik"], "adet": 2, "fiyat": 10},
        {"kutu": [0.4, 0.1, 0.6, 0.4], "urun": u2["kimlik"], "adet": 3}]},
    {"ad": "Koridor", "tur": "koridor", "poly": [[0, 0.5], [1, 0.5], [1, 1], [0, 1]]}]})
ayar = json.loads((yollar.AYAR / "rafk.json").read_text(encoding="utf-8"))
b1 = ayar["bolgeler"][0]["kimlik"]
g1, g2 = (g["kimlik"] for g in ayar["bolgeler"][0]["gozler"])
kontrol("ayar: bölge ve göz kimlikleri verildi", b1 == "b1" and (g1, g2) == ("g1", "g2") and ayar["bolgeler"][1]["kimlik"] == "b2")

# --- kuyruk kayıtları (motorun yazdığı biçimde)
SAYAC = [0]


def birak(k: dict) -> None:
    SAYAC[0] += 1
    kuyruk.KLASOR.mkdir(parents=True, exist_ok=True)
    (kuyruk.KLASOR / f"{SAYAC[0]:020d}_{k['kamera']}_{SAYAC[0]}.json").write_text(json.dumps(k, ensure_ascii=False), encoding="utf-8")


GUN = "2026-01-05"  # pazartesi (geçmişte: "şimdi" dönemin dışında)


def raf(saat: str, d1: str, d2: str, f1=10.0, e1="uygun", g1_gorulen=None, doluluk=None):
    birak({"tur": "raf", "kosu": "t", "kamera": "rafk", "zaman": f"{GUN}T{saat}", "doluluk": doluluk, "uyum": 1.0, "referans": "gecici",
           "gozler": [{"bolge": b1, "goz": g1, "durum": d1, "doluluk": {"dolu": 1.0, "az": 0.3, "bos": 0.0, "yanlis": 0.8}[d1], "urun": u1["kimlik"],
                       "gorulen": g1_gorulen, "etiket": e1, "fiyat": f1},
                      {"bolge": b1, "goz": g2, "durum": d2, "doluluk": {"dolu": 1.0, "az": 0.3, "bos": 0.0}[d2], "urun": u2["kimlik"], "etiket": "uygun", "fiyat": 20.0}]})


raf("10:00:00", "dolu", "bos")
raf("10:05:00", "dolu", "bos")              # değişiklik yok: geçmişe satır eklenmez
raf("10:20:00", "dolu", "dolu")
raf("11:00:00", "bos", "dolu")
raf("11:30:00", "dolu", "dolu")
raf("12:00:00", "dolu", "dolu")
for dk in (10, 20, 40, 50):                  # g1'den dört alma (ürün varken)
    birak({"tur": "etkilesim", "kosu": "t", "kamera": "rafk", "zaman": f"{GUN}T10:{dk:02d}:00", "bolge": b1, "goz": g1, "eylem": "aldi"})
birak({"tur": "etkilesim", "kosu": "t", "kamera": "rafk", "zaman": f"{GUN}T10:30:00", "bolge": b1, "goz": None, "eylem": "durdu", "sure_sn": 12})
birak({"tur": "etkilesim", "kosu": "t", "kamera": "rafk", "zaman": f"{GUN}T10:31:00", "bolge": b1, "goz": None, "eylem": "durdu", "sure_sn": 40})
birak({"tur": "etkilesim", "kosu": "t", "kamera": "rafk", "zaman": f"{GUN}T10:32:00", "eylem": "bilinmeyen"})   # atlanır
birak({"tur": "olcum", "kosu": "t", "kamera": "rafk", "kamera_ad": "Raf K", "bas": f"{GUN}T10:00:00", "sure_sn": 3600, "analiz": 100,
       "veri": {"gecen": 100, "duran": 10, "uzanan": 6, "alan": 3, "bekleme_sn": 300, "bekleme_sayi": 10, "kadin": 60, "erkek": 40,
                f"b:{b1}:gecen": 80, f"b:{b1}:duran": 30, f"b:{b1}:uzanan": 9, f"b:{b1}:alan": 4, f"b:{b1}:bekleme_sn": 100, f"b:{b1}:bekleme_sayi": 5},
       "izgara": {"gen": 2, "yuk": 1, "katmanlar": {"yogunluk": [[1, 3]]}}})
birak({"tur": "olcum", "kosu": "t", "kamera": "rafk", "bas": "bozuk"})   # eksik alan: atlanır, diğerlerini durdurmaz
kuyruk.al()
kontrol("kuyruk: bütün dosyalar işlendi (bozuklar dahil silindi)", not list(kuyruk.KLASOR.glob("*.json")))

gecmis = depo.sor("SELECT * FROM raf_durum WHERE goz = ? ORDER BY zaman", g1)
kontrol("raf: göz geçmişi yalnızca değişiklikte (g1: 3 satır)", [r["durum"] for r in gecmis] == ["dolu", "bos", "dolu"], [r["durum"] for r in gecmis])
son = depo.sor("SELECT * FROM raf_son WHERE goz = ?", g1)[0]
kontrol("raf: son durum ve geçiş anı", son["zaman"] == f"{GUN}T12:00:00" and son["degisim"] == f"{GUN}T11:30:00" and son["durum"] == "dolu")
kontrol("raf: kamera özeti her kayıtta, referans durumu saklandı", depo.sor("SELECT COUNT(*) AS n FROM raf_ozet WHERE referans = 'gecici'")[0]["n"] == 6)
raf("09:00:00", "bos", "bos")  # geç gelen eski kayıt
kuyruk.al()
kontrol("raf: geç gelen eski kayıt son durumu ezmez", depo.sor("SELECT durum FROM raf_son WHERE goz = ?", g1)[0]["durum"] == "dolu")
depo.yaz("DELETE FROM raf_ozet WHERE zaman < ?", f"{GUN}T10:00:00")
kontrol("etkileşim: geçerli kayıtlar alındı, bilinmeyen eylem atlandı", depo.sor("SELECT COUNT(*) AS n FROM etkilesim")[0]["n"] == 6)
kontrol("ölçüm: bozuk kayıt atlandı, geçerli olan alındı", depo.sor("SELECT COUNT(*) AS n FROM olcum")[0]["n"] == 1)

# --- türetilen ölçüler (elle hesap)
depo.genel_yaz({"calisma": {"bas": "08:00", "bit": "22:00"}})
q = {"bas": GUN, "bit": GUN}
r = rapor.raf_olculeri(f"{GUN}T00:00:00", f"{GUN}T23:59:59")
x1 = next(x for x in r["gozler"] if x["goz"] == g1)
x2 = next(x for x in r["gozler"] if x["goz"] == g2)
# g1: dolu 10:00-11:00 (3600) + 11:30-12:10 (son görülme 12:00 + 600 sn = 2400) = 6000 sn; boş 11:00-11:30 = 1800 sn
kontrol("ölçü: g1 boş süre 1800 sn, ürün var 6000 sn", x1["bos_sn"] == 1800 and x1["dolu_sn"] == 6000, (x1["bos_sn"], x1["dolu_sn"]))
# video dosyası çözümlemesi: son kayıttan sonra durum uzatılmaz (10 sn'lik örnek klipteki boş göz 10 dk boş sayılmıyordu)
a_ = json.loads((yollar.AYAR / "rafk.json").read_text(encoding="utf-8"))
a_["kamera"] = {"tur": "dosya", "yol": "x.mp4"}
(yollar.AYAR / "rafk.json").write_text(json.dumps(a_, ensure_ascii=False), encoding="utf-8")
x1d = next(x for x in rapor.raf_olculeri(f"{GUN}T00:00:00", f"{GUN}T23:59:59")["gozler"] if x["goz"] == g1)
kontrol("ölçü: video dosyasında son görülmeden sonra uzatılmaz (ürün var 3600 + 1800 sn)", x1d["dolu_sn"] == 5400 and x1d["bos_sn"] == 1800,
        (x1d["bos_sn"], x1d["dolu_sn"]))
a_["kamera"] = {"tur": "rtsp", "adres": "rtsp://10.0.0.9/a"}
(yollar.AYAR / "rafk.json").write_text(json.dumps(a_, ensure_ascii=False), encoding="utf-8")
# alma hızı 4 / 6000 sn → kayıp = 1800 × 4/6000 = 1,2 adet × 10 TL = 12 TL
kontrol("ölçü: kayıp satış (göz yöntemi) 1,2 adet / 12 TL", x1["kayip_adet"] == 1.2 and x1["kayip_tutar"] == 12.0 and x1["yontem"] == "goz", (x1["kayip_adet"], x1["kayip_tutar"]))
# g2: boş 10:00-10:20 = 1200 sn; alma yok → bölgeden: (30 duran / 3600 sn) × 0,3 (duran < 20: varsayılan dönüşüm) / 2 göz = 0,00125 /sn → 1,5 adet × 20 TL
kontrol("ölçü: kayıp satış (bölge yöntemi) 1,5 adet / 30 TL", x2["bos_sn"] == 1200 and x2["kayip_adet"] == 1.5 and x2["kayip_tutar"] == 30.0 and x2["yontem"] == "bolge",
        (x2["bos_sn"], x2["kayip_adet"], x2["kayip_tutar"]))
dolum = sorted(r["dolum"], key=lambda d: d["bas"])
kontrol("ölçü: doldurma tepki süreleri (g2 1200 sn, g1 1800 sn)", [(d["goz"], d["sure_sn"], d["bos"]) for d in dolum] == [(g2, 1200, True), (g1, 1800, True)], dolum)
kontrol("ölçü: doldurma ortalama 1500, ortanca 1500", r["toplam"]["dolum_ort_sn"] == 1500 and r["toplam"]["dolum_medyan_sn"] == 1500)
kontrol("ölçü: saate göre tükenme (pazartesi 10:00 → 20 dk, 11:00 → 30 dk)", r["matris"][0][10] == 20 and r["matris"][0][11] == 30 and sum(map(sum, r["matris"])) == 50, r["matris"][0][9:13])
# çalışma saatine göre kırpma
kontrol("ölçü: çalışma süresi gece kırpılır (21:30 → ertesi 08:30 = 1 saat)",
        depo.calisma_suresi(dt.datetime(2026, 1, 5, 21, 30), dt.datetime(2026, 1, 6, 8, 30)) == 3600)
kontrol("ölçü: gece yarısını geçen çalışma (20:00-02:00)",
        depo.calisma_suresi(dt.datetime(2026, 1, 5, 23, 0), dt.datetime(2026, 1, 6, 3, 0), {"calisma": {"bas": "20:00", "bit": "02:00"}}) == 3 * 3600)
kontrol("ölçü: çalışma saatinde mi", depo.calisma_saatinde(dt.datetime(2026, 1, 5, 21, 59)) and not depo.calisma_saatinde(dt.datetime(2026, 1, 5, 22, 0)))
m = rapor.musteri({**q, "kamera": "rafk"})
kontrol("huni: kamera bazında gecen → duran → uzanan → alan", m["huni"] == {"gecen": 100, "duran": 10, "uzanan": 6, "alan": 3}, m["huni"])
kontrol("bekleme: ortalama 300/10 = 30 sn; durma dağılımı (12 sn, 40 sn)", m["toplam"]["ort_bekleme_sn"] == 30.0 and m["bekleme"]["ort"] == 26.0
        and [k["n"] for k in m["bekleme"]["dagilim"]] == [0, 1, 0, 1, 0, 0])
br = next(x for x in m["bolgeler"] if x["bolge"] == b1)
kontrol("bölge tablosu: durma oranı 30/80, alma oranı 4/80, ort. bekleme 20 sn", br["durma_orani"] == 0.375 and br["alma_orani"] == 0.05 and br["ort_bekleme_sn"] == 20.0, br)
kontrol("ısı haritası: ızgara toplandı", m["harita"]["katmanlar"]["yogunluk"] == [[1.0, 3.0]])
kontrol("demografi yalnızca toplu sayı", m["demografi"]["kadin"] == 60 and m["demografi"]["erkek"] == 40)
s = rapor._simdi_sayilari(rapor.goz_tanimlari(), rapor._son_durumlar())
kontrol("şimdi: doluluk ortalaması ve uyum (2 dolu göz)", s["doluluk"] == 1.0 and s["uyum"] == 1.0 and s["sayilar"]["dolu"] == 2, s)
eg = rapor._raf_egilimi(f"{GUN}T00:00:00", f"{GUN}T23:59:59")
kontrol("eğilim: iki günden kısa dönemde saatlik", [e["d"] for e in eg] == [f"{GUN}T10:00", f"{GUN}T11:00", f"{GUN}T12:00"], eg)
gb = rapor.genel_bakis(q)
kontrol("genel bakış: kayıp toplamı 42 TL, dikkat listesi", gb["donem"]["kayip_tutar"] == 42.0 and isinstance(gb["dikkat"], list))
rf = rapor.raflar({**q, "kamera": "rafk"})
kontrol("raflar: geçici referans uyarısı", rf["referans_gecici"] is True and rf["kamera"] == "rafk" and len(rf["bolgeler"][0]["gozler"]) == 2)
gg = rapor.goz_gecmisi({**q, "kamera": "rafk", "goz": g1})
kontrol("göz geçmişi: aralıklar, alma, fiyat okumaları", [a["durum"] for a in gg["araliklar"]] == ["dolu", "bos", "dolu"] and gg["olcu"]["alma"] == 4 and gg["fiyatlar"])
ul = rapor.urun_listesi(q)
kontrol("ürünler: yer ve kayıp ürün başına", next(u for u in ul["urunler"] if u["kimlik"] == u1["kimlik"])["kayip_tutar"] == 12.0)
for ad in rapor.DISA_TABLOLAR:
    baslik, sutun, satirlar = rapor.disa_tablo(ad, q)
    kontrol(f"dışa aktarma: {ad}", isinstance(satirlar, list) and all(len(s) == len(sutun) for s in satirlar))
kontrol("dışa aktarma: tükenmeler iki satır", len(rapor.disa_tablo("tukenmeler", q)[2]) == 2)

# --- görevler: olay görevi açar ve kapanınca kapatır
OLAY = {"tur": "olay", "kosu": "t", "kimlik": "o1", "zaman": f"{GUN}T13:00:00", "kamera": "rafk", "kamera_ad": "Raf K", "kural": "bos_raf",
        "kural_ad": "Boş raf", "kategori": "raf", "duzey": "yuksek", "onem": 3, "olasilik": 3, "puan": 9, "ciddi": False, "sure_sn": 20, "x": 0.2, "y": 0.2,
        "aciklama": "Göz boş.", "bitti": False, "bolge": b1, "goz": g1, "urun": u1["kimlik"], "urun_ad": "Deneme suyu", "gorev": True}
birak(OLAY)
yeni = kuyruk.al()
gv = depo.sor("SELECT * FROM gorev WHERE olay = ?", yeni[0])
kontrol("görev: olayla kendiliğinden açıldı", len(gv) == 1 and gv[0]["durum"] == "acik" and gv[0]["otomatik"] == 1 and gv[0]["goz"] == g1 and "Deneme suyu" in gv[0]["baslik"])
o = depo.sor("SELECT * FROM olay WHERE id = ?", yeni[0])[0]
kontrol("olay: bölge adı ayardan, göz ve ürün saklandı", o["bolge"] == "Raf 1" and o["bolge_kimlik"] == b1 and o["urun"] == u1["kimlik"])
birak({**OLAY, "sure_sn": 25 * 60, "bitti": True})
kuyruk.al()
gv = depo.sor("SELECT * FROM gorev WHERE olay = ?", yeni[0])[0]
o = depo.sor("SELECT * FROM olay WHERE id = ?", yeni[0])[0]
kontrol("görev: olay kapanınca kapandı, tepki 1500 sn", gv["durum"] == "kapandi" and gv["tepki_sn"] == 1500 and gv["kapanma"] == f"{GUN}T13:25:00", gv)
kontrol("olay: kapanış zamanı ve kendiliğinden çözüldü", o["bitis"] == f"{GUN}T13:25:00" and o["durum"] == "cozuldu" and o["suruyor"] == 0)
birak({**OLAY, "kimlik": "o2", "kural": "yogunluk", "gorev": False})
yeni2 = kuyruk.al()
kontrol("görev: gorev=false olay görev açmaz", depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE olay = ?", yeni2[0])[0]["n"] == 0)
birak({**OLAY, "kimlik": "o3", "bitti": True, "sure_sn": 60})
yeni3 = kuyruk.al()
kontrol("görev: tek kayıtta başlayıp biten olayın görevi hemen kapanır", depo.sor("SELECT durum, tepki_sn FROM gorev WHERE olay = ?", yeni3[0])[0] == {"durum": "kapandi", "tepki_sn": 60.0})
gl = rapor.gorev_listesi({"bas": GUN, "bit": GUN})
kontrol("görev listesi: tepki istatistiği", gl["tepki"]["n"] == 2 and gl["tepki"]["ort_sn"] == 780, gl["tepki"])

# --- doğrulama (sunucu tarafı, Türkçe ileti, hiçbir şey yazılmaz)


def hata_verir(fn, *a, icerir=""):
    try:
        fn(*a)
    except uygulama.AyarHatasi as e:
        return icerir in str(e)
    return False


urunler = {u1["kimlik"], u2["kimlik"]}
B = uygulama.bolgeleri_denetle
kontrol("doğrulama: bilinmeyen bölge türü", hata_verir(B, [{"tur": "depo", "poly": [[0, 0], [1, 0], [1, 1]]}], urunler, icerir="Bilinmeyen bölge türü"))
kontrol("doğrulama: üçten az köşe", hata_verir(B, [{"tur": "raf", "ad": "R", "poly": [[0, 0], [1, 0]]}], urunler, icerir="en az üç köşe"))
kontrol("doğrulama: 0-1 dışında nokta", hata_verir(B, [{"tur": "raf", "poly": [[0, 0], [1.5, 0], [1, 1]]}], urunler, icerir="arasında olmalı"))
kontrol("doğrulama: katalogda olmayan ürün", hata_verir(B, [{"tur": "raf", "poly": [[0, 0], [1, 0], [1, 1]], "gozler": [{"kutu": [0.1, 0.1, 0.2, 0.2], "urun": "u99"}]}], urunler, icerir="katalogda yok"))
kontrol("doğrulama: ters çizilmiş kutu", hata_verir(B, [{"tur": "raf", "poly": [[0, 0], [1, 0], [1, 1]], "gozler": [{"kutu": [0.3, 0.1, 0.2, 0.2]}]}], urunler, icerir="ters"))
kontrol("doğrulama: yüz sayısı 1-99", hata_verir(B, [{"tur": "raf", "poly": [[0, 0], [1, 0], [1, 1]], "gozler": [{"kutu": [0.1, 0.1, 0.2, 0.2], "adet": 0}]}], urunler, icerir="yüz sayısı"))
kontrol("doğrulama: koridora göz eklenmez", hata_verir(B, [{"tur": "koridor", "poly": [[0, 0], [1, 0], [1, 1]], "gozler": [{"kutu": [0.1, 0.1, 0.2, 0.2]}]}], urunler, icerir="göz yalnızca"))
kontrol("doğrulama: girişte iç nokta zorunlu", hata_verir(B, [{"tur": "giris", "cizgi": [[0, 0], [1, 1]]}], urunler, icerir="iç tarafını"))
kontrol("doğrulama: yinelenen kimlik", hata_verir(B, [{"kimlik": "b1", "tur": "koridor", "poly": [[0, 0], [1, 0], [1, 1]]}, {"kimlik": "b1", "tur": "koridor", "poly": [[0, 0], [1, 0], [1, 1]]}], urunler, icerir="birden çok"))
v = B([{"kimlik": "b7", "tur": "raf", "poly": [[0, 0], [1, 0], [1, 1]], "gozler": [{"kimlik": "g9", "kutu": [0.1, 0.1, 0.2, 0.2]}, {"kutu": [0.3, 0.1, 0.4, 0.2], "fiyat": "12,5".replace(",", ".")}]},
       {"tur": "giris", "cizgi": [[0, 0], [1, 1]], "ic": [0.2, 0.8]}, {"tur": "kasa", "poly": [[0, 0], [1, 0], [1, 1]], "esik": 5}], urunler)
kontrol("doğrulama: var olan kimlik korunur, yenilere sıradaki verilir", [b["kimlik"] for b in v] == ["b7", "b8", "b9"] and [g["kimlik"] for g in v[0]["gozler"]] == ["g9", "g10"])
kontrol("doğrulama: göz varsayılanları (adet 1, fiyat sayı)", v[0]["gozler"][0]["adet"] == 1 and v[0]["gozler"][1]["fiyat"] == 12.5 and v[2]["esik"] == 5)
kontrol("doğrulama: örnek önekli kod gerçek kamerada reddedilir", hata_verir(uygulama._ayar_hazirla, {"kod": "ornek-x", "kamera": {"tur": "dosya"}}, icerir="örnek"))
oz = uygulama.ozellikleri_denetle
import kurallar  # noqa: E402

if kurallar.KURALLAR:
    kod_ = next(k for k in kurallar.KURALLAR if k.get("ayarlar"))
    a_, t_ = next(iter(kod_["ayarlar"].items()))
    en_cok = t_.get("en_cok") if isinstance(t_, dict) else None
    kontrol("özellik: bilinmeyen kod reddedilir", hata_verir(oz, {"yok_boyle": {"acik": True}}, icerir="Bilinmeyen özellik"))
    if en_cok is not None:
        kontrol("özellik: katalog sınırının dışındaki ayar reddedilir", hata_verir(oz, {kod_["kod"]: {a_: en_cok * 10 + 1}}, icerir="arasında"))
    kontrol("özellik: geçerli ayar kabul edilir", oz({kod_["kod"]: {"acik": False}})[kod_["kod"]]["acik"] is False)
else:
    kontrol("özellik: katalog boşken düz ayar kabul edilir", oz({"bos_raf": {"acik": True, "sure_sn": 30}}) == {"bos_raf": {"acik": True, "sure_sn": 30}})
# gözler değişince referansın yenilenmesi gerektiği işaretlenir; referans istekle değiştirilemez
a0 = json.loads((yollar.AYAR / "rafk.json").read_text(encoding="utf-8"))
a0["referans"] = {"zaman": "2000-01-01T00:00:00"}  # istekle gönderilen referans yok sayılır
a0["bolgeler"][0]["gozler"][0]["kutu"] = [0.1, 0.1, 0.25, 0.4]
uygulama.ayar_kaydet(a0)
a1 = json.loads((yollar.AYAR / "rafk.json").read_text(encoding="utf-8"))
kontrol("ayar: gözler değişince gozler_degisim yazılır, referans istekle yazılamaz", a1.get("gozler_degisim") and "referans" not in a1)
kontrol("ürün: boş ad reddedilir", hata_verir(uygulama.urun_kaydet, {"ad": " "}, icerir="adını"))
kontrol("ürün: aynı barkod reddedilir", hata_verir(uygulama.urun_kaydet, {"ad": "X", "barkod": "1234567"}, icerir="barkod"))
kontrol("ürün: planogramda kullanılan ürün silinmez", hata_verir(uygulama.urun_sil, u1["kimlik"], icerir="planogramda"))
kontrol("ürün: fiyat virgüllü yazılabilir", uygulama.urun_kaydet({"kimlik": u2["kimlik"], "ad": "Deneme kola", "fiyat": "21,5"})["fiyat"] == 21.5)

# --- saklama süresi dolan kayıtlar
depo.genel_yaz({"saklama_gun": 30, "klip_gun": 7})
eski = (dt.datetime.now() - dt.timedelta(days=40)).replace(microsecond=0).isoformat()
depo.ekle("olay", {"kimlik": "eski-k", "zaman": eski, "kamera": "rafk", "kamera_ad": "R", "kural": "bos_raf", "kural_ad": "B", "kategori": "raf", "duzey": "orta",
                   "onem": 1, "olasilik": 1, "puan": 1, "ciddi": 0, "sure_sn": 5, "suruyor": 0})
depo.ekle("olay", {"kimlik": "eski-s", "zaman": eski, "kamera": "rafk", "kamera_ad": "R", "kural": "bos_raf", "kural_ad": "B", "kategori": "raf", "duzey": "orta",
                   "onem": 1, "olasilik": 1, "puan": 1, "ciddi": 0, "sure_sn": 5, "suruyor": 1})
depo.ekle("etkilesim", {"kamera": "rafk", "zaman": eski, "eylem": "aldi"})
once_ = depo.sor("SELECT COUNT(*) AS n FROM etkilesim")[0]["n"]
depo.eskileri_temizle()
kontrol("temizlik: kapanmış eski olay silindi, süren olay kaldı", depo.sor("SELECT kimlik FROM olay WHERE kimlik LIKE 'eski-%'") == [{"kimlik": "eski-s"}])
kontrol("temizlik: eski etkileşimler silindi (yeni olanlar değil, 2026 başı da 30 günden eski)", depo.sor("SELECT COUNT(*) AS n FROM etkilesim")[0]["n"] < once_)
kontrol("temizlik: her gözün son durumu korunur", depo.sor("SELECT COUNT(*) AS n FROM raf_durum WHERE goz = ?", g1)[0]["n"] >= 1)

basarili = sum(1 for _, ok in sonuc if ok)
print(f"\n{basarili}/{len(sonuc)} denetim geçti.")
sys.exit(0 if basarili == len(sonuc) else 1)
