"""Panelin HTTP yollarını, geliştirme kipini, örnek veriyi ve tek seferlik motor işlerinin panel tarafını sınar.

  python egitim/dene_panel_api.py

AugeLab Studio çalıştırılmaz: geliştirme kipi açıktır (RAF_GELISTIRME=1), motor işi sahte bir Studio süreciyle sınanır.
Veri klasörü geçicidir. Denetlenenler:
  - bütün yeni GET yolları ve /api/v1 aynaları 200 döner; dışa aktarma (CSV, Excel) dosya verir
  - yalnızca bu bilgisayar: yanlış Host / Origin ile istek reddedilir (403); /api/v1 anahtarsız dışarıdan açılmaz
  - geliştirme kipinde analiz, Studio denemesi ve motor işleri "kullanılamıyor" (409) döner
  - ayar, ürün, görev girdisinde sunucu doğrulaması (400 + Türkçe ileti, hiçbir şey yazılmaz)
  - ürün görseli: yüklenen fotoğraftan ve kameranın karesinden (yalnızca raf bölgesi içinden) kırpılır
  - "Rafı dolu olarak kaydet": yalnızca yüzleri gizlenmiş son kareden; referans zamanı ayara yazılır
  - örnek veri yüklenir ve kaldırılır; gerçek kamera, ürün ve kayıtlar kaldırmadan etkilenmez
  - motor işi (gozler / etiketler / urun_tani): girdi dosyası sözleşmedeki biçimde yazılır, sonuç okunur, hata ve süre aşımı Türkçe
"""
import base64
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
kok = Path(__file__).resolve().parent.parent
VERI = Path(tempfile.mkdtemp(prefix="raf_dene_api_"))
os.environ["RAF_KAMERA_VERI"] = str(VERI)
os.environ["RAF_GELISTIRME"] = "1"
sys.path.insert(0, str(kok))
sys.path.insert(0, str(kok / "egitim"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import yollar  # noqa: E402

yollar.hazirla()
import depo  # noqa: E402
import kuyruk  # noqa: E402
import uygulama  # noqa: E402

depo.vt()
sonuc: list[tuple[str, bool]] = []


def kontrol(ad: str, kosul: bool, ayrinti="") -> None:
    sonuc.append((ad, bool(kosul)))
    print(("  ok  " if kosul else "  HATA ") + ad + ("" if kosul else f"  ({ayrinti})"))


kontrol("geliştirme kipi açık", uygulama.GELISTIRME is True)
kontrol("geliştirme kipinde Studio yoklanmaz", uygulama.studio_durumu().get("gelistirme") is True)

sunucu = uygulama.Sunucu(("127.0.0.1", 0), uygulama.Istek)
PORT = sunucu.server_address[1]
threading.Thread(target=sunucu.serve_forever, daemon=True).start()
TABAN = f"http://127.0.0.1:{PORT}"


def istek(yol: str, govde=None, basliklar=None):
    veri = json.dumps(govde).encode() if govde is not None else None
    r = urllib.request.Request(TABAN + yol, data=veri, headers={"Content-Type": "application/json", **(basliklar or {})}, method="POST" if govde is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=120) as y:
            ham = y.read()
            return y.status, (json.loads(ham) if y.headers.get("Content-Type", "").startswith("application/json") else ham), y.headers
    except urllib.error.HTTPError as e:
        ham = e.read()
        try:
            return e.code, json.loads(ham), e.headers
        except ValueError:
            return e.code, ham, e.headers


# --- gerçek kayıtlar (kaldırma bunlara dokunmamalı)
kod, _ = istek("/api/urun", {"ad": "Gerçek ürün", "fiyat": "5,5"})[0], None
gercek_urun = istek("/api/urun", {"ad": "Gerçek ürün 2"})[1]["urun"]
st, y, _ = istek("/api/ayar", {"ayar": {"kod": "gercek1", "ad": "Gerçek kamera", "kamera": {"tur": "dosya", "yol": "x.mp4"},
                                        "bolgeler": [{"tur": "raf", "ad": "Raf", "poly": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                                                      "gozler": [{"kutu": [0.2, 0.2, 0.4, 0.5], "urun": gercek_urun["kimlik"], "adet": 2}]}]}, "yeni": True})
kontrol("POST /api/ayar yeni kamera", st == 200 and y.get("kod") == "gercek1", y)
st, y, _ = istek("/api/ayar", {"ayar": {"kod": "gercek1", "kamera": {"tur": "dosya"}, "bolgeler": [{"tur": "raf", "poly": [[0, 0], [1, 0]]}]}})
kontrol("POST /api/ayar hatalı bölge: 400 + Türkçe ileti", st == 400 and "köşe" in y.get("hata", ""), y)
kontrol("hatalı ayar dosyayı değiştirmedi", len(json.loads((yollar.AYAR / "gercek1.json").read_text(encoding="utf-8"))["bolgeler"][0]["gozler"]) == 1)
st, y, _ = istek("/api/ayar", {"ayar": {"kod": "ornek-sahte", "kamera": {"tur": "dosya"}}, "yeni": True})
kontrol("örnek önekli gerçek kamera reddedilir", st == 400 and "örnek" in y.get("hata", ""), y)
depo.ekle("olay", {"kimlik": "gercek-o", "zaman": depo.simdi(), "kamera": "gercek1", "kamera_ad": "Gerçek kamera", "kural": "bos_raf", "kural_ad": "Boş raf",
                   "kategori": "raf", "duzey": "yuksek", "onem": 3, "olasilik": 3, "puan": 9, "ciddi": 0, "sure_sn": 30, "suruyor": 0})
depo.ekle("olcum", {"kamera": "gercek1", "kamera_ad": "Gerçek kamera", "bas": depo.simdi(), "sure_sn": 30, "analiz": 90, "veri": {"gecen": 3}})
st, y, _ = istek("/api/gorev", {"baslik": "Gerçek görev", "kamera": "gercek1"})
gercek_gorev = y["id"]
st, y, _ = istek("/api/gorev", {"baslik": ""})
kontrol("POST /api/gorev boş başlık: 400", st == 400 and "başlığı" in y["hata"])
st, y, _ = istek("/api/gorev", {"baslik": "X", "son_tarih": "31.12.2026"})
kontrol("POST /api/gorev hatalı tarih: 400", st == 400 and "tarih" in y["hata"])
st, y, _ = istek("/api/gorev", {"id": gercek_gorev, "baslik": "Gerçek görev", "durum": "suruyor", "sorumlu": "Reyon 1"})
g = depo.sor("SELECT * FROM gorev WHERE id = ?", gercek_gorev)[0]
kontrol("görev başlatılınca başlama zamanı yazılır", st == 200 and g["baslama"] and g["sorumlu"] == "Reyon 1")
st, y, _ = istek("/api/gorev", {"id": gercek_gorev, "baslik": "Gerçek görev", "durum": "kapandi"})
g = depo.sor("SELECT * FROM gorev WHERE id = ?", gercek_gorev)[0]
kontrol("görev kapatılınca tepki süresi yazılır", g["durum"] == "kapandi" and g["tepki_sn"] is not None)
st, y, _ = istek("/api/genel", {"calisma": {"bas": "25:00", "bit": "22:00"}})
kontrol("POST /api/genel hatalı çalışma saati: 400", st == 400)
st, y, _ = istek("/api/genel", {"saklama_gun": 10, "klip_gun": 20})
kontrol("POST /api/genel klip süresi kayıt süresinden uzun olamaz", st == 400)
st, y, _ = istek("/api/genel", {"tesis": "Deneme Mağaza", "calisma": {"bas": "07:00", "bit": "23:00"}, "saklama_gun": 60, "klip_gun": 14})
kontrol("POST /api/genel geçerli ayarlar", st == 200 and y["genel"]["calisma"] == {"bas": "07:00", "bit": "23:00"} and y["genel"]["saklama_gun"] == 60)
st, y, _ = istek("/api/olay/durum", {"id": "abc", "durum": "cozuldu"})
kontrol("bozuk sayı: 400, sunucu düşmez", st == 400)

# --- ürün görseli
img = np.full((200, 300, 3), 200, np.uint8)
cv2.rectangle(img, (100, 50), (200, 150), (40, 90, 200), -1)
veri = "data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", img)[1].tobytes()).decode()
st, y, _ = istek("/api/urun/gorsel", {"kimlik": gercek_urun["kimlik"], "kaynak": "dosya", "veri": veri, "kutu": [0.3, 0.2, 0.7, 0.8]})
kontrol("ürün görseli: fotoğraftan kırpıldı", st == 200 and y["urun"]["gorseller"] == [f"{gercek_urun['kimlik']}_1.jpg"], y)
kirp = cv2.imread(str(depo.gorsel_klasoru() / f"{gercek_urun['kimlik']}_1.jpg"))
kontrol("ürün görseli: kırpılan boyut (120×120)", kirp is not None and kirp.shape[:2] == (120, 120), getattr(kirp, "shape", None))
st, y, _ = istek("/api/urun/gorsel", {"kimlik": gercek_urun["kimlik"], "kaynak": "dosya", "veri": "data:image/jpeg;base64,AAAA"})
kontrol("ürün görseli: bozuk dosya 400", st == 400)
(yollar.AYAR / "_kare_gercek1.jpg").write_bytes(cv2.imencode(".jpg", np.zeros((180, 320, 3), np.uint8))[1].tobytes())
st, y, _ = istek("/api/urun/gorsel", {"kimlik": gercek_urun["kimlik"], "kaynak": "kamera", "kod": "gercek1", "kutu": [0.0, 0.92, 0.05, 0.99]})
kontrol("ürün görseli: raf bölgesi dışından kırpılmaz", st == 400 and "raf" in y["hata"], y)
st, y, _ = istek("/api/urun/gorsel", {"kimlik": gercek_urun["kimlik"], "kaynak": "kamera", "kod": "gercek1", "kutu": [0.3, 0.3, 0.5, 0.6]})
kontrol("ürün görseli: raf bölgesi içinden kameradan kırpıldı", st == 200 and len(y["urun"]["gorseller"]) == 2, y)
st, y, h = istek("/urunler/gorsel/" + y["urun"]["gorseller"][0])
kontrol("GET ürün görseli", st == 200 and h["Content-Type"] == "image/jpeg")
kontrol("GET ürün görseli: yol dışına çıkılmaz", istek("/urunler/gorsel/..%5Curunler.json")[0] == 404)

