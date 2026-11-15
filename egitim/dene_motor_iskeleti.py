"""Motor iskeletini (raf_motor.blok) ve dört bloğun ürettiği kodu Studio olmadan sınar.

  python egitim/dene_motor_iskeleti.py

Studio'nun yaptığı gibi: blokların _process kodu studio_blok tanımlarından üretilir, motor geçici bir "marketplace"
klasöründe custom_blocks'un yanına (raf_engine) konur ve bloklar kısa bir video dosyası üzerinde zincir hâlinde çalıştırılır:
Raf Video → Raf Kişi → Raf Ürün → Raf Analiz. Denetlenenler:
  - bloklar motoru custom_blocks'un kardeşi raf_engine'den yükler; kişisiz videoda Kişi ve Ürün boş sonuç verir
  - Analiz kuyruğa nabız, ölçüm ve bitti kaydı bırakır, son kareyi yazar; panelin kuyruğu (kuyruk.al) bunları içeri alır
  - Kişi bloğu hata verirse Analiz "hata" kaydı bırakır (boş sonuç sayılmaz)
  - deneme koşusu: modeller açılınca "ok", tanımlı model dosyası yoksa hata yazar
  - yüz gizleme: baş kutusu pikselleştirilir, kutunun dışı değişmez; Analiz'in verdiği görüntüde baş gizlidir
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
kok = Path(__file__).resolve().parent.parent
gecici = Path(tempfile.mkdtemp(prefix="raf_iskelet_"))
veri = gecici / "veri"
os.environ["RAF_KAMERA_VERI"] = str(veri)
sys.path.insert(0, str(kok))  # motor/ bilerek eklenmez: raf_motor, Studio'daki gibi raf_engine'den yüklenir

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import studio_blok  # noqa: E402

sonuc: list[tuple[str, bool]] = []


def denetle(ad, kosul):
    sonuc.append((ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad, flush=True)


# --- Studio'nun klasör düzeni: marketplace/custom_blocks ve yanında raf_engine
market = gecici / "marketplace"
(market / "custom_blocks").mkdir(parents=True)
motor = market / studio_blok.MOTOR_KLASORU
shutil.copytree(kok / "motor" / "raf_motor", motor / "raf_motor", ignore=shutil.ignore_patterns("__pycache__"))
if (kok / "motor" / "modeller").is_dir():
    shutil.copytree(kok / "motor" / "modeller", motor / "modeller")
(motor / "surum.txt").write_text("sinama", encoding="ascii")
(motor / "ayar.json").write_text(json.dumps({"veri": str(veri)}), encoding="utf-8")
(veri / "ayar").mkdir(parents=True)
video = veri / "videolar" / "deneme.mp4"
video.parent.mkdir(parents=True)
yazici = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
for i in range(12):
    yazici.write(np.full((120, 160, 3), 15 * i, np.uint8))
yazici.release()
(veri / "ayar" / "dnm.json").write_text(json.dumps({"kod": "dnm", "ad": "Deneme", "kamera": {"tur": "dosya", "yol": "videolar/deneme.mp4"},
                                                    "bolgeler": [{"ad": "Raf 1", "tur": "raf", "poly": [[0.1, 0.1], [0.6, 0.1], [0.6, 0.5]]}]}),
                                        encoding="utf-8")


def blok_islevi(tanim):
    """Bloğun _process gövdesini Studio'nun ürettiği gibi bir işleve çevirir (dosya yolu custom_blocks içinde)."""
    govde = "".join("    " + s + "\n" if s.strip() else "\n" for s in tanim["processCode"].rstrip("\n").split("\n"))
    ad_alani = {"__file__": str(market / "custom_blocks" / (tanim["opCode"] + ".py"))}
    exec("import sys, os, importlib\ndef _process(inputs, parameters, state, outputs):\n" + govde, ad_alani)
    return ad_alani["_process"]


def calistir(islev, state, **girdiler):
    outputs = {}
    islev(girdiler, {}, state, outputs)
    return outputs


V, K, U, A = (blok_islevi(t) for t in studio_blok.TANIMLAR)
sv, sk, su, sa = {}, {}, {}, {}
print("Blok zinciri (video dosyası)")
kosu = "dnm#k1"
kareler = kisiler_bos = 0
durumlar = []
for _ in range(40):
    v = calistir(V, sv, Kamera=kosu)
    k = calistir(K, sk, Image=v["Image"], Kamera=kosu, Zaman=v["Zaman"])
    u = calistir(U, su, Image=v["Image"], Kamera=kosu, Zaman=v["Zaman"])
    a = calistir(A, sa, Image=v["Image"], Kisiler=k["Kisiler"], Raf=u["Raf"], Kamera=kosu, Zaman=v["Zaman"], Bitti=v["Bitti"])
    durumlar.append(a["Durum"])
    if v["Image"] is not None:
        kareler += 1
        kisiler_bos += json.loads(k["Kisiler"]).get("kisiler") == [] and json.loads(u["Raf"]).get("gozler") == []
    if v["Bitti"]:
        break
denetle("motor custom_blocks'un kardeşi raf_engine'den yüklendi", "raf_motor.blok" in sys.modules
        and Path(sys.modules["raf_motor.blok"].__file__).resolve().is_relative_to(motor.resolve()))
