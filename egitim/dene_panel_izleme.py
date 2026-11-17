"""Canlı izlemeyi (kamera başına ayrı koşu), çalışma saatine göre kendiliğinden yeniden başlatmayı ve örnek videoları sınar.

  python egitim/dene_panel_izleme.py

AugeLab Studio çalıştırılmaz: studio.sahne_kur / yeni_kosu / calistir / durdur sahte işlevlerle değiştirilir (dene_is_akisi.py'deki
gibi); çalışma saati sahte bir saatle açılıp kapatılır. Veri klasörü geçicidir. Denetlenenler:
  - birden çok kamera aynı anda canlı izlenir; her biri kendi işi, kendi koşu numarası, kendi durdurma / hata yolu
  - en çok EN_COK_CANLI kamera (Türkçe ileti); aynı kamera iki kez başlatılmaz; video dosyası canlı izlenmez
  - tek seferlik işler (video analizi, motor işi) yine birer birer; canlı izleme bu sırayı tutmaz
  - bir kameranın hatası ya da durdurulması diğerlerini etkilemez; kullanıcının durdurduğu kamera istenenlerden çıkar
  - çalışma saati bitince izleme durur, açılışta istenen kameralar kendiliğinden yeniden başlar
  - panel yeniden açılınca istenen kameralar çalışma saatindeyse başlar; şifre gereken kamera (şifre diske yazılmaz)
    "şifre bekleniyor" olarak kalır, ortam değişkeninde şifre varsa başlar; şifre hiçbir dosyaya yazılmaz
  - izlenen kamera silinemez; geliştirme kipinde planlayıcı hiçbir şey başlatmaz
  - örnek videolar: ornekler/ klasöründen listelenir (ad sabit değil), ayarları kimlikleriyle kurulur, sırayla çözümlenir,
    sonuçları örnek veriden ayrı işaretlenir (ornek = 2) ve "örnek verileri kaldır" onları silmez
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
kok = Path(__file__).resolve().parent.parent
VERI = Path(tempfile.mkdtemp(prefix="raf_dene_izleme_"))
os.environ["RAF_KAMERA_VERI"] = str(VERI)
os.environ.pop("RAF_GELISTIRME", None)
os.environ.pop("KAMERA_SIFRE", None)
sys.path.insert(0, str(kok))

import yollar  # noqa: E402

yollar.hazirla()
import depo  # noqa: E402
import kamera  # noqa: E402
import kuyruk  # noqa: E402
import studio  # noqa: E402
import uygulama  # noqa: E402

depo.vt()
sys.stdout, sys.stderr = uygulama.YON_OUT, uygulama.YON_ERR  # main() gibi: her işin print çıktısı kendi kaydına düşer
sonuc: list[tuple[str, bool]] = []


def kontrol(ad: str, kosul: bool, ayrinti="") -> None:
    sonuc.append((ad, bool(kosul)))
    print(("  ok  " if kosul else "  HATA ") + ad + ("" if kosul else f"  ({ayrinti})"))


def bekle(kosul, sn=10.0) -> bool:
    son = time.time() + sn
    while time.time() < son:
        if kosul():
            return True
        time.sleep(0.05)
    return False


# --- sahte Studio ve sahte saat
SAAT = {"acik": True}
CALISAN: set[str] = set()
DURDURULAN: list[str] = []
SIFRE_GELEN: dict[str, str | None] = {}
depo.calisma_saatinde = lambda an, g=None: SAAT["acik"]


async def sahne_kur(kod, ayar):
    return {"kod": kod}


async def yeni_kosu(bilgi, kod):
    bilgi["kosu"] = f"k-{kod}-{time.time_ns()}"
    return bilgi["kosu"]


async def kamera_adresi(bilgi, adres):
    bilgi["adres"] = adres


async def calistir(bilgi, sure_ms=None):
    CALISAN.add(bilgi["kod"])
    return {}


async def durdur(bilgi):
    CALISAN.discard(bilgi["kod"])
    DURDURULAN.append(bilgi["kod"])


def kaynak(ayar, sifre):
    SIFRE_GELEN[ayar["kod"]] = sifre
    return "rtsp://ornek", "rtsp://ornek"


studio.sahne_kur, studio.yeni_kosu, studio.kamera_adresi, studio.calistir, studio.durdur = sahne_kur, yeni_kosu, kamera_adresi, calistir, durdur
studio.kosu_sorunu = lambda bilgi: None
kamera.kaynak = kaynak
kuyruk.bosalsin = lambda kod, en_cok=None, sakin=1.5: True
uygulama._model_engeli = lambda: None
uygulama.IZLEME_ARA_SN = 0.0
uygulama.GELISTIRME = False

for kod, adres in (("c1", "rtsp://10.0.0.1/a"), ("c2", "rtsp://10.0.0.2/a"), ("c3", "rtsp://10.0.0.3/a"), ("c4", "rtsp://admin:{sifre}@10.0.0.4/a")):
    uygulama.ayar_kaydet({"kod": kod, "ad": f"Kamera {kod}", "kamera": {"tur": "rtsp", "adres": adres}})
uygulama.ayar_kaydet({"kod": "v1", "ad": "Video", "kamera": {"tur": "dosya", "yol": "x.mp4"}})

sunucu = uygulama.Sunucu(("127.0.0.1", 0), uygulama.Istek)
threading.Thread(target=sunucu.serve_forever, daemon=True).start()
TABAN = f"http://127.0.0.1:{sunucu.server_address[1]}"


def post(yol, govde):
    r = urllib.request.Request(TABAN + yol, data=json.dumps(govde).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=30) as y:
            return y.status, json.loads(y.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def durum(kod):
    i = uygulama.IZLEMELER.get(kod)
    return i.durum if i else None


# --- birden çok kamera aynı anda
uygulama.EN_COK_CANLI = 2
st1, y1 = post("/api/is/izle", {"kod": "c1"})
st2, y2 = post("/api/is/izle", {"kod": "c2"})
kontrol("iki kamera aynı anda başladı", st1 == 200 and st2 == 200 and bekle(lambda: CALISAN == {"c1", "c2"}), (st1, y1, st2, y2, CALISAN))
kontrol("her kameranın kendi işi var", uygulama.IZLEMELER["c1"] is not uygulama.IZLEMELER["c2"] and durum("c1") == durum("c2") == "calisiyor")
st, y = post("/api/is/izle", {"kod": "c3"})
kontrol("sınır: en çok 2 kamera (Türkçe ileti)", st == 409 and "en çok 2 kamera" in y["hata"], y)
st, y = post("/api/is/izle", {"kod": "c1"})
kontrol("aynı kamera iki kez başlatılmaz", st == 409 and "zaten izleniyor" in y["hata"], y)
st, y = post("/api/is/izle", {"kod": "v1"})
kontrol("video dosyası canlı izlenmez", st == 400, y)
kontrol("istenenler dosyada (yalnızca kodlar)", json.loads((VERI / "izleme.json").read_text(encoding="utf-8")) == {"kameralar": ["c1", "c2"]})
d = uygulama.durum()
kontrol("durumda kamera başına izleme", d["izlemeler"]["c1"]["durum"] == "calisiyor" and d["izlemeler"]["c2"]["istenen"] and d["en_cok_canli"] == 2)

# tek seferlik işler sırayla, canlı izleme onları engellemez
dur_is = threading.Event()
ok1, _ = uygulama.is_baslat("video", "Video analizi", lambda is_: dur_is.wait(10) and {})
ok2, m2 = uygulama.is_baslat("motor", "Motor işi", lambda is_: {})
kontrol("tek seferlik iş canlı izleme sürerken başlar; ikincisi beklemeli (Türkçe)", ok1 and not ok2 and "çalışıyor" in m2, m2)
dur_is.set()
bekle(lambda: uygulama.AKTIF.durum != "calisiyor")

# bir kameranın hatası diğerini etkilemez: c2'nin koşusu motorun "hata" kaydını bırakmış gibi
asil_kh = kuyruk.kosu_hatasi
kuyruk.kosu_hatasi = lambda kod, kosu="": "model açılamadı" if kod == "c2" else asil_kh(kod, kosu)
kontrol("c2 hatayla bitti", bekle(lambda: durum("c2") == "hata"), durum("c2"))
kuyruk.kosu_hatasi = asil_kh
kontrol("c1 hatadan etkilenmedi", durum("c1") == "calisiyor" and "c1" in CALISAN)
kontrol("hatalı kameranın hatası kendi kaydında (Türkçe)", any("çalışmıyor" in s for s in uygulama.IZLEMELER["c2"].satirlar), uygulama.IZLEMELER["c2"].satirlar[-3:])
kontrol("hata sonrası kamera hâlâ istenen (yeniden denenecek)", "c2" in uygulama.istenen_izlemeler())
st, y = post("/api/ayar/sil", {"kod": "c1"})
kontrol("izlenen kamera silinemez", st == 409 and "izleniyor" in y["hata"], y)

# kullanıcının durdurması
st, y = post("/api/izleme/durdur", {"kod": "c1"})
kontrol("c1 durduruldu, sahne kapatıldı", st == 200 and bekle(lambda: durum("c1") != "calisiyor") and "c1" in DURDURULAN and "c1" not in CALISAN)
kontrol("durdurulan kamera istenenlerden çıktı", uygulama.istenen_izlemeler() == ["c2"])

# --- çalışma saati: kapanışta durur, açılışta yeniden başlar
uygulama.izleme_planla()  # c2'yi (hata sonrası istenen) yeniden başlatır
kontrol("hatadan sonra yeniden deneme başladı", bekle(lambda: durum("c2") == "calisiyor"))
st, y = post("/api/is/izle", {"kod": "c4", "sifre": "gizli-sifre"})
kontrol("şifreli kamera başladı (şifre bellekte)", st == 200 and bekle(lambda: durum("c4") == "calisiyor") and SIFRE_GELEN.get("c4") == "gizli-sifre")
kontrol("çalışma saati kararı istek anında verilir (iş parçacığı geç kalsa da kapanışta durur)",
        uygulama.IZLEMELER["c4"].saatte_basladi is True and uygulama.IZLEMELER["c2"].saatte_basladi is True)
SAAT["acik"] = False
kontrol("kapanışta bütün izlemeler kendiliğinden durdu", bekle(lambda: durum("c2") != "calisiyor" and durum("c4") != "calisiyor") and not CALISAN, CALISAN)
kontrol("kapanışta istenenler korunur", sorted(uygulama.istenen_izlemeler()) == ["c2", "c4"])
kontrol("kapalıyken planlayıcı başlatmaz", uygulama.izleme_planla() == [])
kontrol("durumda 'açılışta başlar' bilgisi", "açılışta" in (uygulama.izleme_durumlari()["c2"]["bekleme"] or ""))
SIFRE_GELEN.clear()
SAAT["acik"] = True
basladi = uygulama.izleme_planla()
kontrol("açılışta istenen kameralar kendiliğinden başladı", sorted(basladi) == ["c2", "c4"] and bekle(lambda: CALISAN == {"c2", "c4"}), (basladi, CALISAN))
kontrol("şifre bellekten yeniden verildi", SIFRE_GELEN.get("c4") == "gizli-sifre")
kontrol("şifre hiçbir dosyaya yazılmadı", not any(b"gizli-sifre" in p.read_bytes() for p in VERI.rglob("*") if p.is_file() and p.suffix != ".db")
        and b"gizli-sifre" not in (VERI / "raf.db").read_bytes())

# --- panel yeniden açıldı: bellek boş, istenenler dosyada
for i in uygulama.IZLEMELER.values():
    i.dur.set()
bekle(lambda: not CALISAN)
bekle(lambda: all(i.durum != "calisiyor" for i in uygulama.IZLEMELER.values()))
uygulama.IZLEMELER.clear()
uygulama._SIFRELER.clear()
uygulama._IZLEME_DURUMU.clear()
basladi = uygulama.izleme_planla()
kontrol("yeniden açılışta şifresiz kamera başladı", basladi == ["c2"] and bekle(lambda: "c2" in CALISAN), basladi)
kontrol("şifre gereken kamera 'şifre bekleniyor'", "Şifre bekleniyor" in (uygulama.izleme_durumlari()["c4"]["bekleme"] or ""))
os.environ["KAMERA_SIFRE"] = "ortamdaki"
kontrol("ortam değişkeninde şifre varsa başlar", uygulama.izleme_planla() == ["c4"] and bekle(lambda: "c4" in CALISAN))
os.environ.pop("KAMERA_SIFRE")
# planlayıcı döngüsü (arka plan iş parçacığı) ve geliştirme kipi
uygulama.GELISTIRME = True
kontrol("geliştirme kipinde planlayıcı hiçbir şey başlatmaz", uygulama.izleme_planla() == [])
uygulama.GELISTIRME = False
for i in uygulama.IZLEMELER.values():
    i.dur.set()
bekle(lambda: all(i.durum != "calisiyor" for i in uygulama.IZLEMELER.values()))
uygulama.IZLEMELER.clear()
dur = threading.Event()
threading.Thread(target=uygulama.izleme_dongusu, args=(dur, 0.1, 0.2), daemon=True).start()
kontrol("arka plan planlayıcısı açılışta istenenleri başlattı (şifresiz c2; şifresi bellekte olmayan c4 bekler)",
        bekle(lambda: durum("c2") == "calisiyor", 5) and durum("c4") is None)
dur.set()
for i in uygulama.IZLEMELER.values():
    i.dur.set()
bekle(lambda: all(i.durum != "calisiyor" for i in uygulama.IZLEMELER.values()))

# --- örnek videolar (ornekler/ klasöründen, ad sabit yazılmadan)
ORN = Path(tempfile.mkdtemp(prefix="raf_ornekler_"))
(ORN / "videolar").mkdir()
(ORN / "ayar").mkdir()
for ad in ("s1", "s3", "Bozuk Ad"):
    (ORN / "videolar" / f"{ad}.mp4").write_bytes(b"video")
(ORN / "ayar" / "s1.json").write_text(json.dumps({"ad": "Örnek raf videosu", "bolgeler": [{"ad": "Raf", "tur": "raf", "poly": [[0, 0], [1, 0], [1, 1]],
                                                                                          "gozler": [{"kutu": [0.1, 0.1, 0.2, 0.3]}]}]}), encoding="utf-8")
yollar.ORNEKLER = ORN
yollar.ORNEK_ADLARI = yollar._ornek_adlari()
kontrol("örnek videolar klasörden listelendi (geçersiz ad atlandı)", yollar.ORNEK_ADLARI == {"s1": "Örnek raf videosu", "s3": "s3"} and yollar.ornek_kodlar() == ["s1", "s3"])
kontrol("durumda örnek video listesi", [o["kod"] for o in uygulama.durum()["ornek_videolar"]] == ["s1", "s3"])
COZULEN = []


def sahte_analiz(is_, kod, en_cok_sn=1800.0):
    COZULEN.append(kod)
    kuyruk.KLASOR.mkdir(parents=True, exist_ok=True)
    (kuyruk.KLASOR / f"{time.time_ns():020d}_{kod}_1.json").write_text(json.dumps({"tur": "olcum", "kosu": "x", "kamera": kod, "bas": "2026-01-05T10:00:00",
                                                                                   "sure_sn": 30, "analiz": 9, "veri": {"gecen": 2}}), encoding="utf-8")
    kuyruk.al()


uygulama.studioda_analiz = sahte_analiz
is_ = uygulama.Is("ornek", "Örnek videolar")
s = uygulama.is_ornek(is_)
a1 = json.loads((yollar.AYAR / "s1.json").read_text(encoding="utf-8"))
kontrol("örnek videolar sırayla çözümlendi", COZULEN == ["s1", "s3"] and s.get("git") == "#/", COZULEN)
kontrol("örnek ayarı kimlikleriyle kuruldu ve işaretli", a1["ornek_video"] is True and a1["bolgeler"][0]["kimlik"] == "b1" and a1["bolgeler"][0]["gozler"][0]["kimlik"] == "g1"
        and a1["kamera"] == {"tur": "dosya", "yol": "videolar/s1.mp4"} and (yollar.VIDEOLAR / "s1.mp4").is_file())
kontrol("örnek video sonuçları ornek = 2", {r["ornek"] for r in depo.sor("SELECT ornek FROM olcum WHERE kamera IN ('s1', 's3')")} == {2})
depo.ornekleri_sil()
kontrol("'örnek verileri kaldır' örnek video sonuçlarını silmez", depo.sor("SELECT COUNT(*) AS n FROM olcum WHERE kamera = 's1'")[0]["n"] == 1)
COZULEN.clear()
uygulama.is_ornek(is_)
kontrol("yeniden çözümlemede önceki sonuçlar silinir", depo.sor("SELECT COUNT(*) AS n FROM olcum WHERE kamera = 's1'")[0]["n"] == 1 and COZULEN == ["s1", "s3"])
st, y = post("/api/ayar", {"ayar": {"kod": "s1", "kamera": {"tur": "dosya"}}, "yeni": True})
kontrol("örnek video kodu gerçek kameraya verilemez", st == 400 and "örnek" in y["hata"], y)
kontrol("kamera listesinde örnek video işareti", next(k for k in __import__("rapor").kameralar() if k["kod"] == "s1")["ornek_video"] is True)

# --- örnek kurulumu: programla gelen ürünler, referans karesi, değişince yenileme, tek örnek, yeniden deneme (2026-11-15)
uygulama.urun_kaydet({"ad": "Kullanıcının ürünü", "fiyat": "10"})
(ORN / "urunler" / "gorsel").mkdir(parents=True)
(ORN / "urunler" / "gorsel" / "ov1_1.jpg").write_bytes(b"\xff\xd8gorsel")
(ORN / "urunler" / "urunler.json").write_text(json.dumps([{"kimlik": "ov1", "ad": "Örnek reçel", "fiyat": 5.5, "gorseller": ["ov1_1.jpg"]},
                                                          {"kimlik": "u99", "ad": "önek dışı: alınmaz"}]), encoding="utf-8")
(ORN / "ayar" / "_referans_s1.jpg").write_bytes(b"\xff\xd8referans")
(ORN / "ayar" / "_referans_s1.json").write_text('{"kisiler": []}', encoding="utf-8")
a = json.loads((ORN / "ayar" / "s1.json").read_text(encoding="utf-8"))
a["bolgeler"][0]["gozler"][0]["urun"] = "ov1"
(ORN / "ayar" / "s1.json").write_text(json.dumps(a), encoding="utf-8")
COZULEN.clear()
uygulama.is_ornek(is_, ["s1"])
a1 = json.loads((yollar.AYAR / "s1.json").read_text(encoding="utf-8"))
urunler = {u["kimlik"]: u for u in depo.urunler()}
kontrol("tek örnek çözümlenebilir (kodlar)", COZULEN == ["s1"], COZULEN)
kontrol("örnek ürün ornek_video işaretiyle kuruldu, görseli kopyalandı; kullanıcının ürünü yerinde; önek dışı alınmadı",
        urunler.get("ov1", {}).get("ornek_video") is True and (depo.gorsel_klasoru() / "ov1_1.jpg").is_file()
        and any(u["ad"] == "Kullanıcının ürünü" for u in urunler.values()) and "u99" not in urunler)
kontrol("programla gelen ayar değişince örnek yeniden kuruldu (göz ürünü, referans karesi ve kişi kutuları)",
        a1["bolgeler"][0]["gozler"][0]["urun"] == "ov1" and (yollar.AYAR / "_referans_s1.jpg").read_bytes() == b"\xff\xd8referans"
        and (yollar.AYAR / "_referans_s1.json").is_file() and a1.get("referans", {}).get("ornek") is True)
a1["elle"] = 1
(yollar.AYAR / "s1.json").write_text(json.dumps(a1), encoding="utf-8")
uygulama.is_ornek(is_, ["s1"])
kontrol("değişmeyen örnek ayarı korunur", json.loads((yollar.AYAR / "s1.json").read_text(encoding="utf-8")).get("elle") == 1)
# Studio süreci sonuç vermeden kapanırsa bir kez daha denenir; model/ayar hatası yinelenmez
DENEME = {"n": 0}


def bir_kez_coker(is_, kod, en_cok_sn=1800.0):
    DENEME["n"] += 1
    if DENEME["n"] == 1:
        raise SystemExit("AugeLab Studio sahneyi çalıştıramadı (süreç sonuç bildirmeden kapandı, çıkış kodu -1).")
    sahte_analiz(is_, kod)


uygulama.studioda_analiz = bir_kez_coker
uygulama.is_ornek(is_, ["s3"])
kontrol("Studio süreci bir kez çökünce örnek yeniden denendi ve bitti", DENEME["n"] == 2, DENEME)
DENEME["n"] = 0
uygulama.studioda_analiz = lambda is_, kod, en_cok_sn=1800.0: (_ for _ in ()).throw(SystemExit("AugeLab Studio'daki analiz çalışmıyor (lisans)."))
try:
    uygulama.is_ornek(is_, ["s3"])
    yinelenmedi = False
except SystemExit:
    yinelenmedi = True
kontrol("lisans/model hatası yinelenmez", yinelenmedi)
uygulama.studioda_analiz = sahte_analiz
# örnekler yeniden çözümlenince örneğin görevleri çoğalmaz (eskiden her çözümlemede aynı görevler yeniden ekleniyordu)


def gorevli_analiz(is_, kod, en_cok_sn=1800.0):
    kuyruk.KLASOR.mkdir(parents=True, exist_ok=True)
    (kuyruk.KLASOR / f"{time.time_ns():020d}_{kod}_9.json").write_text(json.dumps({
        "tur": "olay", "kosu": "x", "kamera": kod, "kimlik": f"o-{time.time_ns()}", "zaman": "2026-01-05T10:00:00", "kural": "bos_raf",
        "kural_ad": "Boş raf", "kategori": "raf", "duzey": "yuksek", "onem": 3, "olasilik": 3, "puan": 9, "ciddi": False, "sure_sn": 5,
        "x": 0.5, "y": 0.5, "aciklama": "Göz boş", "bitti": True, "gorev": True}), encoding="utf-8")
    kuyruk.al()


uygulama.studioda_analiz = gorevli_analiz
uygulama.is_ornek(is_, ["s3"])
uygulama.is_ornek(is_, ["s3"])
kontrol("örnek yeniden çözümlenince görevi çoğalmaz", depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE kamera = 's3'")[0]["n"] == 1,
        depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE kamera = 's3'")[0]["n"])
uygulama.studioda_analiz = sahte_analiz
# saklama temizliği: kayda bağlı olmayan eski klip/kare ve kuyruk artıkları silinir
(yollar.CIKTI / "s1").mkdir(parents=True, exist_ok=True)
eski = time.time() - 40 * 86400
for ad_ in ("artik.ham.mp4", "artik_kare.jpg", "son_kare.jpg"):
    p = yollar.CIKTI / "s1" / ad_
    p.write_bytes(b"x")
    os.utime(p, (eski, eski))
yeni_p = yollar.CIKTI / "s1" / "yeni_kare.jpg"
yeni_p.write_bytes(b"x")
kuyruk.KLASOR.mkdir(parents=True, exist_ok=True)
for ad_, icerik in (("1_s1_1.tmp", "yarim"), ("2_s1_2.json", "{bozuk"), ("3_s1_3.json", json.dumps({"tur": "nabiz", "kamera": "s1"}))):
    p = kuyruk.KLASOR / ad_
    p.write_text(icerik, encoding="utf-8")
    os.utime(p, (eski, eski))
t = depo.eskileri_temizle()
kontrol("eski artık klip/kare silindi; son_kare ve yeni dosya kaldı", not (yollar.CIKTI / "s1" / "artik.ham.mp4").exists()
        and not (yollar.CIKTI / "s1" / "artik_kare.jpg").exists() and (yollar.CIKTI / "s1" / "son_kare.jpg").exists() and yeni_p.exists(), t)
kontrol("kuyrukta eski yarım (.tmp) ve okunamayan kayıt silindi, okunabilir kayıt kaldı",
        not (kuyruk.KLASOR / "1_s1_1.tmp").exists() and not (kuyruk.KLASOR / "2_s1_2.json").exists() and (kuyruk.KLASOR / "3_s1_3.json").exists())

# --- kapanış başladıysa çalışma saati dışında da yeni izleme isteği kaydedilmez
onceki = sorted(uygulama.istenen_izlemeler())
SAAT["acik"] = False
uygulama.KAPANIYOR.set()
st, y = post("/api/is/izle", {"kod": "c3"})
uygulama.KAPANIYOR.clear()
SAAT["acik"] = True
kontrol("kapanırken çalışma saati dışında yeni izleme isteği kaydedilmez",
        st == 409 and "kapanıyor" in str(y) and sorted(uygulama.istenen_izlemeler()) == onceki, (st, y, onceki))

sunucu.shutdown()
basarili = sum(1 for _, ok in sonuc if ok)
print(f"\n{basarili}/{len(sonuc)} denetim geçti.")
sys.exit(0 if basarili == len(sonuc) else 1)