# --- referans kare
st, y, _ = istek("/api/ayar/referans", {"kod": "gercek1"})
kontrol("referans: temiz kare yokken reddedilir (ham bağlantı karesi kullanılmaz)", st == 400 and "temiz karesi" in y["hata"], y)
(yollar.CIKTI / "gercek1").mkdir(parents=True, exist_ok=True)
SON = cv2.imencode(".jpg", np.full((180, 320, 3), 90, np.uint8))[1].tobytes()
TEMIZ = cv2.imencode(".jpg", np.full((180, 320, 3), 160, np.uint8))[1].tobytes()
(yollar.CIKTI / "gercek1" / "son_kare.jpg").write_bytes(SON)
st, y, _ = istek("/api/ayar/referans", {"kod": "gercek1"})
kontrol("referans: çizimli son_kare referans olamaz", st == 400 and not (yollar.AYAR / "_referans_gercek1.jpg").exists(), y)
import rapor  # noqa: E402

kontrol("raf arka planı: temiz kare yokken son kare (yüzler gizli)", rapor._kare_adresi("gercek1").startswith("/cikti/gercek1/son_kare.jpg"))
(yollar.CIKTI / "gercek1" / "temiz_kare.jpg").write_bytes(TEMIZ)
st, y, _ = istek("/api/ayar/referans", {"kod": "gercek1"})
a = json.loads((yollar.AYAR / "gercek1.json").read_text(encoding="utf-8"))
kontrol("referans: temiz kareden kaydedildi ve ayara yazıldı", st == 200 and (yollar.AYAR / "_referans_gercek1.jpg").read_bytes() == TEMIZ and a["referans"]["zaman"] == y["referans"]["zaman"])
kontrol("raf arka planı ve düzenleyici: temiz kare önce", rapor._kare_adresi("gercek1").startswith("/cikti/gercek1/temiz_kare.jpg")
        and next(k for k in rapor.kameralar() if k["kod"] == "gercek1")["temiz_kare"].startswith("/cikti/gercek1/temiz_kare.jpg"))