denetle("video bloğu 12 kareyi okuyup bir kez Bitti verdi", kareler == 12 and v["Bitti"] is True)
denetle("kişisiz videoda Kişi ve Ürün her karede boş sonuç verdi", kisiler_bos == 12)
denetle("Analiz durum satırı çalıştığını söylüyor", any(d.startswith("ok 0 kişi, 0 göz") for d in durumlar) and durumlar[-1].startswith("bitti"))
kayitlar = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((veri / "kuyruk").glob("*.json"))]
turler = [k["tur"] for k in kayitlar]
denetle("kuyruğa nabız, ölçüm ve bitti kaydı bırakıldı (olay yok)", "nabiz" in turler and "olcum" in turler and turler[-1] == "bitti" and "olay" not in turler)
olcum = next(k for k in kayitlar if k["tur"] == "olcum")
denetle("ölçüm kaydı koşu numarası, dönem ve sıfır sayılar taşır (kişi analizi saniyede 3 kez)",
        olcum["kosu"] == "k1" and 3 <= olcum["analiz"] <= 5 and olcum["veri"].get("gecen") == 0 and olcum["veri"].get("kisi_ort") == 0
        and olcum.get("son_kare") == "dnm/son_kare.jpg")
denetle("son kare yazıldı", (veri / "cikti" / "dnm" / "son_kare.jpg").is_file())

print("Panelin kuyruğu")
import depo  # noqa: E402
import kuyruk  # noqa: E402

kuyruk.al()
denetle("kuyruk.al ölçümü veritabanına aldı ve akışın bittiğini gördü",
        len(depo.sor("SELECT * FROM olcum WHERE kamera = 'dnm'")) == 1 and kuyruk.kosu_bitti("dnm", "k1") and not list((veri / "kuyruk").glob("*.json")))
depo.kapat()

print("Kişi bloğu hata verirse")
blok = sys.modules["raf_motor.blok"]
kare = np.full((120, 160, 3), 100, np.uint8)
cikis = blok.analiz({}, kare, '{"hata": "kisi modeli yok"}', '{"sira": 1, "gozler": []}', "dnm#k2", 0.0, False)
hatalar = [json.loads(p.read_text(encoding="utf-8")) for p in (veri / "kuyruk").glob("*.json")]
denetle("hata kaydı bırakılır, durum hatayı söyler", any(h["tur"] == "hata" and h["metin"] == "kisi modeli yok" and h["kosu"] == "k2" for h in hatalar)
        and "analiz çalışmıyor" in cikis[2])
for p in (veri / "kuyruk").glob("*.json"):
    p.unlink()

print("Deneme koşusu (lisans kontrolü)")
sonuc_yolu = gecici / "deneme.json"
os.environ[blok.ORTAM_DENEME_SONUC] = str(sonuc_yolu)
blok.kisi({}, kare, blok.DENEME_KOD, -1)
katalog = sys.modules["raf_motor.katalog"]
denetle("modeller açılınca deneme ok yazar", {k: v for k, v in json.loads(sonuc_yolu.read_text(encoding="utf-8")).items() if k != "onnxruntime"} == {"ok": True, "modeller": sorted(katalog.MODEL_DOSYALARI)})
denetle("deneme hangi onnxruntime yüklendiğini yazar", (json.loads(sonuc_yolu.read_text(encoding="utf-8")).get("onnxruntime") or {}).get("kaynak") in ("studio", "deps"))
katalog.MODEL_DOSYALARI.append("yok.onnx")
try:
    blok.kisi({}, kare, blok.DENEME_KOD, -1)
    d = json.loads(sonuc_yolu.read_text(encoding="utf-8"))
    denetle("tanımlı model dosyası yoksa deneme hata yazar", d["ok"] is False and "yok.onnx" in d["hata"])
finally:
    katalog.MODEL_DOSYALARI.remove("yok.onnx")
del os.environ[blok.ORTAM_DENEME_SONUC]

print("Yüz gizleme")
kayit = sys.modules["raf_motor.kayit"]
rng = np.random.default_rng(1)
ham = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)
bas = [40, 20, 80, 60]
gizli = kayit.yuzleri_gizle(ham.copy(), [bas], pay=0)
bolge, dis = gizli[20:60, 40:80], gizli.copy()
dis[20:60, 40:80] = ham[20:60, 40:80]
denetle("baş kutusu pikselleştirilir (az sayıda farklı renk), dışı değişmez",
        len(np.unique(bolge.reshape(-1, 3), axis=0)) <= kayit.PIKSEL * kayit.PIKSEL and np.array_equal(dis, ham))
kisiler = json.dumps({"sira": 1, "kisiler": [{"iz": 1, "b": [30, 10, 90, 118], "bas": bas}]})
(veri / "ayar" / "bos.json").write_text(json.dumps({"kod": "bos", "ad": "B", "kamera": {"tur": "dosya", "yol": "x.mp4"}}), encoding="utf-8")
st = {}  # bölgesiz kamera: baş kutusunun üstüne çizim düşmesin
cikis = blok.analiz(st, ham.copy(), kisiler, '{"sira": 1, "gozler": []}', "bos#k3", 0.0, False)
beklenen = kayit.yuzleri_gizle(ham.copy(), [bas])
denetle("Analiz'in verdiği görüntüde baş gizli", np.array_equal(cikis[0][20:60, 40:80], beklenen[20:60, 40:80])
        and not np.array_equal(cikis[0][20:60, 40:80], ham[20:60, 40:80]))
blok.kapat(st)

kalan = [ad for ad, ok in sonuc if not ok]
print(f"\n{len(sonuc) - len(kalan)}/{len(sonuc)} denetim geçti" + (f" · kalanlar: {kalan}" if kalan else ""))
time.sleep(0.1)
shutil.rmtree(gecici, ignore_errors=True)
sys.exit(1 if kalan else 0)
