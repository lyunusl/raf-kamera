"""AugeLab Studio'daki motorun bıraktığı kayıtları (veri/kuyruk/*.json) veritabanına alır.

Kayıt türleri:
  olay    bir olay başladı ya da sürüyor (bitti = false) ya da kapandı (bitti = true); aynı `kimlik` ile gelir
  olcum   bir zaman diliminin sayıları: veri {ad: sayı} ve isteğe bağlı ısı haritası (izgara)
  raf     göz durumları (doluluk, ürün, etiket, fiyat): göz geçmişi yalnızca değişiklikte yazılır
  etkilesim  müşteri-raf etkileşimi (durdu / uzandı / aldı / bıraktı), kimliksiz
  nabiz   sahne çalışıyor (yalnızca son kayıt anını yeniler)
  hata    Studio'daki tespit çalışmıyor
  bitti   akış bitti
Klipler motor tarafından ham (mp4v) yazılır; burada tarayıcıda oynayan H.264'e çevrilir.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import depo
import yollar

_GIZLI = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
KLASOR = yollar.VERI / "kuyruk"
# Koşuya göre ayrı tutulur: aynı kamerada önceki koşudan geç gelen bir kayıt, güncel koşunun kaydının üstüne yazılmaz.
BITENLER: dict[str, dict[str, float]] = {}  # kamera → {koşu numarası: akışının bittiği an}
SON_KAYIT: dict[str, float] = {}            # kamera → son kayıt alınan an
HATALAR: dict[str, dict[str, str]] = {}     # kamera → {koşu numarası: neden}: Studio'daki tespit çalışmıyor
_KILIT = threading.Lock()


def _klibi_cevir(goreli: str | None) -> str | None:
    """cikti/ altındaki ham klibi H.264'e çevirir; yeni göreli yolu döndürür."""
    if not goreli:
        return None
    ham = yollar.CIKTI / goreli
    if not goreli.endswith(".ham.mp4"):
        return goreli if ham.exists() else None
    hedef = ham.with_name(ham.name[:-len(".ham.mp4")] + ".mp4")
    if not ham.exists():
        return None
    try:
        subprocess.run([yollar.ffmpeg(), "-y", "-loglevel", "error", "-i", str(ham), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
                        "-movflags", "+faststart", str(hedef)], check=True, stdin=subprocess.DEVNULL, timeout=120, **_GIZLI)
    except Exception:
        return None
    ham.unlink(missing_ok=True)
    return str(hedef.relative_to(yollar.CIKTI)).replace("\\", "/")


GOZ_DURUMLARI = ("dolu", "az", "bos", "yanlis", "kapali", "bilinmiyor")
ETIKET_DURUMLARI = ("uygun", "farkli", "yok", "okunamadi", "bakilmadi")
EYLEMLER = ("durdu", "uzandi", "aldi", "birakti")
_AYARLAR: dict[str, tuple[float, dict]] = {}  # kamera → (dosya zamanı, ayar): bölge adları için


def _ayar(kamera: str) -> dict:
    yol = yollar.AYAR / f"{kamera}.json"
    try:
        z = yol.stat().st_mtime
    except OSError:
        return {}
    var = _AYARLAR.get(kamera)
    if var and var[0] == z:
        return var[1]
    try:
        a = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        a = {}
    _AYARLAR[kamera] = (z, a if isinstance(a, dict) else {})
    return _AYARLAR[kamera][1]


def _bolge_adi(kamera: str, kimlik) -> str | None:
    if not kimlik:
        return None
    for b in _ayar(kamera).get("bolgeler") or []:
        if b.get("kimlik") == kimlik:
            return b.get("ad") or kimlik
    return None


def _sayi(v, varsayilan=None):
    try:
        return float(v) if v is not None and v != "" else varsayilan
    except (TypeError, ValueError):
        return varsayilan


def _olay_bitti_saati(zaman: str, sure_sn: float) -> str:
    try:
        return (dt.datetime.fromisoformat(zaman) + dt.timedelta(seconds=float(sure_sn or 0))).replace(microsecond=0).isoformat()
    except ValueError:
        return depo.simdi()