kontrol("motor işi ve kırpma karesi: temiz kare, son_kare değil", uygulama._kamera_karesi("gercek1", ham_izinli=True).name == "temiz_kare.jpg")
kontrol("GET /ayar/_referans_<kod>.jpg", istek("/ayar/_referans_gercek1.jpg")[0] == 200)
kontrol("referans: motorun kişi kutuları yokken eski kutu dosyası kalmaz", not (yollar.AYAR / "_referans_gercek1.json").exists())
(yollar.CIKTI / "gercek1" / "temiz_kare.json").write_text('{"kisiler": [[0.1, 0.2, 0.3, 0.9]]}', encoding="utf-8")
st, y, _ = istek("/api/ayar/referans", {"kod": "gercek1"})
kontrol("referans: o karedeki kişi kutuları da saklanır (koridor referansı bunların altını öğrenir)", st == 200
        and json.loads((yollar.AYAR / "_referans_gercek1.json").read_text(encoding="utf-8")) == {"kisiler": [[0.1, 0.2, 0.3, 0.9]]})

# --- geliştirme kipi: Studio ve motor kapalı
for yol, govde in (("/api/studio/dene", {}), ("/api/studio/kur", {}), ("/api/is/izle", {"kod": "gercek1"}), ("/api/is/video", {"kod": "gercek1"}),
                   ("/api/motor/gozler", {"kod": "gercek1"})):
    st, y, _ = istek(yol, govde)
    kontrol(f"geliştirme kipi: {yol} → 409 motor yok", st == 409 and y.get("motor_yok") is True and "kullanılamıyor" in y["hata"], (st, y))

