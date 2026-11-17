"""Arayüzsüz Studio koşusunu (studio.py) gerçek Studio olmadan, sahte bir `python -m studio` ile sınar.

  python egitim/dene_arayuzsuz.py

Sahte Studio, gerçeğinin --json çıktısını taklit eder: lifecycle satırları, --step verilirse sonuç satırıyla çıkış; verilmezse
(sürekli kip) kendiliğinden bitmez. Denenenler: blok dosyalarının yazılması, deneme koşusu, kameranın ortam değişkenleriyle
verilmesi (adres komut satırına girmez), durdurma dosyası ve süreç ağacının kapatılması, Studio'nun reddettiği koşunun nedeni,
panelin modeli hiç yüklememesi ve bağlantı denemesinin Studio'yu çalıştırmaması; Studio'nun çıktısının maskelenerek günlüğe
yazılması (kısa şifre ve tek seferlik yerel adres dahil), koşu başına durdurma dosyası, birden çok kameranın ayrı koşuları,
geç durdurulan ya da karesi yazılamayan bağlantı denemesi, lisans kodu girilmemiş Studio, işaretli çıkış kodu ve son satır,
nedende ve günlükte kullanıcı klasörünün geçmemesi.
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

kok = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(kok))
import studio  # noqa: E402
import studio_blok  # noqa: E402

SAHTE = r'''
import json, os, sys, time
arg = sys.argv[1:]
def yaz(**o):
    print(json.dumps(o), flush=True)
kayit = os.path.join(os.getcwd(), "sahte-ortam.json")
with open(kayit, "a", encoding="utf-8") as f:
    f.write(json.dumps({"arg": arg, "kamera": os.environ.get("RAF_KAMERA"), "adres": os.environ.get("RAF_KAMERA_ADRES"),
                        "dur": os.environ.get("RAF_DUR"), "opencv": os.environ.get("OPENCV_LOG_LEVEL"),
                        "ffmpeg": os.environ.get("OPENCV_FFMPEG_LOGLEVEL")}) + "\n")
adres = os.environ.get("RAF_KAMERA_ADRES")
if adres:  # OpenCV / FFmpeg'in yazabileceği: adres ve parçaları
    from urllib.parse import urlsplit
    u = urlsplit(adres)
    sys.stderr.write(f"aciliyor {adres}\n")
    sys.stderr.write(f"login user={u.username} password: {u.password} belirtec {u.password} bitti, maxq7 kalir\n")
    sys.stderr.flush()
for ad, deger in sorted(os.environ.items()):  # ortamla verilen tek seferlik yerel adres
    if ad.startswith("RAF_") and ad.endswith("_URL"):
        sys.stderr.write(f"aliniyor {deger} maskeleme icin\n")
        sys.stderr.flush()
yaz(type="lifecycle", state="starting")
if os.environ.get("RAF_KAMERA", "").startswith("eof"):  # lisansı olmayan Studio konsoldan kod ister
    sys.stderr.write("EOFError: EOF when reading a line\n")
    sys.exit(1)
if os.environ.get("RAF_KAMERA", "").startswith("cokme"):
    sys.stderr.write("fatal: acilamadi " + os.path.join(os.getcwd(), "sahne.bin") + "\n")
    sys.stderr.flush()
    os._exit(-1)
if os.environ.get("RAF_KAMERA", "").startswith("lisanssiz"):
    print("Verification code: ", end="", flush=True)
    yaz(type="result", success=False, exit_code=2, failure_type="license", error="License is not active")
    sys.exit(2)
yaz(type="lifecycle", state="started")
if "--step" in arg:
    sonuc = os.environ.get("RAF_DENEME_SONUC")
    if sonuc:  # motorun deneme koşusu: model açıldı mı (SAHTE_MODEL=lisans ise lisans hatası)
        hata = os.environ.get("SAHTE_MODEL", "")
        with open(sonuc, "w", encoding="utf-8") as f:
            json.dump({"ok": not hata, "hata": "lisans: Studio lisansı etkin değil" if hata == "lisans" else hata}, f)
    time.sleep(0.3)
    yaz(type="result", success=True, exit_code=0, duration_ms=300)
    sys.exit(0)
while True:  # gerçek Studio gibi sürekli kipte kendiliğinden bitmez (durdurma dosyasına bloklar bakar)
    time.sleep(0.2)
'''

sonuc = []


def denetle(ad, kosul):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad, flush=True)


gecici = Path(tempfile.mkdtemp(prefix="raf-arayuzsuz-"))
studio.KOSU_KLASORU = gecici / "veri" / "studio"
studio.DURUM_DOSYASI = gecici / "veri" / "studio.json"
studio.SABLON_KAYNAK = gecici / "raf-kamera.pmod"
studio.SABLON_KAYNAK.write_bytes(b"sahte sahne")
studio.MOTOR_KAYNAK = gecici / "motor"
(studio.MOTOR_KAYNAK / "raf_motor").mkdir(parents=True)
(studio.MOTOR_KAYNAK / "raf_motor" / "__init__.py").write_text("", encoding="utf-8")
studio.marketplace = lambda: gecici / "marketplace"
studio.studio_python = lambda: Path(sys.executable)
paket = studio.KOSU_KLASORU / "studio"
paket.mkdir(parents=True)
(paket / "__init__.py").write_text("", encoding="utf-8")
(paket / "__main__.py").write_text(SAHTE, encoding="utf-8")


def ortamlar():
    yol = studio.KOSU_KLASORU / "sahte-ortam.json"
    return [json.loads(s) for s in yol.read_text(encoding="utf-8").splitlines()] if yol.exists() else []


print("Blok dosyaları")
motor = studio.bloklari_kur()
bloklar = gecici / "marketplace" / "custom_blocks"
dosyalar = sorted(p.name for p in bloklar.glob("*.py"))
denetle("dört blok dosyası yazıldı", dosyalar == sorted(t["opCode"] + ".py" for t in studio_blok.TANIMLAR))
ham = (bloklar / "RafVideo.py").read_bytes()
denetle("Studio'nun ürettiği gibi CRLF satır sonu", b"\r\n" in ham and b"\n" not in ham.replace(b"\r\n", b""))
denetle("motor yanına yerleşti, veri klasörü yazıldı", (motor / "raf_motor" / "__init__.py").exists() and (motor / "ayar.json").exists())
damgalar = {p.name: p.stat().st_mtime_ns for p in bloklar.glob("*.py")}
time.sleep(0.05)
studio.bloklari_kur()
denetle("değişmeyen blok dosyalarına dokunulmaz", damgalar == {p.name: p.stat().st_mtime_ns for p in bloklar.glob("*.py")})
for t in studio_blok.TANIMLAR:
    compile(studio_blok.dosya_metni(t), t["opCode"], "exec")
denetle("üretilen blok dosyaları derlenebilir", True)

print("Deneme koşusu")
d = studio.dene(30)
denetle("deneme geçti, hazır kaydedildi", d["hazir"] and json.loads(studio.DURUM_DOSYASI.read_text())["hazir"] is True)
denetle("deneme --step ile sınırlı", "--step" in ortamlar()[-1]["arg"])
os.environ["SAHTE_MODEL"] = "lisans"
try:
    studio.dene(30)
    denetle("model lisans yüzünden açılmazsa deneme geçmez", False)
except studio.StudioHatasi as e:
    denetle("model lisans yüzünden açılmazsa deneme geçmez", "lisans" in str(e).lower())
denetle("başarısız deneme hazır=False ve nedenini kaydeder", json.loads(studio.DURUM_DOSYASI.read_text())["hazir"] is False and "lisans" in json.loads(studio.DURUM_DOSYASI.read_text())["hata"].lower())
del os.environ["SAHTE_MODEL"]
studio.dene(30)
denetle("lisans gelince deneme yeniden geçer", json.loads(studio.DURUM_DOSYASI.read_text())["hazir"] is True)

print("Panel modeli yüklemez")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import kamera  # noqa: E402
import kurallar  # noqa: E402,F401
import rapor  # noqa: E402,F401
import uygulama  # noqa: E402,F401

denetle("panelin modülleri onnxruntime yüklemez", "onnxruntime" not in sys.modules and "raf_motor.blok" not in sys.modules)
kamera.yollar.AYAR = gecici / "veri" / "ayar"
video = gecici / "deneme.mp4"
yazici = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
for i in range(10):
    yazici.write(np.full((48, 64, 3), 20 * i, np.uint8))
yazici.release()
onceki = len(ortamlar())
ayar = {"kod": "dnm", "kamera": {"tur": "dosya", "yol": str(video)}}
kod = kamera.test(ayar, kamera.yollar.AYAR / "dnm.json")
kare = cv2.imread(str(kamera.yollar.AYAR / "_kare_dnm.jpg"))
denetle("bağlantı denemesi bir kare alır ve kaydeder", kod == 0 and kare is not None and kare.shape[:2] == (48, 64))
denetle("bağlantı denemesi Studio'yu çalıştırmaz, modeli yüklemez", len(ortamlar()) == onceki and "onnxruntime" not in sys.modules)
import threading  # noqa: E402

gec = threading.Event()
gercek_ac = kamera.ac


def ac_ve_durdur(src):  # durdurma, kamera bağlandıktan sonra (kare okunurken) gelir
    cap = gercek_ac(src)
    gec.set()
    return cap


kamera.ac = ac_ve_durdur
ayar_gec = {"kod": "gec", "kamera": {"tur": "dosya", "yol": str(video)}}
r = kamera.test(ayar_gec, kamera.yollar.AYAR / "gec.json", dur=gec)
kamera.ac = gercek_ac
denetle("kare yazılmadan önce durdurulan deneme kare kaydetmez", r == 2 and not (kamera.yollar.AYAR / "_kare_gec.jpg").exists())
gercek_yaz = cv2.imwrite
cv2.imwrite = lambda *a, **k: False  # kare yazılamıyor (disk dolu, klasör yazılamıyor)
r = kamera.test(ayar_gec, kamera.yollar.AYAR / "gec.json")
cv2.imwrite = gercek_yaz
denetle("kaydedilemeyen kare denemeyi başarısız yapar", r == 1 and not (kamera.yollar.AYAR / "_kare_gec.jpg").exists())
r = kamera.test(ayar_gec, kamera.yollar.AYAR / "gec.json", dur=threading.Event())
denetle("kaydedilen kare denemeyi geçirir", r == 0 and (kamera.yollar.AYAR / "_kare_gec.jpg").exists())

print("Kamera koşusu")
bilgi = asyncio.run(studio.sahne_kur("kapi", {"kamera": {"tur": "rtsp"}}))
asyncio.run(studio.yeni_kosu(bilgi, "kapi"))
gizli = "rtsp://kullanici:GIZLI-sifre@10.0.0.9/akis"
asyncio.run(studio.kamera_adresi(bilgi, gizli))
onceki = len(ortamlar())
asyncio.run(studio.calistir(bilgi))
for _ in range(50):
    if len(ortamlar()) > onceki:
        break
    time.sleep(0.1)
o = ortamlar()[-1]
denetle("kamera kodu ve koşu ortamdan verilir", o["kamera"] == f"kapi#{bilgi['kosu']}")
denetle("akış adresi yalnızca sürecin ortamında", o["adres"] == gizli and gizli not in " ".join(o["arg"]))
denetle("canlı akışta Studio çökünce yeniden başlatır", "--on-fail" in o["arg"] and "restart" in o["arg"])
denetle("koşu sürerken sorun yok", studio.kosu_sorunu(bilgi) is None and bilgi["surec"].calisiyor())
denetle("her koşunun kendi durdurma dosyası var", Path(o["dur"]).name == f"kapi-{bilgi['kosu']}.dur")
denetle("canlı adreste OpenCV / FFmpeg günlüğü kapalı", o["opencv"] == "SILENT" and o["ffmpeg"] == "-8")


def gunluk_bekle(ad, isaret):
    yol = studio.KOSU_KLASORU / f"{ad}.log"
    for _ in range(50):  # Studio'nun stderr'i arka planda okunur
        if yol.exists() and isaret in yol.read_text(encoding="utf-8"):
            break
        time.sleep(0.1)
    return yol.read_text(encoding="utf-8") if yol.exists() else ""


metin = gunluk_bekle("kapi", "kalir")
denetle("Studio'nun çıktısı günlüğe adres, kullanıcı ve şifre maskelenmiş olarak ulaşır",
        "aciliyor ****" in metin and "GIZLI" not in metin and "10.0.0.9" not in metin and "kullanici" not in metin
        and "user=****" in metin and "password: ****" in metin)
bas = time.monotonic()
asyncio.run(studio.durdur(bilgi))
denetle("durdurulunca süreç kapandı (kendiliğinden bitmeyen sürekli kip)", not bilgi["surec"].calisiyor())
denetle("durdurma dosyası temizlendi", not Path(o["dur"]).exists())
denetle("adres hiçbir dosyaya yazılmadı", not any("GIZLI" in p.read_text(encoding="utf-8", errors="ignore")
                                                  for p in (gecici / "veri").rglob("*") if p.is_file() and p.name != "sahte-ortam.json"))
denetle("koşu listesi boşaldı", "kapi" not in studio.KOSULAR)

bilgi = asyncio.run(studio.sahne_kur("kapi2", {"kamera": {"tur": "rtsp"}}))
asyncio.run(studio.yeni_kosu(bilgi, "kapi2"))
asyncio.run(studio.kamera_adresi(bilgi, "rtsp://ab:q7@10.0.0.9/akis"))
asyncio.run(studio.calistir(bilgi))
metin = gunluk_bekle("kapi2", "kalir")
denetle("iki karakterli kullanıcı adı ve şifre de maskelenir, başka sözcüklere dokunulmaz",
        "user=**** password: **** belirtec **** bitti, maxq7 kalir" in metin and "ab:q7" not in metin)
asyncio.run(studio.durdur(bilgi))

yerel_adres = "http://127.0.0.1:50999/" + "Zx9" * 8
k = studio.baslat("_gorev", "y1", adim=3, ek_ortam={"RAF_GOREV_KARE_URL": yerel_adres})
k.surec.wait(20)
metin = gunluk_bekle("_gorev", "maskeleme icin")
denetle("ortamla verilen tek seferlik yerel adres ve anahtarı günlüğe ulaşmaz",
        "aliniyor **** maskeleme icin" in metin and "127.0.0.1" not in metin and "Zx9Zx9" not in metin)
with studio._KILIT:
    studio.KOSULAR.pop("_gorev", None)

print("Birden çok kamera aynı anda")
b1 = asyncio.run(studio.sahne_kur("raf1", {"kamera": {"tur": "dosya"}}))
b2 = asyncio.run(studio.sahne_kur("raf2", {"kamera": {"tur": "dosya"}}))
for b, kod_ in ((b1, "raf1"), (b2, "raf2")):
    asyncio.run(studio.yeni_kosu(b, kod_))
    asyncio.run(studio.calistir(b))
denetle("her kameranın koşusu kendi kaydında, ikisi birden çalışır",
        studio.KOSULAR.get("raf1") is b1["surec"] and studio.KOSULAR.get("raf2") is b2["surec"]
        and b1["surec"].calisiyor() and b2["surec"].calisiyor() and b1["surec"].dur != b2["surec"].dur)
t0 = time.monotonic()
studio.durdur_hepsi()
gecen = time.monotonic() - t0
denetle("durdur_hepsi bütün kameraların koşularını kapatır, durdurma dosyası kalmaz",
        not b1["surec"].calisiyor() and not b2["surec"].calisiyor() and not studio.KOSULAR
        and not any(studio.KOSU_KLASORU.glob("*.dur")))
denetle(f"kameralar birlikte kapatılır: süre kamera sayısıyla uzamaz ({gecen:.1f} sn)", gecen < 5.5)

print("Studio reddederse")
bilgi = asyncio.run(studio.sahne_kur("lisanssiz", {"kamera": {"tur": "dosya"}}))
asyncio.run(studio.yeni_kosu(bilgi, "lisanssiz"))
asyncio.run(studio.calistir(bilgi))
bilgi["surec"].surec.wait(20)
neden = studio.kosu_sorunu(bilgi) or ""
denetle("kendiliğinden biten koşunun nedeni bildirilir", "License is not active" in neden)
denetle("video dosyasında yeniden başlatma yok", "--on-fail" not in ortamlar()[-1]["arg"])
bilgi = asyncio.run(studio.sahne_kur("eof", {"kamera": {"tur": "dosya"}}))
asyncio.run(studio.yeni_kosu(bilgi, "eof"))
asyncio.run(studio.calistir(bilgi))
bilgi["surec"].surec.wait(20)
neden = studio.kosu_sorunu(bilgi) or ""
denetle("konsoldan lisans kodu isteyen Studio etkinleştirilmemiş olarak bildirilir",
        "etkinleştirilmemiş" in neden and "lisans kodu girilmemiş" in neden)
bilgi = asyncio.run(studio.sahne_kur("cokme", {"kamera": {"tur": "dosya"}}))
asyncio.run(studio.yeni_kosu(bilgi, "cokme"))
asyncio.run(studio.calistir(bilgi))
bilgi["surec"].surec.wait(20)
neden = studio.kosu_sorunu(bilgi) or ""
denetle("çökme işaretli çıkış kodu ve son satırla bildirilir", "çıkış kodu -1" in neden and "4294967295" not in neden
        and "fatal: acilamadi" in neden)
ev = os.environ.get("USERPROFILE") or ""
denetle("kullanıcı klasörü nedende ve günlükte geçmez",
        bool(ev) and str(gecici).lower().startswith(ev.lower()) and ev.lower() not in neden.lower()
        and "%LOCALAPPDATA%" in neden
        and ev.lower() not in (studio.KOSU_KLASORU / "cokme.log").read_text(encoding="utf-8").lower())
try:
    asyncio.run(studio.sahne_kur("usb", {"kamera": {"tur": "usb"}}))
    denetle("desteklenmeyen kamera türü açıkça reddedilir", False)
except studio.StudioHatasi as e:
    denetle("desteklenmeyen kamera türü açıkça reddedilir", "desteklenmiyor" in str(e))

studio.durdur_hepsi()
kalan = [ad for ad, ok in sonuc if not ok]
print(f"\n{len(sonuc) - len(kalan)}/{len(sonuc)} denetim geçti" + (f" · kalanlar: {kalan}" if kalan else ""))
sys.exit(1 if kalan else 0)