def _gorev_ac(olay_id: int, k: dict, bolge_ad: str | None, ornek: bool) -> None:
    """Görev açan olay başladı: personel görevi kendiliğinden açılır ve olaya bağlanır."""
    baslik = k.get("kural_ad") or k["kural"]
    if k.get("urun_ad"):
        baslik += f" · {k['urun_ad']}"
    elif bolge_ad:
        baslik += f" · {bolge_ad}"
    aciklama = " · ".join(x for x in (k.get("kamera_ad") or k["kamera"], bolge_ad, (k.get("aciklama") or "").strip()) if x)
    gid = depo.ekle("gorev", {
        "baslik": baslik[:200], "aciklama": aciklama[:4000], "sorumlu": "", "son_tarih": None, "durum": "acik",
        "kamera": k["kamera"], "kural": k["kural"], "bolge": bolge_ad, "goz": k.get("goz"), "urun": k.get("urun"),
        "olusturma": k["zaman"], "kapanma": None, "olay": olay_id, "otomatik": 1, "ornek": int(ornek),
    })
    depo.yaz("INSERT OR IGNORE INTO gorev_olay (gorev, olay) VALUES (?, ?)", gid, olay_id)


def _gorevleri_kapat(olay_id: int, bitis: str) -> None:
    """Olay kapandı (raf dolduruldu, kuyruk eridi...): olayın açtığı görev kendiliğinden kapanır, tepki süresi yazılır."""
    for g in depo.sor("SELECT id, olusturma FROM gorev WHERE olay = ? AND otomatik = 1 AND durum != 'kapandi'", olay_id):
        try:
            tepki = max(0.0, (dt.datetime.fromisoformat(bitis) - dt.datetime.fromisoformat(g["olusturma"])).total_seconds())
        except ValueError:
            tepki = None
        depo.yaz("UPDATE gorev SET durum = 'kapandi', kapanma = ?, tepki_sn = ? WHERE id = ?", bitis, tepki, g["id"])


def _olay(k: dict, ornek: bool) -> int | None:
    """Olayı ekler ya da günceller. Yeni eklenen olayın numarasını döndürür. Klip, olay sürerken de gelebilir (klip
    dolduğunda); geldiği anda dönüştürülür. `gorev` işaretli (ya da katalogda görev açan) olay başlarken görev açılır,
    olay kapanınca görev kendiliğinden kapanır."""
    import kurallar

    katalog = kurallar.KURAL.get(k.get("kural"), {})
    klip = _klibi_cevir(k.get("klip"))
    bitti = bool(k.get("bitti"))
    sure_sn = _sayi(k.get("sure_sn"), 0.0)
    var = depo.sor("SELECT id, zaman, suruyor, durum FROM olay WHERE kimlik = ?", k["kimlik"])
    if var:
        o = var[0]
        bitis = _olay_bitti_saati(o["zaman"], sure_sn) if bitti else None
        depo.yaz("UPDATE olay SET sure_sn = ?, olasilik = COALESCE(?, olasilik), puan = COALESCE(?, puan), x = COALESCE(?, x), y = COALESCE(?, y), "
                 "aciklama = COALESCE(?, aciklama), klip = COALESCE(?, klip), kare = COALESCE(?, kare), suruyor = ?, deger = COALESCE(?, deger), "
                 "bitis = COALESCE(?, bitis) WHERE id = ?",
                 sure_sn, k.get("olasilik"), k.get("puan"), k.get("x"), k.get("y"), k.get("aciklama"), klip, k.get("kare"), 0 if bitti else 1,
                 _sayi(k.get("deger")), bitis, o["id"])
        if bitti and o["suruyor"]:
            acik_gorev = depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE olay = ? AND otomatik = 1 AND durum != 'kapandi'", o["id"])[0]["n"]
            _gorevleri_kapat(o["id"], bitis)
            if acik_gorev and o["durum"] in ("acik", "ustlenildi"):  # durum kendiliğinden düzeldi
                depo.yaz("UPDATE olay SET durum = 'cozuldu', durum_zamani = ? WHERE id = ?", bitis, o["id"])
        return None
    bolge_ad = k.get("bolge_ad") or _bolge_adi(k["kamera"], k.get("bolge")) or k.get("bolge")
    duzey = k.get("duzey") or katalog.get("duzey") or "orta"
    onem = int(_sayi(k.get("onem"), katalog.get("onem", 2)))
    olasilik = int(_sayi(k.get("olasilik"), katalog.get("taban", 3)))
    gorev = k["gorev"] if "gorev" in k else bool(katalog.get("gorev"))
    beklenen = k.get("beklenen")
    oid = depo.ekle("olay", {
        "kimlik": k["kimlik"], "zaman": k["zaman"], "kamera": k["kamera"], "kamera_ad": k.get("kamera_ad") or k["kamera"], "kural": k["kural"],
        "kural_ad": k.get("kural_ad") or katalog.get("ad") or k["kural"], "kategori": k.get("kategori") or katalog.get("kategori") or "raf",
        "duzey": duzey, "bolge": bolge_ad, "bolge_kimlik": k.get("bolge"), "onem": onem, "olasilik": olasilik,
        "puan": int(_sayi(k.get("puan"), onem * olasilik)), "ciddi": int(bool(k.get("ciddi", duzey == "kritik"))), "sure_sn": sure_sn,
        "x": _sayi(k.get("x")), "y": _sayi(k.get("y")), "klip": klip, "kare": k.get("kare"), "aciklama": k.get("aciklama") or "",
        "ornek": int(ornek), "suruyor": 0 if bitti else 1, "goz": k.get("goz"), "urun": k.get("urun"), "urun_ad": k.get("urun_ad"),
        "gorev": int(bool(gorev)), "deger": _sayi(k.get("deger")), "beklenen": None if beklenen is None else str(beklenen),
        "bitis": _olay_bitti_saati(k["zaman"], sure_sn) if bitti else None,
    })
    if gorev:
        _gorev_ac(oid, k, bolge_ad, ornek)
        if bitti:  # başlangıcı ve sonu aynı kayıtta: görev hemen kapanır
            _gorevleri_kapat(oid, _olay_bitti_saati(k["zaman"], sure_sn))
    return oid