# --- örnek veri: yükle (2 gün) ve kaldır
import ornek_veri  # noqa: E402  (ince sarmalayıcı: asıl kod ornek_uretici.py)

kontrol("örnek veri üreticisi programla paketlenen modülde", ornek_veri.yukle.__module__ == "ornek_uretici")

ozet = ornek_veri.yukle(yaz=lambda s: None, gun=2)
ov = uygulama.ornek_veri_durumu()
kontrol("örnek veri: yüklendi (4 kamera, uyarı, ölçüm, görev)", ov["yuklu"] and len(ov["kameralar"]) == 4 and ozet["olay"] > 0 and ozet["olcum"] > 0 and ozet["gorev"] > 0, ozet)
kontrol("örnek veri: bütün satırlar örnek işaretli", depo.sor("SELECT COUNT(*) AS n FROM olay WHERE kamera LIKE 'ornek-%' AND ornek = 0")[0]["n"] == 0
        and depo.sor("SELECT COUNT(*) AS n FROM etkilesim WHERE ornek = 1")[0]["n"] > 0)
kontrol("örnek veri: kuyruk boşaldı", not list(kuyruk.KLASOR.glob("*.json")))
kontrol("örnek veri: ürünler örnek işaretli, görselleri var", sum(1 for u in depo.urunler() if u.get("ornek") and u.get("gorseller")) == len(ornek_veri.URUNLER))
kontrol("örnek veri: tutarlılık (raf kameralarında alan = aldı etkileşimi)",
        depo.sor("SELECT COUNT(*) AS n FROM etkilesim WHERE eylem = 'aldi' AND ornek = 1")[0]["n"]
        == sum(json.loads(r["veri"]).get("alan", 0) for r in depo.sor("SELECT veri FROM olcum WHERE kamera IN ('ornek-raf1', 'ornek-raf2')")))
st, y, _ = istek("/api/ornek-veri/yukle", {})
kontrol("örnek veri: yüklüyken yeniden yüklenmez", st == 409)
# bütün ekran yolları (örnek veriyle)
d7 = "gun=7"
for yol in ("/api/durum", "/api/katalog", f"/api/genel-bakis?{d7}", f"/api/raflar?{d7}", f"/api/raflar?{d7}&kamera=ornek-raf2", f"/api/urunler?{d7}",
            f"/api/musteri?{d7}", f"/api/musteri?{d7}&kamera=ornek-koridor", f"/api/gorevler?{d7}", f"/api/olaylar?{d7}", f"/api/rapor-ozeti?{d7}",
            "/api/ara?q=s%C3%BCt", "/api/ornek-veri", f"/api/goz?{d7}&kamera=ornek-raf1&goz=g1", "/api/v1", f"/api/v1/genel-bakis?{d7}", f"/api/v1/raflar?{d7}",
            f"/api/v1/urunler?{d7}", f"/api/v1/musteri?{d7}", "/api/v1/kameralar", "/api/v1/gorevler", "/api/rapor?gun=30", "/api/analitik?gun=7&kamera=ornek-koridor",
            "/bas=2026-01-01"):
    st, y, _ = istek(yol)
    if yol == "/bas=2026-01-01":
        kontrol("bilinmeyen yol 404", st == 404)
        continue
    kontrol(f"GET {yol.split('?')[0]} 200", st == 200 and not (isinstance(y, dict) and y.get("hata")), (st, str(y)[:200]))
st, y, _ = istek("/api/genel-bakis?bas=2026-13-01&bit=2026-01-01")
kontrol("hatalı tarih: 400 + Türkçe ileti", st == 400 and "Tarih" in y["hata"])
d = istek(f"/api/raflar?{d7}&kamera=ornek-raf2")[1]
kontrol("raflar: örnek kamerada gözler, durum ve doluluk", sum(len(b.get("gozler") or []) for b in d["bolgeler"]) == 23 and d["doluluk"] is not None)
kontrol("arama: ürün ve göz bulunur", {s["tur"] for s in istek("/api/ara?q=s%C3%BCt")[1]["sonuclar"]} >= {"urun", "goz"})
# saatlik ziyaretçi: bugünün satırı olmayan dönemde (dün) "bugün" boş, dönem ortalaması dolu gelir; grafik ortalamayı çizmeli
dun = (dt.date.today() - dt.timedelta(days=1)).isoformat()
tr = istek(f"/api/genel-bakis?bas={dun}&bit={dun}")[1]["trafik"]
kontrol("genel bakış: dünün saatlik ortalaması dolu, bugün sütunu boş", sum(x["ort"] for x in tr["saatlik"]) > 0 and not any(x["bugun"] for x in tr["saatlik"]),
        tr["saatlik"])
import shutil  # noqa: E402
import subprocess  # noqa: E402