def _fiyat_farkli(a, b) -> bool:
    if a is None or b is None:
        return (a is None) != (b is None)
    return abs(float(a) - float(b)) > 0.009


def _raf(k: dict, ornek: bool) -> None:
    """Göz durumları: kamera özeti her kayıtta, göz geçmişi yalnızca durum / etiket / görülen ürün / fiyat değişince yazılır."""
    kamera, zaman = k["kamera"], str(k["zaman"])[:19]
    referans = k.get("referans") if k.get("referans") in ("gecici", "kayitli") else None
    depo.ekle("raf_ozet", {"kamera": kamera, "zaman": zaman, "doluluk": _sayi(k.get("doluluk")), "uyum": _sayi(k.get("uyum")),
                           "referans": referans, "ornek": int(ornek)})
    for g in k.get("gozler") or []:
        if not isinstance(g, dict) or not g.get("goz"):
            continue
        bolge, goz = str(g.get("bolge") or ""), str(g["goz"])
        yeni = {
            "durum": g.get("durum") if g.get("durum") in GOZ_DURUMLARI else "bilinmiyor",
            "doluluk": _sayi(g.get("doluluk")), "adet": int(_sayi(g.get("adet"), 0)) if g.get("adet") is not None else None,
            "urun": g.get("urun"), "gorulen": g.get("gorulen"), "benzerlik": _sayi(g.get("benzerlik")),
            "etiket": g.get("etiket") if g.get("etiket") in ETIKET_DURUMLARI else None, "fiyat": _sayi(g.get("fiyat")),
        }
        son = depo.sor("SELECT * FROM raf_son WHERE kamera = ? AND bolge = ? AND goz = ?", kamera, bolge, goz)
        son = son[0] if son else None
        if son is not None and son["zaman"] > zaman:
            continue  # geç gelen eski kayıt: son durumu ezmez
        degisti = son is None or any(son[a] != yeni[a] for a in ("durum", "etiket", "gorulen", "urun")) or _fiyat_farkli(son["fiyat"], yeni["fiyat"])
        if degisti:
            depo.ekle("raf_durum", {"kamera": kamera, "bolge": bolge, "goz": goz, "zaman": zaman, **yeni, "ornek": int(ornek)})
        degisim = zaman if son is None or son["durum"] != yeni["durum"] else son["degisim"]
        depo.yaz("INSERT OR REPLACE INTO raf_son (kamera, bolge, goz, zaman, degisim, durum, doluluk, adet, urun, gorulen, benzerlik, etiket, fiyat, ornek) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", kamera, bolge, goz, zaman, degisim, yeni["durum"], yeni["doluluk"], yeni["adet"],
                 yeni["urun"], yeni["gorulen"], yeni["benzerlik"], yeni["etiket"], yeni["fiyat"], int(ornek))