if shutil.which("node"):
    # grafik.js'in sütun grafiği: sütunlar sıfırken çizgi (dönem ortalaması) varsa "veri yok" yazmaz, çizgiyi çizer
    betik = ("globalThis.window={addEventListener(){}};" + (kok / "web" / "grafik.js").read_text(encoding="utf-8")
             + ";const ort=" + json.dumps([x["ort"] for x in tr["saatlik"]]) + ";"
             "const ciz=(o)=>G.sutun({etiketler:ort.map((_,i)=>i+':00'),seriler:[{ad:'Bugün',degerler:ort.map(()=>0)}],...o})(600);"
             "process.stdout.write(JSON.stringify([ciz({cizgi:{ad:'Dönem ortalaması',degerler:ort}}),ciz({cizgi:null})]))")
    cizim = json.loads(subprocess.run(["node", "-e", betik], capture_output=True, text=True, encoding="utf-8", timeout=60).stdout or "[\"\",\"\"]")
    kontrol("saatlik grafik: bugün boşken dönem ortalaması çizilir", "<polyline" in cizim[0] and "veri yok" not in cizim[0], cizim[0][:200])
    kontrol("saatlik grafik: çizgi de yoksa 'Bu dönemde veri yok'", "Bu dönemde veri yok" in cizim[1], cizim[1][:200])
else:
    print("  (node yok: grafik.js denemesi atlandı)")
# tarayıcıya kullanıcı profili yolu gitmez
st, y, _ = istek("/api/durum")
ev = str(Path.home())
kontrol("/api/durum veri klasörü yolunu göndermez", st == 200 and "veri" not in y, sorted(y)[:40])
kontrol("/api/durum yanıtında kullanıcı profili yolu yok", ev.lower() not in json.dumps(y, ensure_ascii=False).lower().replace("\\\\", "\\"),
        [k for k, v in y.items() if ev.lower() in json.dumps(v, ensure_ascii=False).lower().replace("\\\\", "\\")])
yerel = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
kontrol("gizle: %LOCALAPPDATA% kısaltması", yollar.gizle(str(Path(yerel) / "RafKamera" / "studio" / "k.log")) == r"%LOCALAPPDATA%\RafKamera\studio\k.log",
        yollar.gizle(str(Path(yerel) / "RafKamera")))
kontrol("gizle: profil (büyük/küçük harf ve / ile)", yollar.gizle(ev.upper().replace("\\", "/") + "/Belgeler/x.mp4") == "%USERPROFILE%/Belgeler/x.mp4"
        and yollar.gizle("ayrıntı: " + ev + "\\Desktop") == "ayrıntı: %USERPROFILE%\\Desktop", yollar.gizle(ev + "\\Desktop"))
kontrol("gizle: benzer adlı başka klasöre dokunmaz", yollar.gizle(ev + "x\\a") == ev + "x\\a")
is_ = uygulama.Is("deneme", "Deneme")
is_.ekle(f"Hata: günlük {VERI / 'studio' / 'k.log'}\n")
is_.sonuc = {"hata": f"bkz. {VERI}"}
oz = json.dumps(is_.ozet(), ensure_ascii=False)
kontrol("iş kaydı ve sonucu ekrana kısaltılmış yolla gider", ev.lower() not in oz.lower().replace("\\\\", "\\") and "%" in oz, oz[:300])
for ad in ("tukenmeler", "gorevler", "kayip-satis", "trafik", "olaylar"):
    st, ham, h = istek(f"/api/disa/{ad}.csv?{d7}")
    kontrol(f"dışa aktarma CSV {ad}", st == 200 and h["Content-Type"].startswith("text/csv") and ham.startswith("﻿".encode()) and b";" in ham)
st, ham, h = istek(f"/api/disa/hepsi.xlsx?{d7}")
kontrol("dışa aktarma Excel (bütün tablolar)", st == 200 and ham[:2] == b"PK" and "attachment" in h.get("Content-Disposition", ""))
st, ham, h = istek(f"/api/v1/disa/kayip-satis.csv?{d7}")
kontrol("GET /api/v1/disa/<tablo>.csv", st == 200 and h["Content-Type"].startswith("text/csv"))
# yalnızca bu bilgisayar
st, _, _ = istek("/api/durum", basliklar={"Host": "kotu.ornek"})
kontrol("yanlış Host: 403", st == 403)
st, _, _ = istek("/api/urun", {"ad": "Kötü"}, basliklar={"Origin": "http://kotu.ornek"})
kontrol("yanlış Origin ile POST: 403", st == 403)
st, _, _ = istek("/api/v1/raflar", basliklar={"Host": "kotu.ornek"})
kontrol("/api/v1 anahtarsız dışarıdan: 403", st == 403)
st, _, _ = istek("/api/disa/olaylar.csv", basliklar={"Host": "kotu.ornek"})
kontrol("dışa aktarma dışarıdan: 403", st == 403)
# çıkışlara örnek olay gönderilmez
import baglanti  # noqa: E402

gonderilen = []
baglanti.gonder = lambda ids: gonderilen.extend(ids) or []
uygulama._bildir([r["id"] for r in depo.sor("SELECT id FROM olay WHERE ornek = 1 LIMIT 5")] + [depo.sor("SELECT id FROM olay WHERE kimlik = 'gercek-o'")[0]["id"]])
kontrol("örnek olaylar çıkışlara gönderilmez, gerçekler gönderilir", gonderilen == [depo.sor("SELECT id FROM olay WHERE kimlik = 'gercek-o'")[0]["id"]], gonderilen)
# kaldır
gercek_once = {t: depo.sor(f"SELECT COUNT(*) AS n FROM {t} WHERE ornek = 0")[0]["n"] for t in ("olay", "olcum", "gorev")}
st, y, _ = istek("/api/ornek-veri/kaldir", {})
kontrol("örnek veri: kaldırıldı", st == 200 and len(y["kameralar"]) == 4 and y["urunler"] == len(ornek_veri.URUNLER), y)
kontrol("örnek veri: örnek satır kalmadı", not any(depo.ornek_sayilari().values()), depo.ornek_sayilari())
kontrol("örnek veri: gerçek satırlar aynen duruyor", gercek_once == {t: depo.sor(f"SELECT COUNT(*) AS n FROM {t} WHERE ornek = 0")[0]["n"] for t in ("olay", "olcum", "gorev")})
kontrol("örnek veri: gerçek kamera ve ürünler duruyor", (yollar.AYAR / "gercek1.json").is_file() and {u["ad"] for u in depo.urunler()} == {"Gerçek ürün", "Gerçek ürün 2"}
        and (depo.gorsel_klasoru() / f"{gercek_urun['kimlik']}_1.jpg").is_file())
kontrol("örnek veri: örnek ayar, kare ve görseller silindi", not list(yollar.AYAR.glob("ornek-*")) and not list(yollar.AYAR.glob("_referans_ornek-*"))
        and not list(yollar.CIKTI.glob("ornek-*")) and not any(p.name.startswith("u") and p.name not in {f"{gercek_urun['kimlik']}_1.jpg", f"{gercek_urun['kimlik']}_2.jpg"} for p in depo.gorsel_klasoru().iterdir()))
kontrol("örnek veri: mağaza adı geri alındı", depo.genel()["tesis"] == "Deneme Mağaza")

# --- motor işi (panel tarafı) sahte Studio süreciyle
import studio  # noqa: E402


class SahteSurec:
    def __init__(self, davranis):
        self.davranis = davranis

    def wait(self, sn):
        if self.davranis == "takil":
            import subprocess
            raise subprocess.TimeoutExpired("studio", sn)


class SahteKosu:
    def __init__(self, davranis):
        self.surec = SahteSurec(davranis)
        self.bitti = False

    def bitir(self, bekle=0):
        self.bitti = True

    def sorun(self):
        return "çıkış kodu 1"


GORULEN = {}