def _etkilesim(k: dict, ornek: bool) -> None:
    if k.get("eylem") not in EYLEMLER:
        return
    depo.ekle("etkilesim", {"kamera": k["kamera"], "zaman": str(k["zaman"])[:19], "bolge": k.get("bolge"), "goz": k.get("goz"),
                            "eylem": k["eylem"], "sure_sn": _sayi(k.get("sure_sn")), "ornek": int(ornek)})


def _ornek_mi(kamera: str) -> int:
    """Satırın `ornek` değeri: 2 = programla gelen örnek videonun gerçek analizi, 1 = örnek (demo) veri, 0 = gerçek kayıt.
    "Örnek verileri kaldır" yalnızca 1'leri siler; örnek video sonuçları kendi kamerasıyla yeniden çözümlenince silinir."""
    if kamera in yollar.ORNEK_ADLARI:
        return 2
    return 1 if depo.ornek_kamera(kamera) else 0


TOPLU = 400  # bir turda tek seferde kaydedilen en çok kayıt
_OKUNAMADI = object()
_OKUYUCU = ThreadPoolExecutor(max_workers=12, thread_name_prefix="kuyruk-oku")


def al() -> list[int]:
    """Kuyruktaki kayıtları sırayla içeri alır. Dönüş: yeni başlayan olayların numaraları (çıkışlara iletilmek üzere).
    Bozuk ya da eksik alanlı kayıt atlanır (diğerlerinin işlenmesini durdurmaz)."""
    yeni: list[int] = []
    if not KLASOR.is_dir():
        return yeni
    def oku(dosya):
        try:
            return json.loads(dosya.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _OKUNAMADI

    with _KILIT:
        dosyalar = sorted(KLASOR.glob("*.json"))
        for i in range(0, len(dosyalar), TOPLU):
            parca = dosyalar[i:i + TOPLU]
            # Dosyalar paralel okunur (Windows'ta yeni yazılmış dosyanın ilk okunuşu virüs taramasını bekler), sırayla işlenir.
            icerik = list(_OKUYUCU.map(oku, parca)) if len(parca) > 4 else [oku(d) for d in parca]
            islenen: list = []
            with depo.islem():
                for dosya, k in zip(parca, icerik):
                    if k is _OKUNAMADI:
                        continue  # yazımı sürüyor olabilir; bir sonraki turda
                    try:
                        if not isinstance(k, dict):
                            continue
                        kamera = str(k.get("kamera", ""))
                        ornek = _ornek_mi(kamera)
                        if not ornek:  # örnek veri yüklenirken gerçek kameraların "son kayıt" bilgisi değişmez
                            SON_KAYIT[kamera] = time.time()
                        tur = k.get("tur")
                        if tur == "olay":
                            kimlik = _olay(k, ornek)
                            if kimlik is not None:
                                yeni.append(kimlik)
                        elif tur == "olcum":
                            depo.ekle("olcum", {
                                "kamera": kamera, "kamera_ad": k.get("kamera_ad") or kamera, "bas": str(k["bas"])[:19], "sure_sn": k["sure_sn"],
                                "analiz": k.get("analiz") or 0, "veri": k.get("veri") or {}, "izgara": k.get("izgara"), "son_kare": k.get("son_kare"),
                                "ornek": int(ornek),
                            })
                        elif tur == "raf":
                            _raf(k, ornek)
                        elif tur == "etkilesim":
                            _etkilesim(k, ornek)
                        elif tur == "bitti":
                            BITENLER.setdefault(kamera, {})[str(k.get("kosu") or "")] = time.time()
                        elif tur == "hata":
                            HATALAR.setdefault(kamera, {})[str(k.get("kosu") or "")] = str(k.get("metin") or "bilinmiyor")
                    except (KeyError, TypeError, ValueError) as e:
                        import sys

                        print(f"Kuyruk kaydı atlandı ({dosya.name}: {type(e).__name__} {e})", file=sys.__stderr__)
                    finally:
                        islenen.append(dosya)
            # kayıtlar veritabanına yazıldıktan (commit) sonra silinir: yarıda kalan bir turda kayıt kaybolmaz
            list(_OKUYUCU.map(lambda d: d.unlink(missing_ok=True), islenen))
    return yeni


def _kosunun(kayitlar: dict | None, kosu: str):
    """Bu koşunun kaydı: yalnızca numarası tutan kayıt. Başka koşunun ya da numarasız bir kaydın numaralı koşuya sayılması
    engellenir. Koşu numarası verilmediyse (geliştirme komutları) numarasız kayıt, o da yoksa kameranın herhangi bir kaydı sayılır."""
    if not kayitlar:
        return None
    if kosu:
        return kayitlar.get(kosu)
    return kayitlar[""] if "" in kayitlar else next(iter(kayitlar.values()))


def kosu_bitti(kod: str, kosu: str = "") -> bool:
    """Bu koşunun akışı bitti mi ("bitti" kaydı içeri alındı mı)."""
    return _kosunun(BITENLER.get(kod), kosu) is not None


def kosu_hatasi(kod: str, kosu: str = "") -> str | None:
    """Bu koşuda Studio'daki tespitin çalışmadığını bildiren kayıt geldiyse nedeni; önceki koşudan kalan kayıt sayılmaz."""
    return _kosunun(HATALAR.get(kod), kosu)


BOSALMA_SN = 300.0  # bosalsin'in varsayılan bekleme süresi


def bosalsin(kod: str, en_cok: float | None = None, sakin: float = 1.5) -> bool:
    """Bu kameranın kuyruktaki bütün kayıtları içeri alınana kadar bekler. Sahne durdurulduktan sonra çağrılır.

    Boş sayılması için kuyrukta bu kameraya ait dosya (yazımı süren .tmp dahil) `sakin` saniye boyunca hiç bulunmamalı ve
    içeri alma kilidi boşta olmalıdır: içeri alma, klip dönüştürme dahil, kilit altında yapılır. `en_cok` saniye (verilmezse
    BOSALMA_SN) dolarsa False döner; çağıran bu durumda temizlik yapmamalıdır (işlenmemiş kayıtlar ve dönüştürülmemiş klipler
    olabilir). Süre monotonik saatle ölçülür ve kilit, kalan süre kadar beklenerek edinilir: uzun süren bir klip dönüştürme
    kilidi tutarken de işlev süresini aşmaz."""
    son = time.monotonic() + (BOSALMA_SN if en_cok is None else en_cok)
    bos_basi = None
    while True:
        kalan = son - time.monotonic()
        if kalan <= 0 or not _KILIT.acquire(timeout=kalan):
            return False
        try:
            bos = not KLASOR.is_dir() or not any(KLASOR.glob(f"*_{kod}_*"))
        finally:
            _KILIT.release()
        simdi = time.monotonic()
        if not bos:
            bos_basi = None
        elif bos_basi is None:
            bos_basi = simdi
        elif simdi - bos_basi >= sakin:
            return True
        time.sleep(max(0.0, min(0.2, son - time.monotonic())))


def surekli(dur: threading.Event, yeni_olay=None) -> None:
    """Arka plan döngüsü: kuyruğu saniyede bir boşaltır; `yeni_olay(numaralar)` çıkışları tetikler."""
    while not dur.is_set():
        try:
            yeni = al()
            if yeni and yeni_olay is not None:
                yeni_olay(yeni)
        except Exception:
            import sys
            import traceback

            traceback.print_exc(file=sys.__stderr__)
        dur.wait(1.0)