def sahte_baslat(davranis):
    def baslat(kod, kosu, adres="", canli=False, adim=None, ek_ortam=None):
        GORULEN.update(kod=kod, adim=adim, ortam=dict(ek_ortam or {}))
        girdi = json.loads(Path(ek_ortam["RAF_GOREV_GIRDI"]).read_text(encoding="utf-8"))
        GORULEN["girdi"] = girdi
        cikti = Path(ek_ortam["RAF_GOREV_CIKTI"])
        if davranis == "gozler":
            cikti.write_text(json.dumps({"gozler": [{"bolge": "b1", "kutu": [0.2, 0.2, 0.3, 0.4], "skor": 0.8, "etiket": None}, {"bolge": "b1", "kutu": [9, 9, 9, 9]}]}), encoding="utf-8")
        elif davranis == "etiketler":
            cikti.write_text(json.dumps({"etiketler": [{"kutu": k, "metin": "12,50 TL", "fiyat": 12.5} for k in girdi["kutular"]]}), encoding="utf-8")
        elif davranis == "hata":
            cikti.write_text(json.dumps({"hata": "model yok"}), encoding="utf-8")
        return SahteKosu(davranis)
    return baslat


is_ = uygulama.Is("motor", "deneme")
studio.baslat = sahte_baslat("gozler")
s = uygulama.is_motor(is_, "gozler", "gercek1", uygulama._motor_girdisi("gozler", "gercek1", {}))
kontrol("motor işi: kamera kodu _gorev, --step 3, ortam değişkenleri", GORULEN["kod"] == "_gorev" and GORULEN["adim"] == 3
        and set(GORULEN["ortam"]) == {"RAF_GOREV", "RAF_GOREV_GIRDI", "RAF_GOREV_CIKTI"} and GORULEN["ortam"]["RAF_GOREV"] == "gozler")
kontrol("motor işi: girdi sözleşmedeki biçimde (kare + raf bölgeleri)", Path(GORULEN["girdi"]["kare"]).name == "temiz_kare.jpg" and GORULEN["girdi"]["bolgeler"][0]["kimlik"] == "b1"
        and set(GORULEN["girdi"]["bolgeler"][0]) == {"kimlik", "poly"})
kontrol("motor işi: sonuç okundu, bozuk kutu ayıklandı", s["gozler"] == [{"bolge": "b1", "kutu": [0.2, 0.2, 0.3, 0.4], "skor": 0.8, "etiket": None}], s)
studio.baslat = sahte_baslat("etiketler")
s = uygulama.is_motor(is_, "etiketler", "gercek1", {"kutular": [[0.1, 0.1, 0.2, 0.15]]})
kontrol("motor işi: etiket okuma sonucu", s["etiketler"][0]["fiyat"] == 12.5 and GORULEN["girdi"]["kutular"] == [[0.1, 0.1, 0.2, 0.15]])
for davranis, beklenen in (("hata", "model yok"), ("bos", "sonuç bırakmadı"), ("takil", "saniyede bitirmedi")):
    studio.baslat = sahte_baslat(davranis)
    try:
        uygulama.is_motor(is_, "urun_tani", "gercek1", {"kutular": [[0.1, 0.1, 0.2, 0.2]]}, sinir_sn=1)
        kontrol(f"motor işi: {davranis} → Türkçe hata", False, "hata yükselmedi")
    except SystemExit as e:
        kontrol(f"motor işi: {davranis} → Türkçe hata", beklenen in str(e.code), e.code)
try:
    uygulama._motor_girdisi("etiketler", "gercek1", {})
    kontrol("motor işi: etiket kutusu yokken Türkçe hata", False)
except uygulama.AyarHatasi as e:
    kontrol("motor işi: etiket kutusu yokken Türkçe hata", "etiket" in str(e))

sunucu.shutdown()
basarili = sum(1 for _, ok in sonuc if ok)
print(f"\n{basarili}/{len(sonuc)} denetim geçti.")
sys.exit(0 if basarili == len(sonuc) else 1)
