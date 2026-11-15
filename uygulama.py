"""Raf Kamera: çift tıklayınca veri klasörünü kurar, yerel sunucuyu başlatır ve tarayıcıda açar.

Sunucu varsayılan olarak yalnızca 127.0.0.1'i dinler. Ayarlar'da ağ erişimi açılırsa bütün ağ arayüzlerini dinler;
ağdan gelen istekler yalnızca API anahtarıyla /api/v1/... adreslerini okuyabilir (olay klipleri ve kareleri dahil).

Ekranlar tek sayfadır (web/index.html); veriler /api/... adreslerinden JSON olarak gelir.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

import yollar

VARSAYILAN_PORT = 8800
KOD_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
KIMLIK_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,19}$")
# Geliştirme kipi (RAF_GELISTIRME=1): panel AugeLab Studio'yu hiç çalıştırmaz ve yoklamaz (kendi kendini sınama yok,
# analiz ve tek seferlik motor işleri "kullanılamıyor" döner). Arayüz ve raporlar örnek verilerle denenir. Varsayılan kapalı.
GELISTIRME = os.environ.get("RAF_GELISTIRME", "").strip() in ("1", "evet", "true")
MOTOR_KAPALI = ("Analiz motoru bu kipte kullanılamıyor (geliştirme kipi: RAF_GELISTIRME). "
                "AugeLab Studio çalıştırılmaz; arayüz örnek verilerle denenebilir.")
TURLER = {
    ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".jpg": "image/jpeg",
    ".mp4": "video/mp4", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png", ".ico": "image/x-icon", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}

# ---------------------------------------------------------------- arka plan işleri


class Is:
    """Arka planda çalışan bir iş (örnek analiz, bağlantı denemesi, izleme) ve ekrana yazdıkları."""

    sayac = 0

    def __init__(self, tur: str, baslik: str):
        Is.sayac += 1
        self.no = Is.sayac
        self.tur, self.baslik = tur, baslik
        self.kod: str | None = None  # işin o anda çalıştığı kamera (varsa)
        self.satirlar: list[str] = []
        self._yarim = ""
        self.durum = "calisiyor"
        self.sonuc: dict = {}
        self.bas, self.bitis = time.time(), None
        self.dur = threading.Event()
        self.kilit = threading.Lock()

    def ekle(self, metin: str) -> None:
        with self.kilit:
            parca = (self._yarim + metin.replace("\r\n", "\n").replace("\r", "\n")).split("\n")
            self._yarim = parca.pop()
            for s in parca:
                s = s.rstrip()
                if not s:
                    continue
                self.satirlar.append(yollar.gizle(s))  # ekrana gider: profil yolu kısaltılır (konsolda tam yol kalır)
            del self.satirlar[:-400]

    def ozet(self) -> dict:
        with self.kilit:
            satirlar = self.satirlar + ([yollar.gizle(self._yarim)] if self._yarim.strip() else [])
        return {"no": self.no, "tur": self.tur, "baslik": self.baslik, "kod": self.kod, "durum": self.durum, "satirlar": satirlar[-80:],
                "sonuc": yollar.gizle_her(self.sonuc), "sure": round((self.bitis or time.time()) - self.bas, 1), "durduruluyor": self.dur.is_set()}


class Yonlendirici(io.TextIOBase):
    """print() çıktısını, o anda hangi işin iş parçacığındaysa o işin kaydına da yazar."""

    def __init__(self, asil):
        self.asil = asil
        self.yerel = threading.local()

    @property
    def encoding(self):
        return "utf-8"

    def write(self, s):
        is_ = getattr(self.yerel, "is_", None)
        if is_ is not None:
            is_.ekle(s)
        if self.asil is not None:
            try:
                self.asil.write(s)
            except UnicodeEncodeError:
                kod = getattr(self.asil, "encoding", None) or "ascii"
                self.asil.write(s.encode(kod, "replace").decode(kod))
            except Exception:
                pass
        return len(s)

    def flush(self):
        if self.asil is not None:
            try:
                self.asil.flush()
            except Exception:
                pass

    def isatty(self):
        return False


DINLENEN = {"adres": "127.0.0.1", "port": VARSAYILAN_PORT, "ag": []}  # sunucunun dinlediği adres (başlarken dolar)
YON_OUT = Yonlendirici(sys.stdout)
YON_ERR = Yonlendirici(sys.stderr)
AKTIF: Is | None = None
IS_KILIDI = threading.Lock()
_SAHNE_KILIDI = threading.Lock()


def is_baslat(tur: str, baslik: str, fn, *args) -> tuple[bool, str]:
    """Tek seferlik işler (video dosyası analizi, örnek videolar, motor işi, kurulum, bağlantı denemesi): aynı anda bir tane.
    Canlı izleme bu sıraya girmez: kamera başına ayrı çalışır (izleme_baslat)."""
    global AKTIF
    with IS_KILIDI:
        if AKTIF is not None and AKTIF.durum == "calisiyor":
            return False, f"Şu an \"{AKTIF.baslik}\" çalışıyor. Bitmesini bekleyin ya da durdurun."
        is_ = Is(tur, baslik)
        AKTIF = is_
    _is_calistir(is_, fn, *args)
    return True, ""


def _is_calistir(is_: Is, fn, *args) -> None:
    """İşi kendi iş parçacığında çalıştırır; print çıktısı işin kaydına düşer, sonuç ve durum işe yazılır."""

    def calis():
        YON_OUT.yerel.is_ = YON_ERR.yerel.is_ = is_
        try:
            sonuc = fn(is_, *args)
            is_.sonuc = sonuc or {}
            is_.durum = "hata" if is_.sonuc.get("hata") else ("durduruldu" if is_.dur.is_set() else "bitti")
        except SystemExit as e:
            if e.code not in (None, 0):
                if not isinstance(e.code, int):
                    print(str(e.code), flush=True)
                is_.durum = "hata"
            else:
                is_.durum = "bitti"
        except Exception as e:  # beklenmeyen hata: ayrıntı konsola, kısa mesaj ekrana
            traceback.print_exc(file=sys.__stderr__)
            print(f"Hata: {e}", flush=True)
            is_.durum = "hata"
        finally:
            YON_OUT.yerel.is_ = YON_ERR.yerel.is_ = None
            is_.bitis = time.time()

    threading.Thread(target=calis, name=f"is-{is_.no}", daemon=True).start()


def ayar_yolu(kod: str) -> Path:
    return yollar.AYAR / f"{kod}.json"


class AyarHatasi(Exception):
    """Kamera ayarı kaydedilemedi; ileti kullanıcıya gösterilir."""


_AYAR_KILIDI = threading.Lock()  # ayar dosyalarını yazan bütün işlemler: aynı anda gelen iki kayıt birbirinin arasına giremez


def _ayar_metni_yaz(dosya, ayar: dict) -> None:
    dosya.write(json.dumps(ayar, ensure_ascii=False, indent=1))


def _ayar_sil(kod: str) -> None:
    ayar_yolu(kod).unlink(missing_ok=True)


BOLGE_TURLERI = {"raf": "Raf", "koridor": "Koridor", "kasa": "Kasa", "dolap": "Soğutucu dolap", "giris": "Giriş"}  # sözleşme: beş tür
GOZLU_TURLER = ("raf", "dolap")


def _sayi(v, ad: str, en_az: float, en_cok: float, tam: bool = False):
    try:
        if isinstance(v, bool):
            raise ValueError
        x = float(v)
    except (TypeError, ValueError):
        raise AyarHatasi(f"{ad} bir sayı olmalı.") from None
    if x != x or not en_az <= x <= en_cok:
        raise AyarHatasi(f"{ad} {en_az:g} ile {en_cok:g} arasında olmalı.")
    if tam and x != int(x):
        raise AyarHatasi(f"{ad} tam sayı olmalı.")
    return int(x) if tam else x


def _nokta(p, ad: str) -> list[float]:
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise AyarHatasi(f"{ad}: nokta okunamadı.")
    return [round(_sayi(p[0], ad, 0, 1), 4), round(_sayi(p[1], ad, 0, 1), 4)]


def _kutu(k, ad: str) -> list[float]:
    if not isinstance(k, (list, tuple)) or len(k) != 4:
        raise AyarHatasi(f"{ad}: kutu dört sayı olmalı (x1, y1, x2, y2).")
    x1, y1, x2, y2 = (round(_sayi(v, ad, 0, 1), 4) for v in k)
    if x2 - x1 < 0.003 or y2 - y1 < 0.003:
        raise AyarHatasi(f"{ad}: kutu çok küçük ya da ters çizilmiş.")
    return [x1, y1, x2, y2]


def _kimlikler(liste, on: str, ad: str) -> list[str]:
    """Var olan kimlikleri korur (değişmez), olmayanlara `on` + sıradaki sayıyı verir. Yinelenen kimlik reddedilir."""
    var = [str(x.get("kimlik")) for x in liste if x.get("kimlik")]
    for k in var:
        if not KIMLIK_RE.match(k):
            raise AyarHatasi(f"{ad} kimliği geçersiz: {k}")
    if len(set(var)) != len(var):
        raise AyarHatasi(f"Aynı {ad.lower()} kimliği birden çok kez geçiyor.")
    n = 1 + max([int(k[len(on):]) for k in var if k.startswith(on) and k[len(on):].isdigit()] or [0])
    out = []
    for x in liste:
        if x.get("kimlik"):
            out.append(str(x["kimlik"]))
        else:
            while f"{on}{n}" in var:
                n += 1
            out.append(f"{on}{n}")
            var.append(f"{on}{n}")
            n += 1
    return out


def bolgeleri_denetle(bolgeler, urun_kimlikleri: set[str]) -> list[dict]:
    """Bölgeleri ve gözleri denetler; kimliği olmayan bölgeye ve göze kimlik verir (var olanlar değişmez). Hatalı
    girdide hiçbir şey yazılmaz, neden Türkçe bildirilir."""
    if bolgeler is None:
        return []
    if not isinstance(bolgeler, list) or len(bolgeler) > 60:
        raise AyarHatasi("Bölgeler okunamadı (en çok 60 bölge).")
    if any(not isinstance(b, dict) for b in bolgeler):
        raise AyarHatasi("Bölgeler okunamadı.")
    bkim = _kimlikler(bolgeler, "b", "Bölge")
    tum_gozler = [g for b in bolgeler for g in (b.get("gozler") or []) if isinstance(g, dict)]
    gkim = iter(_kimlikler(tum_gozler, "g", "Göz"))
    out, sayac = [], defaultdict_int()
    for b, kimlik in zip(bolgeler, bkim):
        tur = b.get("tur")
        if tur not in BOLGE_TURLERI:
            raise AyarHatasi(f"Bilinmeyen bölge türü: {tur}")
        sayac[tur] += 1
        ad = str(b.get("ad") or "").strip()[:60] or f"{BOLGE_TURLERI[tur]} {sayac[tur]}"
        yeni = {"kimlik": kimlik, "ad": ad, "tur": tur}
        if tur == "giris":
            cizgi = b.get("cizgi")
            if not isinstance(cizgi, list) or len(cizgi) != 2:
                raise AyarHatasi(f"\"{ad}\": giriş için sayım çizgisi (iki nokta) çizin.")
            yeni["cizgi"] = [_nokta(p, ad) for p in cizgi]
            if yeni["cizgi"][0] == yeni["cizgi"][1]:
                raise AyarHatasi(f"\"{ad}\": çizginin iki ucu aynı yerde.")
            if b.get("ic") is None:
                raise AyarHatasi(f"\"{ad}\": mağazanın iç tarafını göstermek için bir nokta seçin.")
            yeni["ic"] = _nokta(b["ic"], ad)
        else:
            poly = b.get("poly")
            if not isinstance(poly, list) or not 3 <= len(poly) <= 100:
                raise AyarHatasi(f"\"{ad}\": bölge için en az üç köşe gerekir.")
            yeni["poly"] = [_nokta(p, ad) for p in poly]
        if tur == "kasa" and b.get("esik") not in (None, ""):
            yeni["esik"] = _sayi(b["esik"], f"\"{ad}\" kuyruk eşiği", 1, 50, tam=True)
        gozler = b.get("gozler") or []
        if gozler and tur not in GOZLU_TURLER:
            raise AyarHatasi(f"\"{ad}\": göz yalnızca raf ve soğutucu dolap bölgesine eklenir.")
        if tur in GOZLU_TURLER:
            if not isinstance(gozler, list) or len(gozler) > 300:
                raise AyarHatasi(f"\"{ad}\": gözler okunamadı (en çok 300).")
            yeni["gozler"] = []
            for i, g in enumerate(gozler, 1):
                if not isinstance(g, dict):
                    raise AyarHatasi(f"\"{ad}\": göz okunamadı.")
                gad = f"\"{ad}\" {i}. göz"
                urun = g.get("urun") or None
                if urun is not None and str(urun) not in urun_kimlikleri:
                    raise AyarHatasi(f"{gad}: ürün katalogda yok ({urun}).")
                fiyat = g.get("fiyat")
                yeni["gozler"].append({
                    "kimlik": next(gkim), "kutu": _kutu(g.get("kutu"), gad), "urun": None if urun is None else str(urun),
                    "adet": _sayi(g.get("adet") if g.get("adet") not in (None, "") else 1, f"{gad} beklenen yüz sayısı", 1, 99, tam=True),
                    "etiket": _kutu(g["etiket"], f"{gad} etiketi") if g.get("etiket") else None,
                    "fiyat": None if fiyat in (None, "") else round(_sayi(fiyat, f"{gad} fiyatı", 0, 999999), 2),
                })
        out.append(yeni)
    return out


def defaultdict_int():
    from collections import defaultdict

    return defaultdict(int)


def ozellikleri_denetle(ozellikler) -> dict:
    """Kamera başına özellik ayarları: {kod: {"acik": bool, ayar: değer}}. Ayar türü katalogdaki varsayılanla aynı olmalı."""
    import kurallar

    if ozellikler is None:
        return {}
    if not isinstance(ozellikler, dict) or len(ozellikler) > 100:
        raise AyarHatasi("Özellik ayarları okunamadı.")
    out = {}
    for kod, deger in ozellikler.items():
        if not re.match(r"^[a-z][a-z0-9_]{1,39}$", str(kod)) or not isinstance(deger, dict):
            raise AyarHatasi(f"Özellik ayarı okunamadı: {kod}")
        k = kurallar.KURAL.get(kod)
        if kurallar.KURALLAR and k is None:
            raise AyarHatasi(f"Bilinmeyen özellik: {kod}")
        ad = (k or {}).get("ad") or kod
        varsayilan = (k or {}).get("ayarlar") or {}
        yeni = {}
        for a, v in deger.items():
            if a == "acik":
                yeni["acik"] = bool(v)
                continue
            if not re.match(r"^[a-z][a-z0-9_]{0,39}$", str(a)):
                raise AyarHatasi(f"\"{ad}\": ayar adı okunamadı.")
            tanim = varsayilan.get(a)
            # katalog ayarı düz varsayılan (20) ya da tanım ({"ad", "varsayilan", "birim", "en_az", "en_cok", "adim"}) olabilir
            if not isinstance(tanim, dict):
                tanim = {"varsayilan": tanim}
            ornek = tanim.get("varsayilan")
            ayar_ad = f"\"{ad}\" · {tanim.get('ad') or a}"
            if isinstance(ornek, bool) or (ornek is None and isinstance(v, bool)):
                yeni[a] = bool(v)
            elif isinstance(ornek, (int, float)) or (ornek is None and isinstance(v, (int, float))):
                en_az = tanim.get("en_az") if isinstance(tanim.get("en_az"), (int, float)) else 0
                en_cok = tanim.get("en_cok") if isinstance(tanim.get("en_cok"), (int, float)) else 1e6
                yeni[a] = _sayi(v, ayar_ad, en_az, en_cok)
                if isinstance(ornek, int) and not isinstance(ornek, bool) and float(yeni[a]).is_integer():
                    yeni[a] = int(yeni[a])
            elif isinstance(v, str) and len(v) <= 200:
                yeni[a] = v
            else:
                raise AyarHatasi(f"\"{ad}\" ayarı ({a}) okunamadı.")
        out[str(kod)] = yeni
    return out


def _gozler_imzasi(ayar: dict) -> str:
    return json.dumps([[b.get("kimlik"), [[g.get("kimlik"), g.get("kutu")] for g in b.get("gozler") or []]]
                       for b in ayar.get("bolgeler") or [] if b.get("tur") in GOZLU_TURLER], sort_keys=True)


def _ayar_hazirla(ayar, ornek: bool = False) -> tuple[str, dict, list[str]]:
    """Gelen ayarı denetler: (kısa kod, şifresi temizlenmiş ayar, notlar). Bölgeler, gözler ve özellik ayarları da
    denetlenir; referans karesi bilgisi her zaman diskteki ayardan alınır (istekle değiştirilemez)."""
    import depo

    if not isinstance(ayar, dict):
        raise AyarHatasi("Ayar okunamadı.")
    kod = str(ayar.get("kod", ""))
    if not KOD_RE.match(kod):
        raise AyarHatasi("Kısa kod yalnızca küçük harf (a-z), rakam, - ve _ içerebilir (ör. depo2).")
    if kod in yollar.ORNEK_ADLARI:
        raise AyarHatasi(f"\"{kod}\" örnek kameralara ait. Başka bir kısa kod yazın (ör. {kod}2).")
    if depo.ornek_kamera(kod) != ornek:
        raise AyarHatasi(f"\"{depo.ORNEK_ON}\" ile başlayan kodlar örnek verilere ayrılmıştır. Başka bir kısa kod yazın."
                         if not ornek else "Örnek kameranın kodu örnek önekiyle başlamalı.")
    ayar = json.loads(json.dumps(ayar))  # kopya: çağıranın verisi değişmesin
    ayar["kod"] = kod
    ayar["ad"] = str(ayar.get("ad") or kod).strip()[:80] or kod
    ayar["bolgeler"] = bolgeleri_denetle(ayar.get("bolgeler"), {u["kimlik"] for u in depo.urunler()})
    ayar["ozellikler"] = ozellikleri_denetle(ayar.get("ozellikler"))
    for alan, ad, en_az, en_cok in (("kisi_fps", "Kişi analizi hızı (kare/sn)", 0.5, 10), ("raf_araligi_sn", "Raf kontrol aralığı (sn)", 1, 3600)):
        if ayar.get(alan) in (None, ""):
            ayar.pop(alan, None)
        else:
            ayar[alan] = _sayi(ayar[alan], ad, en_az, en_cok)
    eski = {}
    try:
        eski = json.loads(ayar_yolu(kod).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    ayar.pop("referans", None)
    ayar.pop("gozler_degisim", None)
    if isinstance(eski, dict):
        if eski.get("referans"):
            ayar["referans"] = eski["referans"]
        if _gozler_imzasi(eski) != _gozler_imzasi(ayar) and (eski.get("bolgeler") or ayar["bolgeler"]):
            ayar["gozler_degisim"] = depo.simdi()  # gözler değişti: referans karesini yenilemek gerekir
        elif eski.get("gozler_degisim"):
            ayar["gozler_degisim"] = eski["gozler_degisim"]
    if ornek:
        ayar["ornek"] = True
    else:
        ayar.pop("ornek", None)
    return kod, ayar, sifreyi_temizle(ayar)


def ayar_kaydet(ayar: dict, ornek: bool = False) -> tuple[str, list[str]]:
    """Var olan ya da yeni kamera ayarını denetleyip yazar (geçici dosya + yer değiştirme)."""
    kod, ayar, notlar = _ayar_hazirla(ayar, ornek=ornek)
    with _AYAR_KILIDI:
        yollar.AYAR.mkdir(parents=True, exist_ok=True)
        gecici = yollar.AYAR / f".{kod}.json.tmp"
        gecici.write_text(json.dumps(ayar, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, ayar_yolu(kod))
    return kod, notlar


def kameralari_olustur(ayarlar) -> dict:
    """Yeni kameraları tek işlemde oluşturur: ya hepsi yazılır ya hiçbiri (toplu kanal ekleme).

    Var olan bir kameranın üstüne yazılmaz. Denetim ve yazma tek kilit altında yapılır ve her dosya "yoksa oluştur" ile
    açılır: aynı anda gelen iki istekten yalnızca biri başarılı olur. Yazarken hata çıkarsa bu çağrının oluşturduğu
    dosyalar silinir; silinemeyen olursa adı iletide açıkça yazılır."""
    if not isinstance(ayarlar, list) or not 1 <= len(ayarlar) <= 64:
        raise AyarHatasi("Bir seferde 1 ile 64 arasında kamera eklenebilir.")
    hazir = [_ayar_hazirla(a) for a in ayarlar]
    kodlar = [kod for kod, _, _ in hazir]
    yinelenen = sorted({k for k in kodlar if kodlar.count(k) > 1})
    if yinelenen:
        raise AyarHatasi(f"Aynı kısa kod birden çok kez geçiyor: {', '.join(yinelenen)}. Hiçbiri eklenmedi.")
    with _AYAR_KILIDI:
        yollar.AYAR.mkdir(parents=True, exist_ok=True)
        varolan = [k for k in kodlar if ayar_yolu(k).exists()]
        if varolan:
            raise AyarHatasi(f"Bu kodlarla kamera zaten var: {', '.join(varolan)}. Üstlerine yazılmadı; hiçbiri eklenmedi.")
        olusan: list[str] = []
        try:
            for kod, ayar, _ in hazir:
                dosya = open(ayar_yolu(kod), "x", encoding="utf-8")  # "x": dosya varsa hata verir, var olanı ezmez
                olusan.append(kod)
                with dosya:
                    _ayar_metni_yaz(dosya, ayar)
        except OSError as e:
            kalan = []
            for kod in olusan:  # yalnızca bu çağrının oluşturdukları geri alınır
                try:
                    _ayar_sil(kod)
                except OSError:
                    kalan.append(kod)
            neden = "aynı kodla bir kamera az önce oluşturulmuş" if isinstance(e, FileExistsError) else f"dosya yazılamadı ({type(e).__name__})"
            raise AyarHatasi(f"Kameralar eklenemedi: {neden}. " + ("Hiçbiri eklenmedi." if not kalan else
                             f"Geri alınamayan kayıtlar kaldı: {', '.join(kalan)}. Bunları Ayarlar'dan silin.")) from None
    return {"kodlar": kodlar, "notlar": sorted({n for _, _, notlar in hazir for n in notlar})}


def kanal_ayarlari(taban, kanallar, profiller=None) -> list[dict]:
    """Bir kayıt cihazının kanalları için kamera ayarlarını üretir: `taban` formdaki ayardır (kod, ad, bağlantı, kurallar).

    Her kanal `<kod>-k<n>` koduyla ayrı bir kamera olur; bölgeler boş başlar, kurallar kopyalanır. `profiller` verilirse
    (ONVIF: cihazdan okunan profil listesi) kanalın profil ve görüntü kaynağı belirteçleri de yazılır: kamera, cihaz
    profilleri sonradan başka sırayla bildirse de aynı fiziksel kanala bağlanır. Listede profili olmayan kanal reddedilir."""
    if not isinstance(taban, dict) or not isinstance(taban.get("kamera"), dict):
        raise AyarHatasi("Ayar okunamadı.")
    kod = str(taban.get("kod", ""))
    if not KOD_RE.match(kod):
        raise AyarHatasi("Önce kısa kodu yazın (ör. nvr1): kanallar nvr1-k1, nvr1-k2… olarak eklenir.")
    if not taban["kamera"].get("ip"):
        raise AyarHatasi("Önce kayıt cihazının IP adresini yazın.")
    try:
        kanallar = [int(n) for n in kanallar]
    except (TypeError, ValueError):
        raise AyarHatasi("Kanal listesi okunamadı.") from None
    if not 1 <= len(kanallar) <= 64 or len(set(kanallar)) != len(kanallar) or min(kanallar) < 1:
        raise AyarHatasi("Kanal sayısı 1 ile 64 arasında olmalı ve her kanal bir kez geçmeli.")
    if taban["kamera"].get("tur") == "onvif" and not (isinstance(profiller, list) and profiller):
        # ONVIF'te kanal, kalıcı profil ve kaynak belirteciyle kaydedilir; liste gelmediyse belirteçsiz ayar yazılmaz
        raise AyarHatasi("ONVIF kanalları eklenmeden önce cihazın kanalları ve profilleri listelenmeli; hiçbiri eklenmedi.")
    if taban["kamera"].get("tur") != "onvif":
        profiller = None  # markaya göre RTSP: kanal adresin içindedir, belirteç yoktur
    out = []
    for n in kanallar:
        kamera = {a: v for a, v in taban["kamera"].items() if a not in ("profil", "profil_ad", "kaynak")}
        kamera["kanal"] = n
        if profiller is not None:
            aday = sorted((p for p in profiller if isinstance(p, dict) and p.get("kanal") == n and p.get("belirtec") and p.get("kaynak")),
                          key=lambda p: int(p.get("en") or 0) * int(p.get("boy") or 0))
            if not aday:
                raise AyarHatasi(f"Cihazın bildirdiği profiller arasında {n}. kanal yok; hiçbiri eklenmedi. Kanalları yeniden listeleyin.")
            p = aday[-1] if kamera.get("akis") == "ana" else aday[0]
            kamera.update(profil=str(p["belirtec"]), kaynak=str(p["kaynak"]),
                          profil_ad=f"Kanal {n} · {p.get('ad') or p['belirtec']} · {p.get('kodlama', '')} {p.get('en', 0)}×{p.get('boy', 0)}")
        out.append({**taban, "kod": f"{kod}-k{n}", "ad": f"{taban.get('ad') or kod} · Kanal {n}", "kamera": kamera, "bolgeler": []})
    return out


def ayar_oku(kod: str) -> dict:
    yol = ayar_yolu(kod)
    if not yol.exists():
        raise SystemExit(f"Ayar bulunamadı: {kod}")
    return json.loads(yol.read_text(encoding="utf-8"))


def _bildir(olay_numaralari: list[int]) -> None:
    """Yeni başlayan olayları tanımlı çıkışlara iletir. Örnek (demo) olaylar hiçbir çıkışa gönderilmez."""
    import baglanti
    import depo

    if olay_numaralari:
        ornekler = {r["id"] for r in depo.sor(f"SELECT id FROM olay WHERE ornek = 1 AND id IN ({','.join(str(int(n)) for n in olay_numaralari)})")}
        olay_numaralari = [n for n in olay_numaralari if n not in ornekler]
    if not olay_numaralari:
        return
    for satir in baglanti.gonder(olay_numaralari):
        print(satir, flush=True)


def _studio(korutin):
    import asyncio

    return asyncio.run(korutin)


def is_studio_dene(is_: Is) -> dict:
    """Studio lisansını bir kez kontrol eder: Studio arka planda kısa süre çalışır, modeller açılır (korumalı paketin
    lisansı burada doğrulanır; hiç model yoksa Studio'nun kurulu, lisanslı olduğu ve blokları yüklediği sınanır). Sonuç saklanır; sonraki açılışlarda yeniden yapılmaz."""
    import studio

    engel = _model_indirme_engeli()  # deneme modeli açar: model yokken denenirse sonuç yanlışlıkla "hazır değil" kalırdı
    if engel:
        raise SystemExit(engel)
    print("Lisans kontrol ediliyor…", flush=True)
    try:
        studio.dene()
    except studio.StudioHatasi as e:
        raise SystemExit(str(e)) from None
    finally:
        _STUDIO["an"] = 0.0
    print("Hazır: lisans doğrulandı.", flush=True)
    return {}


def _tespit_hatasi(neden: str | None) -> str:
    return (f"AugeLab Studio'daki analiz çalışmıyor ({neden}). "
            "Model dosyalarını ve AugeLab Studio lisansınızı kontrol edin.")


KUYRUK_BOSALMADI = ("Studio'dan gelen son kayıtlar işlenemedi (kuyruk boşalmadı). Açık olaylar ve yarım klipler olduğu gibi bırakıldı; "
                    "veri klasöründeki kuyruk klasörüne bakın.")


def _sahneyi_kapat(kod: str, durdur, bekle_sn: float) -> str | None:
    """Sahneyi durdurur (`durdur()`: durdurma işini veren işlev) ve kameranın kuyruğunun boşalmasını bekler.

    Dönüş: her şey yolundaysa None; durdurma doğrulanamadıysa ya da kuyruk bekleme süresinde boşalmadıysa nedeni.
    Neden dönerse çağıran açık olayları kapatmaz, yarım klipleri silmez ve işi hatayla bitirir: sahne hâlâ kayıt
    bırakıyor olabilir ya da işlenmemiş kayıtlar ve dönüştürülmemiş klipler vardır."""
    import kuyruk

    try:
        _studio(durdur())
    except Exception as e:
        return (f"AugeLab Studio sürecinin durduğu doğrulanamadı ({type(e).__name__}: {e}). Açık olaylar ve "
                "yarım klipler olduğu gibi bırakıldı. Programı kapatıp yeniden açın.")
    time.sleep(bekle_sn)  # sahnenin son kayıtları kuyruğa düşsün
    if not kuyruk.bosalsin(kod):  # bu koşunun bütün kayıtları içeri alınmalı, klipleri dönüştürülmeli
        return KUYRUK_BOSALMADI
    return None


def studioda_analiz(is_: Is, kod: str, en_cok_sn: float = 1800.0) -> None:
    """Kameranın video dosyasını AugeLab Studio'daki sahnede baştan sona çalıştırır; olaylar kuyruktan panele düşer."""
    import kuyruk
    import studio

    ayar = ayar_oku(kod)
    print("  AugeLab Studio hazırlanıyor (arayüzsüz; pencere açılmaz)", flush=True)
    with _SAHNE_KILIDI:  # birden çok kamera aynı anda başlarken bloklar ve sahne bir kez, sırayla hazırlanır
        bilgi = _studio(studio.sahne_kur(kod, ayar))
    kuyruk.BITENLER.pop(kod, None)
    kuyruk.HATALAR.pop(kod, None)

    async def baslat():
        kosu = await studio.yeni_kosu(bilgi, kod)
        await studio.calistir(bilgi, int(en_cok_sn * 1000))
        return kosu

    kosu = _studio(baslat())  # kuyruk kayıtları bu numarayı taşır: önceki çalıştırmadan kalan kayıt bu işe sayılmaz
    hata: BaseException | None = None
    print("  sahne AugeLab Studio'da arayüzsüz çalışıyor (ilk çalıştırmada Studio'nun ve modelin yüklenmesi biraz sürer)", flush=True)
    bas = time.time()
    try:
        while True:
            if kuyruk.kosu_hatasi(kod, kosu):  # "bitti" kaydıyla aynı anda gelse de hata önce gelir
                raise SystemExit(_tespit_hatasi(kuyruk.kosu_hatasi(kod, kosu)))
            if kuyruk.kosu_bitti(kod, kosu):
                break
            if studio.kosu_sorunu(bilgi):
                raise SystemExit(studio.kosu_sorunu(bilgi))
            if is_.dur.is_set():
                print("  durduruldu", flush=True)
                break
            if time.time() - bas > en_cok_sn:
                raise SystemExit("AugeLab Studio'daki analiz beklenen sürede bitmedi.")
            son = kuyruk.SON_KAYIT.get(kod, 0.0)
            # ilk kayıttan önce daha uzun beklenir: motor yenilendiyse Studio blokları ve modeli baştan yükler
            if time.time() - max(bas, son) > (90 if son > bas else 240):
                raise SystemExit("AugeLab Studio'dan uzun süredir kayıt gelmedi. Kurulum sihirbazındaki “Studio’yu dene” adımıyla kontrol edin.")
            time.sleep(0.5)
    except BaseException as e:  # iş hatası: sahne yine de kapatılır, hata aşağıda yeniden yükseltilir
        hata = e
    # Temizlik (açık olayları kapatma, yarım klipleri silme) yalnızca sahnenin durduğu doğrulandıysa ve bu koşunun bütün
    # kuyruk kayıtları içeri alınıp klipleri dönüştürüldüyse yapılır; değilse hiçbir şey silinmez ve iş hatayla biter.
    sorun = _sahneyi_kapat(kod, lambda: studio.durdur(bilgi), 1.2)
    if sorun is not None:
        print("  uyarı: " + sorun, flush=True)
    elif not kuyruk.kosu_bitti(kod, kosu) or kuyruk.kosu_hatasi(kod, kosu):  # hata ya da durdurma: süren olaylar kapanış kaydı bırakamadı
        _acik_olaylari_kapat(kod)
    if hata is not None:
        raise hata
    if kuyruk.kosu_hatasi(kod, kosu):  # bu koşunun hata kaydı "bitti"den sonra, son kayıtlarla işlenmiş olabilir
        raise SystemExit(_tespit_hatasi(kuyruk.kosu_hatasi(kod, kosu)))
    if sorun is not None:
        raise SystemExit(sorun)


YINELENIR = ("AugeLab Studio sahneyi çalıştıramadı", "AugeLab Studio'dan uzun süredir kayıt gelmedi")


def analiz_bir_kez_yinele(is_: Is, kod: str, temizle) -> None:
    """Video dosyası analizi: Studio süreci kayıt bırakmadan kapanırsa (ör. açılışta beklenmedik çıkış) bir kez daha denenir.
    Yalnızca süreç düzeyindeki hatalar yinelenir; model, lisans ya da ayar hatası yinelenmez."""
    try:
        studioda_analiz(is_, kod)
    except SystemExit as e:
        if is_.dur.is_set() or not str(e.code or "").startswith(YINELENIR):
            raise
        print(f"  ilk deneme olmadı ({e.code}); bir kez daha deneniyor", flush=True)
        temizle()
        studioda_analiz(is_, kod)


def _acik_olaylari_kapat(kod: str) -> None:
    """Sahne durdurulduğunda süren olaylar kapanış kaydı bırakamaz: panelde "sürüyor" olarak kalmasın, yarım klipler silinsin."""
    import depo

    depo.yaz("UPDATE olay SET suruyor = 0 WHERE kamera = ? AND suruyor = 1", kod)
    if (yollar.CIKTI / kod).is_dir():
        for f in (yollar.CIKTI / kod).glob("*.ham.mp4"):
            try:
                f.unlink()
            except OSError:
                pass


def _ornegi_temizle(kod: str) -> None:
    import depo

    depo.kamera_sil(kod, yalniz_ornek=True)
    for f in (yollar.CIKTI / kod).glob("*") if (yollar.CIKTI / kod).is_dir() else []:
        f.unlink(missing_ok=True)


ORNEK_URUN_ON = "ov"  # programla gelen örnek videoların ürünleri (ornekler/urunler/): kimlikleri bu önekle başlar


def _ornek_dosyalari(kod: str) -> list[Path]:
    """Bir örnek kameranın programla gelen dosyaları: ayar, referans karesi (+ kişi kutuları), video, örnek ürün kataloğu."""
    o = yollar.ORNEKLER
    return [o / "ayar" / f"{kod}.json", o / "ayar" / f"_referans_{kod}.jpg", o / "ayar" / f"_referans_{kod}.json",
            o / "videolar" / f"{kod}.mp4", o / "urunler" / "urunler.json"]


def ornek_imzasi(kod: str) -> str:
    """Programla gelen örnek dosyalarının içerik imzası: değişince (yeni sürüm) örnek kamera yeniden kurulur."""
    h = hashlib.sha256()
    for p in _ornek_dosyalari(kod):
        h.update(p.name.encode("utf-8") + b"\0")
        h.update(p.read_bytes() if p.is_file() else b"-")
    return h.hexdigest()[:20]


def ornek_urunleri_kur() -> int:
    """Örnek videoların ürünlerini (ornekler/urunler/urunler.json + gorsel/) kataloğa ekler ya da günceller. Ürünler
    "ornek_video" işaretlidir ve kimlikleri ORNEK_URUN_ON ile başlar: kullanıcının ürünleri ve örnek verilerle (ornek)
    karışmaz, kullanıcının ürününe dokunulmaz. Dönüş: kurulan ürün sayısı."""
    import depo

    kaynak = yollar.ORNEKLER / "urunler"
    try:
        gelen = json.loads((kaynak / "urunler.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    gelen = [u for u in gelen if isinstance(u, dict) and str(u.get("kimlik") or "").startswith(ORNEK_URUN_ON)]
    if not gelen:
        return 0
    with depo._URUN_KILIDI:
        depo.gorsel_klasoru().mkdir(parents=True, exist_ok=True)
        liste = depo.urunler()
        for u in gelen:
            gorseller = []
            for dosya in u.get("gorseller") or []:
                if GORSEL_RE.match(dosya) and (kaynak / "gorsel" / dosya).is_file():
                    shutil.copyfile(kaynak / "gorsel" / dosya, depo.gorsel_klasoru() / dosya)
                    gorseller.append(dosya)
            yeni = {"kimlik": u["kimlik"], "ad": str(u.get("ad") or u["kimlik"])[:80], "barkod": "",
                    "kategori": str(u.get("kategori") or "")[:40], "fiyat": u.get("fiyat"), "gorseller": gorseller,
                    "ornek_video": True}
            liste = [x for x in liste if x["kimlik"] != u["kimlik"]] + [yeni]
        depo.urunleri_yaz(liste)
    return len(gelen)


def ornek_video_kur(kod: str) -> dict:
    """Programla gelen örnek videoyu kamera olarak kurar: video veri klasörüne kopyalanır, ayarı (ornekler/ayar/<kod>.json ya
    da varsayılan) bölge / göz / özellik denetiminden geçirilip kimlikleri verilerek yazılır; kamera "örnek video" işaretlidir.
    Programla gelen dosyalar (ayar, referans karesi, video, örnek ürünler) değişmediyse var olan ayar korunur; değiştiyse
    (yeni sürüm) örnek kamera bunlardan yeniden kurulur. Örnek kameralar panelden düzenlenemez (kodları ayrılmıştır)."""
    import depo

    imza = ornek_imzasi(kod)
    try:
        ayar = ayar_oku(kod)
    except SystemExit:
        ayar = {}
    yenile = ayar.get("ornek_imza") != imza
    if yenile:
        ayar = yollar.ornek_ayari(kod)
    video = yollar.VIDEOLAR / f"{kod}.mp4"
    if yenile or not video.exists():
        yollar.VIDEOLAR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(yollar.ORNEKLER / "videolar" / f"{kod}.mp4", video)
    if yenile:  # referans karesi: programla gelen (yüzleri gizli, motorun temiz karesinden alınmış) ya da hiç
        yollar.AYAR.mkdir(parents=True, exist_ok=True)
        for uzanti in (".jpg", ".json"):
            hedef = yollar.AYAR / f"_referans_{kod}{uzanti}"
            kaynak = yollar.ORNEKLER / "ayar" / f"_referans_{kod}{uzanti}"
            if kaynak.is_file():
                shutil.copyfile(kaynak, hedef)
            else:
                hedef.unlink(missing_ok=True)
        ayar.pop("referans", None)
        if (yollar.AYAR / f"_referans_{kod}.jpg").is_file():
            ayar["referans"] = {"zaman": depo.simdi(), "ornek": True}
    ayar.update(kod=kod, ornek_video=True, ornek_imza=imza, kamera={"tur": "dosya", "yol": f"videolar/{kod}.mp4"})
    ayar["bolgeler"] = bolgeleri_denetle(ayar.get("bolgeler"), {u["kimlik"] for u in depo.urunler()})
    ayar["ozellikler"] = ozellikleri_denetle(ayar.get("ozellikler"))
    with _AYAR_KILIDI:
        yollar.AYAR.mkdir(parents=True, exist_ok=True)
        gecici = yollar.AYAR / f".{kod}.json.tmp"
        gecici.write_text(json.dumps(ayar, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, ayar_yolu(kod))
    return ayar


def is_ornek(is_: Is, secilen: list[str] | None = None) -> dict:
    """"Örnek videoları çözümle": ornekler/ klasöründeki her örnek videoyu kamera olarak kurar ve sırayla AugeLab Studio'da
    baştan sona analiz eder (gerçek motor yolu). Önceki çözümlemenin sonuçları önce silinir. `secilen`: yalnızca bu örnekler."""
    import kuyruk

    kodlar = [k for k in yollar.ornek_kodlar() if not secilen or k in secilen]
    if not kodlar:
        raise SystemExit("Bu sürümde örnek video yok. Bir kamera ya da video dosyası ekleyin.")
    ornek_urunleri_kur()
    for n, kod in enumerate(kodlar, 1):
        if is_.dur.is_set():
            print("Durduruldu.", flush=True)
            return {}
        try:
            ayar = ornek_video_kur(kod)
        except AyarHatasi as e:
            print(f"[{n}/{len(kodlar)}] {kod}: örnek ayarı okunamadı ({e}); atlandı.", flush=True)
            continue
        print(f"[{n}/{len(kodlar)}] {ayar.get('ad', kod)} AugeLab Studio'da analiz ediliyor…", flush=True)
        is_.kod = kod
        t0 = time.time()
        _ornegi_temizle(kod)
        kuyruk.SON_KAYIT.pop(kod, None)
        analiz_bir_kez_yinele(is_, kod, lambda: (_ornegi_temizle(kod), kuyruk.SON_KAYIT.pop(kod, None)))
        print(f"[{n}/{len(kodlar)}] bitti ({time.time() - t0:.0f} sn).", flush=True)
    return {"git": "#/"}


def is_test(is_: Is, kod: str, sifre: str | None) -> dict:
    import kamera

    ayar = ayar_oku(kod)
    if kamera.test(ayar, ayar_yolu(kod), sifre) != 0:
        return {"hata": True}
    return {"kare": f"/ayar/_kare_{kamera.kod(ayar, ayar_yolu(kod))}.jpg?t={int(time.time())}", "kod": kod}


def is_izle(is_: Is, kod: str, sifre: str | None, dakika: float) -> dict:
    """Canlı kamerayı AugeLab Studio'daki sahnede durdurulana kadar izler; olaylar başladığı anda panele düşer."""
    import kamera
    import kuyruk
    import studio

    ayar = ayar_oku(kod)
    if (ayar.get("kamera") or {}).get("tur") not in ("rtsp", "onvif", "http"):
        raise SystemExit("Canlı izleme IP kamera, kayıt cihazı ya da HTTP akışı içindir. Video dosyasında Videoyu analiz et'i kullanın.")
    adres, goster = kamera.kaynak(ayar, sifre)
    print(f"{ayar.get('ad', kod)}: {goster}", flush=True)
    print("  AugeLab Studio hazırlanıyor (arayüzsüz; pencere açılmaz)", flush=True)
    with _SAHNE_KILIDI:  # birden çok kamera aynı anda başlarken bloklar ve sahne bir kez, sırayla hazırlanır
        bilgi = _studio(studio.sahne_kur(kod, ayar))
    kuyruk.SON_KAYIT.pop(kod, None)
    kuyruk.HATALAR.pop(kod, None)

    async def baslat():
        await studio.kamera_adresi(bilgi, str(adres))
        kosu = await studio.yeni_kosu(bilgi, kod)
        await studio.calistir(bilgi)
        return kosu

    async def bitir():
        try:
            await studio.durdur(bilgi)
        finally:
            await studio.kamera_adresi(bilgi, "")  # adres şifre içerebilir: bellekte bırakılmaz

    kosu = _studio(baslat())
    print("  sahne AugeLab Studio'da arayüzsüz çalışıyor; durdurulana kadar izlenir", flush=True)
    bas, uyarildi = time.time(), False
    hata: BaseException | None = None
    import depo

    saatte_basladi = getattr(is_, "saatte_basladi", None)
    if saatte_basladi is None:
        saatte_basladi = depo.calisma_saatinde(dt.datetime.now())
    try:
        while not is_.dur.is_set():
            if saatte_basladi and not depo.calisma_saatinde(dt.datetime.now()):  # çalışma saati bitti: izleme kendiliğinden durur
                print("  çalışma saatleri bitti; izleme durduruluyor", flush=True)
                break
            if kuyruk.kosu_hatasi(kod, kosu):
                raise SystemExit(_tespit_hatasi(kuyruk.kosu_hatasi(kod, kosu)))
            if studio.kosu_sorunu(bilgi):
                raise SystemExit(studio.kosu_sorunu(bilgi))
            son = kuyruk.SON_KAYIT.get(kod, 0.0)
            if not uyarildi and time.time() - max(bas, son) > 45:
                uyarildi = True
                print("  45 saniyedir Studio'dan kayıt gelmiyor: kamera görüntü vermiyor olabilir (adres, kullanıcı, şifre, ağ).", flush=True)
            elif uyarildi and time.time() - son < 10:
                uyarildi = False
                print("  kayıt yeniden geliyor", flush=True)
            time.sleep(0.5)
        print("  durduruluyor", flush=True)
    except BaseException as e:  # iş hatası: sahne yine de kapatılır, hata aşağıda yeniden yükseltilir
        hata = e
    # Video akışındaki kural: durdurma doğrulanamazsa ya da kuyruk boşalmazsa temizlik atlanır ve iş hatayla biter.
    sorun = _sahneyi_kapat(kod, bitir, 1.5)
    if sorun is None:
        _acik_olaylari_kapat(kod)  # izleme durduruldu: süren olaylar kapanış kaydı bırakamadı
    else:
        print("  uyarı: " + sorun, flush=True)
    if hata is not None:
        raise hata
    if kuyruk.kosu_hatasi(kod, kosu):  # hata kaydı son kayıtlarla işlenmiş olabilir
        raise SystemExit(_tespit_hatasi(kuyruk.kosu_hatasi(kod, kosu)))
    if sorun is not None:
        raise SystemExit(sorun)
    return {"git": "#/"}


def is_video(is_: Is, kod: str) -> dict:
    """Video dosyası türündeki kamerayı (ör. kayıt cihazından alınmış kayıt) AugeLab Studio'da baştan sona analiz eder."""
    import kuyruk

    ayar = ayar_oku(kod)
    if (ayar.get("kamera") or {}).get("tur") != "dosya":
        raise SystemExit("Bu kamera bir video dosyası değil.")
    print(f"{ayar.get('ad', kod)} AugeLab Studio'da analiz ediliyor…", flush=True)
    kuyruk.SON_KAYIT.pop(kod, None)
    studioda_analiz(is_, kod)
    return {"git": "#/"}


# ---------------------------------------------------------------- canlı izleme: kamera başına ayrı koşu, çalışma saatine göre kendiliğinden
#
# Her kamera kendi gizli Studio sürecinde, kendi işiyle (Is) izlenir: durdurma, kuyruk boşaltma ve hata ayrı ayrı yürür.
# İzlenmesi istenen kameralar <VERI>/izleme.json'da tutulur (yalnızca kodlar). Çalışma saati bitince izleme durur ve
# ertesi açılışta (ya da panel yeniden açıldığında, çalışma saatindeyse) kendiliğinden yeniden başlar. Kamera şifresi diske
# yazılmaz: şifre kutusuna yazılan şifre yalnızca bu süreçte bellekte tutulur; panel yeniden açılınca şifre gereken kamera
# (sifre_degiskeni ortam değişkeni yoksa) "şifre bekleniyor" olarak kalır.

EN_COK_CANLI = max(1, int(os.environ.get("RAF_EN_COK_CANLI") or 8))  # aynı anda en çok canlı kamera (işlemci sınırı)
IZLEME_ARA_SN = 300.0     # kendiliğinden başlatma başarısız olursa yeniden deneme aralığı
IZLEMELER: dict[str, Is] = {}
_IZLEME_KILIDI = threading.Lock()
_SIFRELER: dict[str, str] = {}          # kod → şifre (yalnızca bellek)
_IZLEME_DURUMU: dict[str, dict] = {}    # kod → {"son_deneme": zaman, "bekleme": neden}
CANLI_TURLER = ("rtsp", "onvif", "http")


def _izleme_dosyasi() -> Path:
    return yollar.VERI / "izleme.json"


def istenen_izlemeler() -> list[str]:
    """İzlenmesi istenen ve ayarı hâlâ duran kameralar."""
    try:
        liste = json.loads(_izleme_dosyasi().read_text(encoding="utf-8")).get("kameralar") or []
    except (OSError, ValueError, AttributeError):
        liste = []
    return [k for k in liste if isinstance(k, str) and KOD_RE.match(k) and ayar_yolu(k).exists()]


def izleme_istenir(kod: str, istenir: bool) -> None:
    with _IZLEME_KILIDI:
        try:
            liste = json.loads(_izleme_dosyasi().read_text(encoding="utf-8")).get("kameralar") or []
        except (OSError, ValueError, AttributeError):
            liste = []
        liste = [k for k in liste if k != kod] + ([kod] if istenir else [])
        yollar.VERI.mkdir(parents=True, exist_ok=True)
        gecici = _izleme_dosyasi().with_suffix(".json.tmp")
        gecici.write_text(json.dumps({"kameralar": liste}, ensure_ascii=False), encoding="utf-8")
        os.replace(gecici, _izleme_dosyasi())
    if not istenir:
        _SIFRELER.pop(kod, None)
        _IZLEME_DURUMU.pop(kod, None)


def izleme_calisiyor(kod: str) -> bool:
    i = IZLEMELER.get(kod)
    return i is not None and i.durum == "calisiyor"


def izleme_baslat(kod: str, sifre: str | None = None) -> tuple[bool, str]:
    """Kameranın canlı izlemesini kendi işiyle başlatır. Aynı kamera iki kez izlenmez; en çok EN_COK_CANLI kamera."""
    ayar = ayar_oku(kod)
    ad = ayar.get("ad", kod)
    if (ayar.get("kamera") or {}).get("tur") not in CANLI_TURLER:
        return False, "Canlı izleme IP kamera, kayıt cihazı ya da HTTP akışı içindir. Video dosyasında “Videoyu analiz et”i kullanın."
    with _IZLEME_KILIDI:
        if izleme_calisiyor(kod):
            return False, f"{ad} zaten izleniyor."
        calisan = sum(1 for i in IZLEMELER.values() if i.durum == "calisiyor")
        if calisan >= EN_COK_CANLI:
            return False, (f"Aynı anda en çok {EN_COK_CANLI} kamera canlı izlenebilir (bu bilgisayarın işlemcisi için). "
                           "Önce bir kameranın izlemesini durdurun.")
        is_ = Is("izle", f"İzleme · {ad}")
        is_.kod = kod
        # Çalışma saatinde mi başladı: istek anında karar verilir (iş parçacığı sahneyi kurarken saat kapanırsa izleme
        # "saat dışında başlatıldı" sanılıp kapanışta durmazdı; dene_panel_izleme bunu ara sıra yakalıyordu).
        import depo

        is_.saatte_basladi = depo.calisma_saatinde(dt.datetime.now())
        IZLEMELER[kod] = is_
    if sifre:
        _SIFRELER[kod] = sifre  # sabah yeniden başlatmak için yalnızca bellekte
    _IZLEME_DURUMU.setdefault(kod, {}).pop("bekleme", None)
    _is_calistir(is_, is_izle, kod, sifre if sifre is not None else _SIFRELER.get(kod), 0)
    return True, ""


def izleme_durdur(kod: str, istenmez: bool = True) -> bool:
    """Kameranın izlemesini durdurur. `istenmez`: kullanıcı durdurdu, sabah kendiliğinden başlamasın."""
    if istenmez:
        izleme_istenir(kod, False)
    i = IZLEMELER.get(kod)
    if i is not None and i.durum == "calisiyor":
        i.dur.set()
        print(f"Durdurma istendi: {i.baslik}", flush=True)
        return True
    return False


def _sifre_bekleniyor(kod: str, ayar: dict) -> str | None:
    import kamera

    if kod in _SIFRELER or not kamera.sifre_gerekli(ayar):
        return None
    degisken = (ayar.get("kamera") or {}).get("sifre_degiskeni", "KAMERA_SIFRE")
    if os.environ.get(degisken):
        return None
    return "Şifre bekleniyor: program yeniden açıldığı için kamera şifresini Kameralar ekranında yazıp izlemeyi başlatın."


def izleme_planla(simdi: dt.datetime | None = None) -> list[str]:
    """Çalışma saatindeyse izlenmesi istenen ama çalışmayan kameraları başlatır (sabah açılış, panelin yeniden açılması,
    hata sonrası IZLEME_ARA_SN aralıkla yeniden deneme). Dönüş: başlatılan kodlar."""
    import depo

    if GELISTIRME:
        return []
    simdi = simdi or dt.datetime.now()
    if not depo.calisma_saatinde(simdi):
        return []
    basladi = []
    for kod in istenen_izlemeler():
        if izleme_calisiyor(kod):
            continue
        d = _IZLEME_DURUMU.setdefault(kod, {})
        if time.time() - d.get("son_deneme", 0.0) < IZLEME_ARA_SN:
            continue
        try:
            ayar = ayar_oku(kod)
        except SystemExit:
            continue
        engel = _model_engeli() or _sifre_bekleniyor(kod, ayar)
        if engel:
            d["bekleme"] = engel
            continue
        d["son_deneme"] = time.time()
        ok, m = izleme_baslat(kod)
        if ok:
            basladi.append(kod)
            print(f"{ayar.get('ad', kod)}: izleme kendiliğinden başlatıldı (çalışma saati).", flush=True)
        else:
            d["bekleme"] = m
    return basladi


def izleme_dongusu(dur: threading.Event, ilk_sn: float = 5.0, aralik_sn: float = 30.0) -> None:
    """Arka plan: açılıştan kısa süre sonra ve sonra yarım dakikada bir izleme planını uygular."""
    bekle = ilk_sn
    while not dur.wait(bekle):
        bekle = aralik_sn
        try:
            izleme_planla()
        except Exception:
            traceback.print_exc(file=sys.__stderr__)


def izleme_durumlari() -> dict[str, dict]:
    """Ekran için kamera başına canlı izleme durumu: çalışan ya da istenen her kamera."""
    import depo

    istenen = set(istenen_izlemeler())
    saatte = depo.calisma_saatinde(dt.datetime.now())
    out = {}
    for kod in sorted(istenen | set(IZLEMELER)):
        i = IZLEMELER.get(kod)
        oz = i.ozet() if i else {}
        if oz:
            oz["satirlar"] = oz["satirlar"][-30:]
        bekleme = (_IZLEME_DURUMU.get(kod) or {}).get("bekleme")
        if kod in istenen and not izleme_calisiyor(kod) and not bekleme:
            bekleme = ("Çalışma saati dışında: açılışta kendiliğinden başlar." if not saatte else
                       "Kısa süre içinde yeniden denenecek." if oz.get("durum") == "hata" else "Başlatılıyor…")
        out[kod] = {**oz, "istenen": kod in istenen, "bekleme": bekleme if kod in istenen else None}
    return out


# ---------------------------------------------------------------- ayarlar


def sifreyi_temizle(ayar: dict) -> list[str]:
    """Ayar dosyasına şifre yazılmasın: şifre alanlarını siler, adresteki şifreyi {sifre} yapar."""
    notlar = []
    k = ayar.get("kamera")
    if isinstance(k, dict):
        for alan in list(k):
            if alan != "sifre_degiskeni" and re.search(r"sifre|şifre|password|pass$|parola", alan, re.I):
                del k[alan]
                notlar.append("Şifre alanı kaydedilmedi.")
        adres = k.get("adres")
        if isinstance(adres, str):
            m = re.search(r"://([^:/@]+):([^@]*)@", adres)
            if m and m.group(2) not in ("{sifre}", ""):
                k["adres"] = adres[:m.start(2)] + "{sifre}" + adres[m.end(2):]
                notlar.append("Adresteki şifre kaydedilmedi; yerine {sifre} yazıldı. Şifreyi çalışırken şifre kutusuna yazın.")
    ayar.pop("sifre", None)
    return notlar


def model_kilidi() -> dict:
    """Model paketinin durumu. Panel modeli açmaz: korumalı paket yalnızca AugeLab Studio'nun içinde, etkin lisansla açılır."""
    import kurallar
    import studio_kurulum

    if not yollar.DONDURULMUS:
        return kurallar.model_kilidi(str(yollar.MODELLER))
    if not studio_kurulum.model_gerekli():  # düz derleme ya da indirilecek model yok: modeller (varsa) programla gelir
        return kurallar.model_kilidi(str(yollar.PAKET_MODELLER))
    # Exe, korumalı paket: işaret ve DLL programla gelen kopyadan; modeller veri klasöründen ve yalnızca bu süreçte
    # SHA-256 ile doğrulanmışsa (Studio'ya giden görünüm: studio_kurulum.motor_modelleri).
    from raf_motor import community_model as cm

    sonuc = {"paketli": True, "community": True}
    try:
        kimlik = cm._kimlik(yollar.PAKET_MODELLER)
        if not cm._dosya(yollar.PAKET_MODELLER, kimlik).is_file():
            raise cm.LisansHatasi(cm._MESAJ[1])
        if studio_kurulum.eksik_modeller():
            return dict(sonuc, durum="hazirlaniyor", mesaj="Modeller hazırlanıyor.")
        for m in studio_kurulum.MODELLER:
            if not studio_kurulum.korumali(m):  # yardımcı dosya (etiket-oku.txt): paket başlığı yok
                continue
            with studio_kurulum.model_yolu(m).open("rb") as f:
                if f.read(24) != cm.SIHIR + kimlik:
                    raise cm.LisansHatasi(cm._MESAJ[1])
    except (OSError, cm.LisansHatasi) as e:
        return dict(sonuc, durum="bozuk", mesaj=str(e) if isinstance(e, cm.LisansHatasi) else cm._MESAJ[1])
    return dict(sonuc, durum="studio_kosusunda_dogrulanir")


def _model_var() -> bool:
    """Bütün modeller kullanılabilir mi (exe'de korumalı pakette: bu süreçte doğrulanmış model dosyaları).
    Hiç model tanımlı değilse True: bu sürümde analiz modelsiz iskelettir."""
    import kurallar
    import studio_kurulum

    if not yollar.DONDURULMUS:
        return not kurallar.eksik_dosyalar(str(yollar.MODELLER))
    if studio_kurulum.model_gerekli():
        return not studio_kurulum.eksik_modeller()
    return not kurallar.eksik_dosyalar(str(yollar.PAKET_MODELLER))


def _model_indirme_engeli() -> str | None:
    """Korumalı paketin model dosyaları hazır değilse nedeni (doğrulanıyor, indiriliyor ya da indirilmesi gerekiyor)."""
    import studio_kurulum

    d = studio_kurulum.model_durumu()
    if not d["eksik"]:
        return None
    if d["asama"] == "dogrulaniyor":
        return "Modeller hazırlanıyor (dosyalar doğrulanıyor). Birkaç saniye sonra analizi yeniden başlatın."
    if d["asama"] == "indiriliyor":
        yuzde = round(100 * d["indirilen"] / d["toplam"]) if d["toplam"] else 0
        return f"Model indiriliyor ({d.get('ne') or 'model'}, %{yuzde}). İndirme bitince analizi yeniden başlatın."
    return (f"Modeller henüz indirilmedi (yaklaşık {max(1, round(d['boyut'] / 1e6))} MB). Sayfanın üstündeki “Yeniden dene” "
            "düğmesiyle indirin; indirme bitince analizi başlatın.")


def _model_engeli() -> str | None:
    """Analiz başlatılamıyorsa nedeni (model dosyası yok ya da paket bozuk); başlatılabiliyorsa None."""
    indirme = _model_indirme_engeli()
    if indirme:
        return indirme
    kilit = model_kilidi()
    if kilit["paketli"] and kilit["durum"] != "studio_kosusunda_dogrulanir":
        return kilit.get("mesaj") or "Model paketi açılamıyor."
    if not _model_var():
        return "Model dosyaları yerinde değil (motor/modeller). Programı yeniden kurun."
    return None


def durum() -> dict:
    import depo
    import kamera
    import rapor
    import studio_kurulum

    kameralar = rapor.kameralar()
    for k in kameralar:
        try:
            k["sifre"] = kamera.sifre_gerekli(ayar_oku(k["kod"]))
        except SystemExit:
            k["sifre"] = False
    son_olay = depo.sor("SELECT COALESCE(MAX(id), 0) AS n FROM olay")[0]["n"]
    return {
        # veri klasörünün yolu gönderilmez (kullanıcı adını taşır; arayüz göstermiyor, "Veri klasörü" düğmesi sunucuda açar)
        "uygulama": yollar.UYGULAMA, "surum": yollar.SURUM,
        "model": _model_var(), "model_kilidi": yollar.gizle_her(model_kilidi()), "gelistirme": GELISTIRME,
        "ornek_var": bool(yollar.ornek_kodlar()), "kameralar": kameralar, "genel": depo.genel(), "dinlenen": DINLENEN,
        "is": AKTIF.ozet() if AKTIF else None, "studio": yollar.gizle_her(studio_durumu()), "son_kritik": rapor.son_kritik(), "son_olay": son_olay,
        "acik_gorev": depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE durum != 'kapandi'")[0]["n"],
        "izlemeler": izleme_durumlari(), "en_cok_canli": EN_COK_CANLI,
        "ornek_videolar": [{"kod": k, "ad": a} for k, a in yollar.ORNEK_ADLARI.items() if k in yollar.ornek_kodlar()],
        "studio_kurulu": (studio_kurulum.kurulu_studio() is not None) if not GELISTIRME else False,
        "studio_kurulum": yollar.gizle_her(studio_kurulum.durum()), "hesap_url": studio_kurulum.HESAP_URL,
        "model_indirme": yollar.gizle_her(studio_kurulum.model_durumu()), "ornek_veri": ornek_veri_durumu(),
        "calisma_saatinde": depo.calisma_saatinde(dt.datetime.now()), "simdi": depo.simdi(),
    }


_STUDIO = {"an": 0.0, "durum": None, "yokluyor": False}
_STUDIO_KILIDI = threading.Lock()


def _studio_yokla() -> None:
    try:
        import studio

        d = _studio(studio.durum())
        _STUDIO["durum"] = {"bagli": d.get("hazir") is True, "kurulu": True, **d}
    except Exception as e:
        _STUDIO["durum"] = {"bagli": False, "kurulu": False, "mesaj": str(e)[:200]}
    finally:
        _STUDIO["an"] = time.time()
        _STUDIO["yokluyor"] = False


def studio_durumu() -> dict:
    """AugeLab Studio arayüzsüz çalışmaya hazır mı (kurulu ve deneme geçti). Yoklama arka planda yapılır ve Studio'yu
    çalıştırmaz; bu işlev hiç beklemez ve son bilinen durumu döndürür. Geliştirme kipinde hiç yoklanmaz."""
    if GELISTIRME:
        return {"bagli": False, "kurulu": False, "gelistirme": True, "hazir": False, "mesaj": MOTOR_KAPALI}
    with _STUDIO_KILIDI:
        if not _STUDIO["yokluyor"] and time.time() - _STUDIO["an"] > 5:
            _STUDIO["yokluyor"] = True
            threading.Thread(target=_studio_yokla, daemon=True, name="studio-yoklama").start()
    return _STUDIO["durum"] or {"bagli": False, "yoklaniyor": True, "mesaj": "AugeLab Studio yoklanıyor…"}


def katalog() -> dict:
    import baglanti
    import kamera
    import kurallar

    # modeli eksik kurallar panelde işaretlenir (kaynak koddan: motor/modeller'deki dosyalar)
    eksik = kurallar.eksik_modeller(str(yollar.MODELLER if not yollar.DONDURULMUS else yollar.PAKET_MODELLER))
    if yollar.DONDURULMUS and not _model_var():
        eksik = {k["kod"]: (k.get("modeller") or ["model"])[0] for k in kurallar.KURALLAR if k.get("modeller")}
    return {
        "kurallar": [{**k, "model_eksik": eksik[k["kod"]]} if k["kod"] in eksik else k for k in kurallar.KURALLAR],
        # sözleşmedeki kategori ve bölge türleri katalogda henüz yoksa panelin bildiği adlarla eklenir
        "kategoriler": {"raf": "Raf", "musteri": "Müşteri", "operasyon": "Operasyon", "birlikte": "Raf ve müşteri", **kurallar.KATEGORILER},
        "bolge_turleri": {**BOLGE_TURLERI, **{k: v for k, v in kurallar.BOLGE_TURLERI.items() if k in BOLGE_TURLERI}},
        "motor_isleri": MOTOR_ISLERI, "disa_tablolar": {"tukenmeler": "Stok tükenmeleri", "gorevler": "Görevler ve tepki süreleri",
                                                       "kayip-satis": "Ürüne göre kayıp satış (tahmin)", "trafik": "Saatlik trafik", "olaylar": "Uyarılar"},
        "hassasiyetler": getattr(kurallar, "HASSASIYET_ADLARI", {}), "varsayilan_hassasiyet": getattr(kurallar, "VARSAYILAN_HASSASIYET", None),
        "durumlar": {"hazir": "Hazır", "sinirli": "Sınırlı", "deneysel": "Deneysel", **getattr(kurallar, "DURUMLAR", {})},
        "markalar": {k: v["ad"] for k, v in kamera.MARKALAR.items()},
        "baglanti_turleri": baglanti.TURLER, "api": API_UCLARI,
    }


# ---------------------------------------------------------------- ürün kataloğu (motor okur: <VERI>/urunler/)

GORSEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}\.jpg$")
EN_COK_GORSEL = 12


def urun_kaydet(g: dict, ornek: bool = False) -> dict:
    """Ürün ekler ya da düzenler. Görseller burada değişmez (ayrı istekle eklenir / silinir)."""
    import depo

    ad = str(g.get("ad") or "").strip()[:80]
    if not ad:
        raise AyarHatasi("Ürün adını yazın.")
    barkod = str(g.get("barkod") or "").strip()[:32]
    if barkod and not re.match(r"^[0-9A-Za-z-]{4,32}$", barkod):
        raise AyarHatasi("Barkod yalnızca rakam ve harf içerebilir (4-32 karakter).")
    fiyat = g.get("fiyat")
    fiyat = None if fiyat in (None, "") else round(_sayi(str(fiyat).replace(",", "."), "Fiyat", 0, 999999), 2)
    kategori = str(g.get("kategori") or "").strip()[:40]
    with depo._URUN_KILIDI:
        liste = depo.urunler()
        if barkod and any(u.get("barkod") == barkod and u["kimlik"] != g.get("kimlik") for u in liste):
            raise AyarHatasi(f"Bu barkodla başka bir ürün var ({barkod}).")
        if g.get("kimlik"):
            u = next((u for u in liste if u["kimlik"] == g["kimlik"]), None)
            if u is None:
                raise AyarHatasi("Ürün bulunamadı.")
            u.update(ad=ad, barkod=barkod, kategori=kategori, fiyat=fiyat)
        else:
            u = {"kimlik": depo.yeni_urun_kimligi(liste), "ad": ad, "barkod": barkod, "kategori": kategori, "fiyat": fiyat, "gorseller": []}
            if ornek:
                u["ornek"] = True
            liste.append(u)
        depo.urunleri_yaz(liste)
    return u


def urun_kullanimi(kimlik: str) -> list[str]:
    """Ürünün planogramda geçtiği kameralar (ad · bölge)."""
    import rapor

    return sorted({f"{t['kamera_ad']} · {t['bolge_ad']}" for t in rapor.goz_tanimlari().values() if t.get("urun") == kimlik})


def urun_sil(kimlik: str) -> None:
    import depo

    yerler = urun_kullanimi(kimlik)
    if yerler:
        raise AyarHatasi("Ürün planogramda kullanılıyor: " + ", ".join(yerler) + ". Önce bu gözlerden kaldırın.")
    with depo._URUN_KILIDI:
        liste = depo.urunler()
        u = next((u for u in liste if u["kimlik"] == kimlik), None)
        if u is None:
            raise AyarHatasi("Ürün bulunamadı.")
        depo.urunleri_yaz([x for x in liste if x["kimlik"] != kimlik])
    for dosya in u.get("gorseller") or []:
        if GORSEL_RE.match(dosya):
            (depo.gorsel_klasoru() / dosya).unlink(missing_ok=True)


def _bolge_icinde(x: float, y: float, poly: list) -> bool:
    ic = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            ic = not ic
        j = i
    return ic


def _kamera_karesi(kod: str, ham_izinli: bool = False) -> Path | None:
    """Kameranın çizimsiz karesi: motorun temiz karesi (yüzler gizli, çizim yok), yoksa referans karesi; `ham_izinli` ise en son
    bağlantı denemesinin karesi (bölge çizme karesi; yalnızca raf bölgesi içinden kırpmak ya da motora girdi için).
    son_kare.jpg kullanılmaz: üstünde motorun çizimleri vardır."""
    for yol in (yollar.CIKTI / kod / "temiz_kare.jpg", yollar.AYAR / f"_referans_{kod}.jpg") + ((yollar.AYAR / f"_kare_{kod}.jpg",) if ham_izinli else ()):
        if yol.is_file():
            return yol
    return None


def _goruntu_oku(veri: bytes):
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(veri, np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 16 or img.shape[1] < 16:
        raise AyarHatasi("Görüntü okunamadı (JPEG ya da PNG seçin).")
    return img


def urun_gorseli_ekle(g: dict) -> dict:
    """Ürüne referans görsel ekler: kameranın karesinden (yalnızca raf / dolap bölgesinin içinden) ya da yüklenen fotoğraftan
    kırpılır, en çok 480 piksele küçültülür. Panel modeli yüklemez; gömmeyi motor kendisi hesaplar."""
    import base64

    import cv2

    import depo

    kimlik = str(g.get("kimlik") or "")
    if not any(u["kimlik"] == kimlik for u in depo.urunler()):
        raise AyarHatasi("Ürün bulunamadı.")
    kutu = _kutu(g["kutu"], "Kırpma") if g.get("kutu") else None
    if g.get("kaynak") == "kamera":
        kod = str(g.get("kod") or "")
        if not KOD_RE.match(kod) or not ayar_yolu(kod).exists():
            raise AyarHatasi("Kamera bulunamadı.")
        if kutu is None:
            raise AyarHatasi("Karede ürünün çevresine bir kutu çizin.")
        ayar = ayar_oku(kod)
        x, y = (kutu[0] + kutu[2]) / 2, (kutu[1] + kutu[3]) / 2
        if not any(b.get("tur") in GOZLU_TURLER and _bolge_icinde(x, y, b.get("poly") or []) for b in ayar.get("bolgeler") or []):
            raise AyarHatasi("Ürün görseli yalnızca raf ya da soğutucu dolap bölgesinin içinden kırpılabilir. Önce raf bölgesini çizin.")
        kare = _kamera_karesi(kod, ham_izinli=True)
        if kare is None:
            raise AyarHatasi("Bu kameranın karesi yok. Kameralar ekranında “Bağlantıyı dene” ile bir kare alın.")
        img = _goruntu_oku(kare.read_bytes())
    elif g.get("kaynak") == "dosya":
        veri = str(g.get("veri") or "")
        if "," in veri[:80]:
            veri = veri.split(",", 1)[1]
        try:
            ham = base64.b64decode(veri, validate=True)
        except ValueError:
            raise AyarHatasi("Fotoğraf okunamadı.") from None
        if len(ham) > 3_500_000:
            raise AyarHatasi("Fotoğraf çok büyük (en çok 3,5 MB).")
        img = _goruntu_oku(ham)
    else:
        raise AyarHatasi("Görselin kaynağı seçilmedi.")
    yuk, gen = img.shape[:2]
    if kutu:
        x1, y1, x2, y2 = int(kutu[0] * gen), int(kutu[1] * yuk), int(kutu[2] * gen), int(kutu[3] * yuk)
        img = img[y1:max(y1 + 2, y2), x1:max(x1 + 2, x2)]
    olcek = 480 / max(img.shape[:2])
    if olcek < 1:
        img = cv2.resize(img, (max(2, int(img.shape[1] * olcek)), max(2, int(img.shape[0] * olcek))), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise AyarHatasi("Görsel kaydedilemedi.")
    with depo._URUN_KILIDI:
        liste = depo.urunler()
        u = next(u for u in liste if u["kimlik"] == kimlik)
        gorseller = list(u.get("gorseller") or [])
        if len(gorseller) >= EN_COK_GORSEL:
            raise AyarHatasi(f"Bir ürüne en çok {EN_COK_GORSEL} görsel eklenir. Önce birini silin.")
        n = 1
        while f"{kimlik}_{n}.jpg" in gorseller or (depo.gorsel_klasoru() / f"{kimlik}_{n}.jpg").exists():
            n += 1
        dosya = f"{kimlik}_{n}.jpg"
        depo.gorsel_klasoru().mkdir(parents=True, exist_ok=True)
        (depo.gorsel_klasoru() / dosya).write_bytes(jpg.tobytes())
        u["gorseller"] = gorseller + [dosya]
        depo.urunleri_yaz(liste)
    return u


def urun_gorseli_sil(kimlik: str, dosya: str) -> dict:
    import depo

    with depo._URUN_KILIDI:
        liste = depo.urunler()
        u = next((u for u in liste if u["kimlik"] == kimlik), None)
        if u is None or dosya not in (u.get("gorseller") or []):
            raise AyarHatasi("Görsel bulunamadı.")
        u["gorseller"] = [d for d in u["gorseller"] if d != dosya]
        depo.urunleri_yaz(liste)
    if GORSEL_RE.match(dosya):
        (depo.gorsel_klasoru() / dosya).unlink(missing_ok=True)
    return u


def referans_kaydet(kod: str) -> dict:
    """"Rafı dolu olarak kaydet": motorun temiz karesini (temiz_kare.jpg: yüzler gizli, çizim yok) referans kare olarak saklar
    ve kamera ayarına zamanını yazar. son_kare.jpg (üstünde motorun çizimleri var) ve bağlantı denemesinin ham karesi (yüzleri
    gizlenmemiş) referans olamaz."""
    import depo

    if not KOD_RE.match(kod) or not ayar_yolu(kod).exists():
        raise AyarHatasi("Kamera bulunamadı.")
    kaynak = yollar.CIKTI / kod / "temiz_kare.jpg"
    if not kaynak.is_file():
        raise AyarHatasi("Motorun temiz karesi (yüzleri gizlenmiş, çizimsiz) yok. Referans bu kareden alınır: "
                         "rafı doldurup analizi kısa bir süre çalıştırın, sonra yeniden deneyin.")
    with _AYAR_KILIDI:
        gecici = yollar.AYAR / f"._referans_{kod}.tmp"
        shutil.copyfile(kaynak, gecici)
        os.replace(gecici, yollar.AYAR / f"_referans_{kod}.jpg")
        # o karedeki kişi kutuları (motor yazar): koridor referansında bu kutuların altı kişisiz görülünce öğrenilir
        kisiler = yollar.CIKTI / kod / "temiz_kare.json"
        if kisiler.is_file():
            shutil.copyfile(kisiler, yollar.AYAR / f"_referans_{kod}.json")
        else:
            (yollar.AYAR / f"_referans_{kod}.json").unlink(missing_ok=True)
        ayar = ayar_oku(kod)
        ayar["referans"] = {"zaman": depo.simdi()}
        gecici = yollar.AYAR / f".{kod}.json.tmp"
        gecici.write_text(json.dumps(ayar, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, ayar_yolu(kod))
    return ayar["referans"]


# ---------------------------------------------------------------- tek seferlik motor işleri (Studio içinde koşar)

MOTOR_ISLERI = {"gozler": "Gözleri otomatik bul", "etiketler": "Fiyat etiketlerini oku", "urun_tani": "Gözlerdeki ürünleri tanı"}
MOTOR_IS_SINIRI = 180.0


def _motor_girdisi(ad: str, kod: str, g: dict) -> dict:
    ayar = ayar_oku(kod)
    if ad == "gozler":
        bolgeler = [{"kimlik": b["kimlik"], "poly": b["poly"]} for b in ayar.get("bolgeler") or [] if b.get("tur") in GOZLU_TURLER and b.get("kimlik")]
        if g.get("bolge"):
            bolgeler = [b for b in bolgeler if b["kimlik"] == g["bolge"]]
        if not bolgeler:
            raise AyarHatasi("Önce raf bölgesini çizip kaydedin.")
        return {"bolgeler": bolgeler}
    kutular = g.get("kutular")
    if kutular is None:  # verilmezse kameradaki bütün gözler (etiketlerde etiket kutuları)
        alan = "etiket" if ad == "etiketler" else "kutu"
        kutular = [gz[alan] for b in ayar.get("bolgeler") or [] for gz in b.get("gozler") or [] if gz.get(alan)]
    if not isinstance(kutular, list) or not kutular or len(kutular) > 500:
        raise AyarHatasi("Okunacak kutu yok. Önce gözleri (etiket okumada etiket kutularını) çizip kaydedin.")
    return {"kutular": [_kutu(k, "Kutu") for k in kutular]}


def _motor_sonucu(ad: str, sonuc) -> dict:
    """Motorun çıktısını denetler (sözleşme 5. bölüm); biçim bozuksa Türkçe hata."""
    def kutu(k):
        try:
            return _kutu(k, "Motor kutusu")
        except AyarHatasi:
            return None

    if not isinstance(sonuc, dict):
        raise SystemExit("Analiz motorunun sonucu okunamadı.")
    if sonuc.get("hata"):
        raise SystemExit(f"Analiz motoru işi yapamadı: {sonuc['hata']}")
    if ad == "gozler":
        out = [{"bolge": str(x.get("bolge") or ""), "kutu": kutu(x.get("kutu")), "skor": x.get("skor"), "etiket": kutu(x["etiket"]) if x.get("etiket") else None}
               for x in sonuc.get("gozler") or [] if isinstance(x, dict)]
        return {"gozler": [x for x in out if x["kutu"]]}
    if ad == "etiketler":
        return {"etiketler": [{"kutu": kutu(x.get("kutu")), "metin": str(x.get("metin") or "")[:80], "fiyat": x.get("fiyat") if isinstance(x.get("fiyat"), (int, float)) else None}
                              for x in sonuc.get("etiketler") or [] if isinstance(x, dict)]}
    return {"urunler": [{"kutu": kutu(x.get("kutu")), "urun": x.get("urun") or None, "benzerlik": x.get("benzerlik")}
                        for x in sonuc.get("urunler") or [] if isinstance(x, dict)]}


def is_motor(is_: Is, ad: str, kod: str, girdi: dict, sinir_sn: float = MOTOR_IS_SINIRI) -> dict:
    """Tek seferlik motor işi: sahne kendi kendini sınama düzeniyle (--step, kamera kodu `_gorev`) çalışır; motor sonucu
    RAF_GOREV_CIKTI dosyasına bırakır. Süre dolarsa ya da sonuç yoksa iş Türkçe bir hatayla biter."""
    import secrets as _s
    import subprocess

    import studio

    kare = _kamera_karesi(kod, ham_izinli=True)
    if kare is None:
        raise SystemExit("Bu kameranın karesi yok. Kameralar ekranında “Bağlantıyı dene” ile bir kare alın.")
    studio.KOSU_KLASORU.mkdir(parents=True, exist_ok=True)
    giris, cikis = studio.KOSU_KLASORU / f"gorev-{ad}-girdi.json", studio.KOSU_KLASORU / f"gorev-{ad}-cikti.json"
    cikis.unlink(missing_ok=True)
    giris.write_text(json.dumps({"kare": str(kare), **girdi}, ensure_ascii=False), encoding="utf-8")
    print(f"{MOTOR_ISLERI[ad]}: AugeLab Studio'da arayüzsüz çalışıyor…", flush=True)
    try:
        k = studio.baslat("_gorev", _s.token_hex(4), adim=3, ek_ortam={"RAF_GOREV": ad, "RAF_GOREV_GIRDI": str(giris), "RAF_GOREV_CIKTI": str(cikis)})
    except studio.StudioHatasi as e:
        raise SystemExit(str(e)) from None
    try:
        k.surec.wait(sinir_sn)
    except subprocess.TimeoutExpired:
        k.bitir(0)
        raise SystemExit(f"Analiz motoru işi {int(sinir_sn)} saniyede bitirmedi. AugeLab Studio'nun kurulu ve lisanslı olduğunu kontrol edin.") from None
    finally:
        studio.KOSULAR.pop("_gorev", None)
    if not cikis.is_file():
        raise SystemExit(f"Analiz motoru sonuç bırakmadı ({k.sorun() or 'motor bu işi henüz desteklemiyor olabilir'}).")
    try:
        sonuc = json.loads(cikis.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit("Analiz motorunun sonucu okunamadı.") from None
    out = _motor_sonucu(ad, sonuc)
    print("Bitti.", flush=True)
    return {"motor": ad, "kod": kod, **out}


# ---------------------------------------------------------------- örnek veriler ("Örnek verilerle dene")


def _ornek_modulu():
    """ornek_uretici.py (programla paketlenir): örnek verileri gerçek yollardan (kuyruk kayıtları + ayar dosyaları) üretir."""
    import ornek_uretici

    return ornek_uretici


def is_ornek_veri(is_: Is) -> dict:
    ov = _ornek_modulu()
    ozet = ov.yukle(ayar_kaydet=ayar_kaydet, urun_kaydet=urun_kaydet, gorsel_ekle=urun_gorseli_ekle, yaz=lambda s: print(s, flush=True))
    return {"git": "#/", "ozet": ozet}


def ornek_veri_kaldir() -> dict:
    """Örnek verileri kaldırır: yalnızca örnek işaretli satırlar (ornek = 1), örnek önekli ve örnek işaretli kamera
    ayarları, örnek işaretli ürünler ve görselleri. Gerçek kayıtlara dokunulmaz; gerçek bir gözde örnek ürün seçilmişse
    o gözün ürünü boşaltılır (göz silinmez)."""
    import depo

    depo.ornekleri_sil()
    kameralar = []
    for yol in sorted(yollar.AYAR.glob(f"{depo.ORNEK_ON}*.json")) if yollar.AYAR.is_dir() else []:
        try:
            a = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(a, dict) and a.get("ornek") is True and depo.ornek_kamera(a.get("kod") or yol.stem):
            kod = yol.stem
            yol.unlink(missing_ok=True)
            for f in (f"_kare_{kod}.jpg", f"_referans_{kod}.jpg", f"_referans_{kod}.json"):
                (yollar.AYAR / f).unlink(missing_ok=True)
            if KOD_RE.match(kod):
                shutil.rmtree(yollar.CIKTI / kod, ignore_errors=True)
            kameralar.append(kod)
    with depo._URUN_KILIDI:
        liste = depo.urunler()
        silinen = [u for u in liste if u.get("ornek") is True]
        if silinen:
            depo.urunleri_yaz([u for u in liste if u.get("ornek") is not True])
    for u in silinen:
        for dosya in u.get("gorseller") or []:
            if GORSEL_RE.match(dosya):
                (depo.gorsel_klasoru() / dosya).unlink(missing_ok=True)
    kimlikler = {u["kimlik"] for u in silinen}
    if kimlikler:  # gerçek kameralarda örnek ürüne bağlanmış gözler
        for yol in yollar.AYAR.glob("*.json"):
            try:
                a = json.loads(yol.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            degisti = False
            for b in a.get("bolgeler") or [] if isinstance(a, dict) else []:
                for gz in b.get("gozler") or []:
                    if gz.get("urun") in kimlikler:
                        gz["urun"] = None
                        degisti = True
            if degisti:
                with _AYAR_KILIDI:
                    yol.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    g = depo.genel()
    if g.get("ornek_veri"):
        ek = {"ornek_veri": None}
        once = (g.get("ornek_veri") or {}).get("onceki_tesis")
        if g.get("tesis") == "Örnek Market" and once:  # örnek yüklenirken verilen mağaza adı geri alınır
            ek["tesis"] = once
        depo.genel_yaz(ek)
    return {"kameralar": kameralar, "urunler": len(silinen)}


def ornek_veri_durumu() -> dict:
    import depo

    g = depo.genel()
    sayilar = depo.ornek_sayilari()
    kameralar = sorted(p.stem for p in yollar.AYAR.glob(f"{depo.ORNEK_ON}*.json")) if yollar.AYAR.is_dir() else []
    return {"yuklu": bool(kameralar or any(sayilar.values()) or any(u.get("ornek") for u in depo.urunler())),
            "kameralar": kameralar, "sayilar": sayilar, "zaman": (g.get("ornek_veri") or {}).get("zaman")}


# ---------------------------------------------------------------- dış sistemler için API (yalnızca okuma)

API_UCLARI = {
    "/api/v1/ozet": "Olay sayıları, açık ve süren uyarılar, günlük seri (gun | bas, bit)",
    "/api/v1/olaylar": "Olay listesi (gun | bas, bit, kamera, kategori, kural, durum, duzey, vardiya, ciddi=1: yalnız kritik, sinir)",
    "/api/v1/olaylar.csv": "Aynı liste CSV olarak (Excel, Power BI)",
    "/api/v1/olay/<no>": "Tek olay",
    "/api/v1/rapor": "Kural / kamera / vardiya / bölge kırılımları ve eğilim (gun | bas, bit)",
    "/api/v1/analitik": "Bir kameranın ölçüm sayıları ve ısı haritası katmanları (kamera, gun | bas, bit)",
    "/api/v1/kameralar": "Kameralar ve son durumları",
    "/api/v1/gorevler": "Görevler ve doğrulama durumları",
    "/api/v1/medya/<yol>": "Olayın klibi ya da karesi (olaydaki klip / kare alanı)",
    "/api/v1/genel-bakis": "Şu anki raf durumu, dönem sayıları, dikkat isteyenler (gun | bas, bit)",
    "/api/v1/raflar": "Bir kameranın bölgeleri ve gözleri: durum, doluluk, etiket, kayıp satış tahmini (kamera, gun | bas, bit)",
    "/api/v1/urunler": "Ürün kataloğu, yerleri ve dönem ölçüleri (gun | bas, bit)",
    "/api/v1/musteri": "Huni, bekleme, bölgeler, giriş-çıkış, toplu demografi tahmini (kamera, gun | bas, bit)",
    "/api/v1/disa/<tablo>.csv": "Tablolar CSV olarak: tukenmeler, gorevler, kayip-satis, trafik, olaylar (gun | bas, bit)",
}
CSV_ALANLARI = ("id", "zaman", "kamera", "kamera_ad", "kural", "kural_ad", "kategori", "duzey", "bolge", "vardiya", "onem", "olasilik", "puan",
                "sure_sn", "durum", "ustlenen", "notlar", "klip", "kare")


def api_v1(yol: str, q: dict):
    """Dönüş: ("json", veri) | ("csv", metin) | ("dosya", Path) | None."""
    import depo
    import rapor

    uc = yol[len("/api/v1"):].rstrip("/")
    if uc == "":
        return "json", {"uygulama": yollar.UYGULAMA, "surum": yollar.SURUM, "uclar": API_UCLARI}
    if uc == "/ozet":
        return "json", rapor.ozet(q)
    if uc in ("/olaylar", "/olaylar.csv"):
        d = rapor.olaylar({"sinir": 1000, **q})
        if uc == "/olaylar":
            return "json", d
        tampon = io.StringIO()
        yaz = csv.writer(tampon, delimiter=";", lineterminator="\n")
        yaz.writerow(CSV_ALANLARI)
        for o in d["olaylar"]:
            yaz.writerow(["" if o.get(a) is None else o[a] for a in CSV_ALANLARI])
        return "csv", tampon.getvalue()
    if uc.startswith("/olay/"):
        try:
            o = depo.sor("SELECT * FROM olay WHERE id = ?", int(uc[len("/olay/"):]))
        except ValueError:
            o = []
        return ("json", o[0]) if o else None
    if uc == "/rapor":
        return "json", rapor.rapor(q)
    if uc == "/analitik":
        return "json", rapor.analitik(q)
    if uc == "/kameralar":
        return "json", {"kameralar": rapor.kameralar()}
    if uc == "/gorevler":
        return "json", {"gorevler": rapor.gorevler()}
    if uc == "/genel-bakis":
        return "json", rapor.genel_bakis(q)
    if uc == "/raflar":
        return "json", rapor.raflar(q)
    if uc == "/urunler":
        return "json", rapor.urun_listesi(q)
    if uc == "/musteri":
        return "json", rapor.musteri(q)
    m = re.match(r"^/disa/([a-z-]+)\.csv$", uc)
    if m and m.group(1) in rapor.DISA_TABLOLAR:
        return "csv", rapor.disa_csv(m.group(1), q)
    if uc.startswith("/medya/"):
        hedef = (yollar.CIKTI / uc[len("/medya/"):]).resolve()
        if yollar.CIKTI.resolve() in hedef.parents and hedef.suffix.lower() in (".mp4", ".jpg"):
            return "dosya", hedef
    return None


# ---------------------------------------------------------------- HTTP


class Sunucu(ThreadingHTTPServer):
    allow_reuse_address = False  # Windows'ta aynı portu ikinci kez açmasın
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Istek(BaseHTTPRequestHandler):
    server_version = "RafKamera"
    sys_version = ""

    def log_message(self, *a):  # konsolu istek satırlarıyla doldurma
        pass

    # --- yardımcılar
    def _izinli(self) -> bool:
        """Arayüz ve bütün işlemler yalnızca bu bilgisayardan."""
        port = self.server.server_address[1]
        izinli = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.client_address[0] not in ("127.0.0.1", "::1") or self.headers.get("Host", "") not in izinli:
            return False
        koken = self.headers.get("Origin")
        if self.command == "POST" and koken is not None and koken not in {f"http://{h}" for h in izinli}:
            return False
        return True

    def _anahtarli(self) -> bool:
        """Ağdaki başka bir sistem: yalnızca ağ erişimi açıksa ve doğru API anahtarını gönderiyorsa."""
        import depo

        g = depo.genel()
        anahtar = g.get("api_anahtari") or ""
        if not g.get("ag_erisimi") or len(anahtar) < 20:
            return False
        gelen = self.headers.get("X-API-Key") or ""
        yetki = self.headers.get("Authorization") or ""
        if not gelen and yetki.lower().startswith("bearer "):
            gelen = yetki[7:].strip()
        return hmac.compare_digest(gelen.encode("utf-8"), anahtar.encode("utf-8"))

    def _v1(self, yol: str, q: dict):
        r = api_v1(yol, q)
        if r is None:
            return self._json({"hata": "Bulunamadı."}, 404)
        if r[0] == "json":
            return self._json(r[1])
        if r[0] == "csv":
            return self._gonder(200, ("\ufeff" + r[1]).encode("utf-8"), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="olaylar.csv"'})
        return self._dosya(r[1])

    def _gonder(self, kod: int, govde: bytes, tur: str, ek: dict | None = None):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (ek or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(govde)

    def _json(self, veri, kod: int = 200):
        # hata ve ileti metinleri tarayıcıya profil yolu (kullanıcı adı) taşımasın; veri alanlarına (ör. kameranın video
        # yolu, ayar ekranında düzenlenip geri kaydedilir) dokunulmaz
        if kod >= 400:
            veri = yollar.gizle_her(veri)
        elif isinstance(veri, dict) and any(isinstance(veri.get(a), str) for a in ("hata", "mesaj")):
            veri = {**veri, **{a: yollar.gizle(veri[a]) for a in ("hata", "mesaj") if isinstance(veri.get(a), str)}}
        self._gonder(kod, json.dumps(veri, ensure_ascii=False).encode("utf-8"), TURLER[".json"])

    def _yok(self):
        self._gonder(404, "Bulunamadı".encode("utf-8"), "text/plain; charset=utf-8")

    def _dosya(self, yol: Path):
        if not yol.is_file():
            return self._yok()
        tur = TURLER.get(yol.suffix.lower()) or mimetypes.guess_type(yol.name)[0] or "application/octet-stream"
        boyut = yol.stat().st_size
        aralik = self.headers.get("Range")
        bas, son = 0, boyut - 1
        kod = 200
        m = re.match(r"bytes=(\d*)-(\d*)$", aralik or "")
        if m and boyut > 0 and (m.group(1) or m.group(2)):
            if m.group(1):
                bas = int(m.group(1))
                son = min(int(m.group(2)), boyut - 1) if m.group(2) else boyut - 1
            else:
                bas = max(0, boyut - int(m.group(2)))
            if bas > son or bas >= boyut:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{boyut}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            kod = 206
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(son - bas + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if kod == 206:
            self.send_header("Content-Range", f"bytes {bas}-{son}/{boyut}")
        if yol.suffix.lower() == ".xlsx":
            self.send_header("Content-Disposition", f'attachment; filename="{yol.name}"')
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(yol, "rb") as f:
                f.seek(bas)
                kalan = son - bas + 1
                while kalan > 0:
                    parca = f.read(min(1 << 16, kalan))
                    if not parca:
                        break
                    self.wfile.write(parca)
                    kalan -= len(parca)
        except (ConnectionError, OSError):
            pass

    def _altinda(self, kok: Path, goreli: str):
        hedef = (kok / goreli).resolve()
        if kok.resolve() not in hedef.parents:
            return self._yok()
        return self._dosya(hedef)

    def _govde(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5_000_000:
            raise ValueError("istek çok büyük")
        veri = self.rfile.read(n) if n else b"{}"
        return json.loads(veri.decode("utf-8") or "{}")

    # --- GET
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        ayrik = urlparse(self.path)
        yol = unquote(ayrik.path)
        q = dict(parse_qsl(ayrik.query))
        if not self._izinli():
            if yol.startswith("/api/v1") and self._anahtarli():
                try:
                    return self._v1(yol, q)
                except SystemExit as e:
                    return self._json({"hata": str(e.code)}, 400)
                except Exception:
                    traceback.print_exc(file=sys.__stderr__)
                    return self._json({"hata": "Beklenmeyen hata."}, 500)
            return self._gonder(403, b"Forbidden", "text/plain")
        try:
            return self._get(yol, q)
        except SystemExit as e:
            return self._json({"hata": str(e.code)}, 400)
        except Exception as e:
            traceback.print_exc(file=sys.__stderr__)
            return self._json({"hata": f"Beklenmeyen hata: {e}"}, 500)

    def _get(self, yol: str, q: dict):
        import depo
        import rapor

        if yol in ("/", "/index.html"):
            return self._dosya(yollar.WEB / "index.html")
        if yol.startswith("/web/"):
            return self._altinda(yollar.WEB, yol[len("/web/"):])
        if yol == "/favicon.ico":
            return self._dosya(yollar.WEB / "favicon.ico")
        if yol.startswith("/api/v1"):
            return self._v1(yol, q)
        if yol == "/api/durum":
            return self._json(durum())
        if yol == "/api/katalog":
            return self._json(katalog())
        if yol == "/api/ozet":
            return self._json(rapor.ozet(q))
        if yol == "/api/olaylar":
            return self._json(rapor.olaylar(q))
        if yol == "/api/analitik":
            return self._json(rapor.analitik(q))
        if yol == "/api/rapor":
            return self._json(rapor.rapor(q))
        if yol == "/api/gorevler":
            return self._json(rapor.gorev_listesi(q))
        if yol == "/api/rapor.xlsx":
            return self._dosya(rapor.excel())
        if yol == "/api/genel-bakis":
            return self._json(rapor.genel_bakis(q))
        if yol == "/api/raflar":
            return self._json(rapor.raflar(q))
        if yol == "/api/goz":
            return self._json(rapor.goz_gecmisi(q))
        if yol == "/api/urunler":
            return self._json(rapor.urun_listesi(q))
        if yol == "/api/musteri":
            return self._json(rapor.musteri(q))
        if yol == "/api/rapor-ozeti":
            return self._json(rapor.rapor_ozeti(q))
        if yol == "/api/ara":
            return self._json(rapor.ara(q))
        if yol == "/api/ornek-veri":
            return self._json(ornek_veri_durumu())
        if yol.startswith("/api/urun-kullanimi/"):
            return self._json({"yerler": urun_kullanimi(yol.rsplit("/", 1)[-1])})
        m = re.match(r"^/api/disa/([a-z-]+)\.(csv|xlsx)$", yol)
        if m:
            ad, tur = m.groups()
            adlar = list(rapor.DISA_TABLOLAR) if ad == "hepsi" and tur == "xlsx" else [ad]
            if any(a not in rapor.DISA_TABLOLAR for a in adlar):
                return self._json({"hata": "Bilinmeyen tablo."}, 404)
            if tur == "xlsx":
                return self._dosya(rapor.disa_excel(adlar, q))
            bas, bit = rapor.aralik(q)
            return self._gonder(200, ("﻿" + rapor.disa_csv(ad, q)).encode("utf-8"), "text/csv; charset=utf-8",
                                {"Content-Disposition": f'attachment; filename="raf-kamera-{ad}-{bas[:10]}-{bit[:10]}.csv"'})
        if yol.startswith("/urunler/gorsel/"):
            import depo as _depo

            ad = yol[len("/urunler/gorsel/"):]
            return self._dosya(_depo.gorsel_klasoru() / ad) if GORSEL_RE.match(ad) else self._yok()
        if yol.startswith("/api/olay/"):
            try:
                o = depo.sor("SELECT * FROM olay WHERE id = ?", int(yol[len("/api/olay/"):]))
            except ValueError:
                o = []
            if not o:
                return self._json({"hata": "Olay bulunamadı."}, 404)
            return self._json(o[0])
        if yol.startswith("/api/ayar/"):
            kod = yol[len("/api/ayar/"):]
            if not KOD_RE.match(kod) or not ayar_yolu(kod).exists():
                return self._json({"hata": "Ayar bulunamadı."}, 404)
            return self._json(json.loads(ayar_yolu(kod).read_text(encoding="utf-8")))
        if yol.startswith("/ayar/"):
            ad = yol[len("/ayar/"):]
            if re.match(r"^_(kare|referans)_[a-z0-9_-]{1,40}\.jpg$", ad):  # yalnızca bölge çizme ve raf referans kareleri
                return self._dosya(yollar.AYAR / ad)
            return self._yok()
        if yol.startswith("/cikti/"):
            return self._altinda(yollar.CIKTI, yol[len("/cikti/"):])
        return self._yok()

    # --- POST
    def do_POST(self):
        if not self._izinli():
            return self._gonder(403, b"Forbidden", "text/plain")
        yol = urlparse(self.path).path
        try:
            g = self._govde()
        except Exception:
            return self._json({"hata": "İstek okunamadı."}, 400)
        if not isinstance(g, dict):
            return self._json({"hata": "İstek okunamadı."}, 400)
        try:
            return self._post(yol, g)
        except SystemExit as e:
            return self._json({"hata": str(e.code)}, 400)
        except AyarHatasi as e:
            return self._json({"hata": str(e)}, 400)
        except (ValueError, TypeError, KeyError):
            traceback.print_exc(file=sys.__stderr__)
            return self._json({"hata": "İstekteki bir değer okunamadı; hiçbir şey değiştirilmedi."}, 400)
        except Exception as e:
            traceback.print_exc(file=sys.__stderr__)
            return self._json({"hata": f"Beklenmeyen hata: {e}"}, 500)

    def _kod(self, g: dict) -> str:
        kod = str(g.get("kod", ""))
        if not KOD_RE.match(kod):
            raise SystemExit("Kısa kod yalnızca küçük harf (a-z), rakam, - ve _ içerebilir (ör. depo2).")
        return kod

    def _mesgul(self) -> bool:
        return AKTIF is not None and AKTIF.durum == "calisiyor"

    def _post(self, yol: str, g: dict):
        import depo

        if GELISTIRME and (yol in ("/api/studio/kur", "/api/studio/lisans", "/api/studio/dene", "/api/is/ornek", "/api/is/izle", "/api/is/video")
                           or yol.startswith("/api/motor/")):
            return self._json({"hata": MOTOR_KAPALI, "motor_yok": True}, 409)
        if yol.startswith("/api/motor/"):  # tek seferlik motor işi: göz önerme, etiket okuma, ürün tanıma
            ad = yol[len("/api/motor/"):]
            if ad not in MOTOR_ISLERI:
                return self._json({"hata": "Bilinmeyen iş."}, 404)
            engel = _model_engeli()
            if engel:
                return self._json({"hata": engel}, 409)
            kod = self._kod(g)
            if not ayar_yolu(kod).exists():
                return self._json({"hata": f"Ayar bulunamadı: {kod}"}, 404)
            girdi = _motor_girdisi(ad, kod, g)
            ok, m = is_baslat("motor", f"{MOTOR_ISLERI[ad]} · {ayar_oku(kod).get('ad', kod)}", is_motor, ad, kod, girdi)
            if not ok:
                return self._json({"hata": m}, 409)
            AKTIF.kod = kod
            return self._json({"tamam": True, "is": AKTIF.ozet()})
        if yol == "/api/urun":
            return self._json({"tamam": True, "urun": urun_kaydet(g)})
        if yol == "/api/urun/sil":
            urun_sil(str(g.get("kimlik") or ""))
            return self._json({"tamam": True})
        if yol == "/api/urun/gorsel":
            return self._json({"tamam": True, "urun": urun_gorseli_ekle(g)})
        if yol == "/api/urun/gorsel/sil":
            return self._json({"tamam": True, "urun": urun_gorseli_sil(str(g.get("kimlik") or ""), str(g.get("dosya") or ""))})
        if yol == "/api/ayar/referans":
            return self._json({"tamam": True, "referans": referans_kaydet(self._kod(g))})
        if yol == "/api/ornek-veri/yukle":
            if ornek_veri_durumu()["yuklu"]:
                return self._json({"hata": "Örnek veriler zaten yüklü. Yeniden yüklemek için önce kaldırın."}, 409)
            ok, m = is_baslat("ornek-veri", "Örnek veriler yükleniyor", is_ornek_veri)
            if not ok:
                return self._json({"hata": m}, 409)
            return self._json({"tamam": True, "is": AKTIF.ozet()})
        if yol == "/api/ornek-veri/kaldir":
            if self._mesgul() and AKTIF.tur == "ornek-veri":
                return self._json({"hata": "Örnek veriler yüklenirken kaldırılamaz; bitmesini bekleyin."}, 409)
            return self._json({"tamam": True, **ornek_veri_kaldir()})
        if yol == "/api/temizle":
            return self._json({"tamam": True, **depo.eskileri_temizle()})
        if yol in ("/api/is/ornek", "/api/is/izle", "/api/is/video"):  # bağlantı denemesi modeli kullanmaz
            engel = _model_engeli()
            if engel:
                return self._json({"hata": engel}, 409)
        if yol == "/api/studio/kur":
            import studio_kurulum

            ok, m = is_baslat("studio-kurulum", "AugeLab Studio kurulumu", studio_kurulum.kur)
        elif yol == "/api/studio/lisans":
            import studio
            import studio_kurulum

            if self._mesgul():
                return self._json({"hata": "Çalışan işlem bitince lisans kodunu girin."}, 409)
            try:
                studio_kurulum.lisans_kaydet(str(g.get("kod") or ""))  # kod saklanmaz, günlüğe yazılmaz
            except SystemExit as e:
                return self._json({"hata": str(e.code or "Lisans kodu kaydedilemedi.")}, 400)
            studio.kaydet(lisans=time.time(), hazir=None)
            _STUDIO["an"] = 0.0
            ok, m = is_baslat("studio-dene", "AugeLab Studio lisans kontrolü", is_studio_dene)
        elif yol == "/api/studio/dene":
            ok, m = is_baslat("studio-dene", "AugeLab Studio lisans kontrolü", is_studio_dene)
        elif yol == "/api/model/indir":  # arka planda indirilir; panelin işlerini bekletmez (ilerleme /api/durum'da)
            import studio_kurulum

            ok, m = studio_kurulum.model_indirmeyi_baslat()
        elif yol == "/api/is/ornek":
            secilen = [str(k) for k in g.get("kodlar") or [] if isinstance(k, str)] if isinstance(g.get("kodlar"), list) else None
            ok, m = is_baslat("ornek", "Örnek analiz", is_ornek, secilen)
        elif yol in ("/api/is/test", "/api/is/izle", "/api/is/video"):
            kod = self._kod(g)
            if not ayar_yolu(kod).exists():
                return self._json({"hata": f"Ayar bulunamadı: {kod}"}, 404)
            sifre = g.get("sifre")
            sifre = str(sifre) if sifre is not None else None
            ad = ayar_oku(kod).get("ad", kod)
            if yol == "/api/is/test":
                ok, m = is_baslat("test", f"Bağlantı denemesi · {ad}", is_test, kod, sifre)
            elif yol == "/api/is/video":
                ok, m = is_baslat("video", f"Video analizi · {ad}", is_video, kod)
            else:  # canlı izleme: kamera başına ayrı koşu (tek iş sırasına girmez)
                if (ayar_oku(kod).get("kamera") or {}).get("tur") not in CANLI_TURLER:
                    return self._json({"hata": "Canlı izleme IP kamera, kayıt cihazı ya da HTTP akışı içindir. Video dosyasında “Videoyu analiz et”i kullanın."}, 400)
                if not depo.calisma_saatinde(dt.datetime.now()):
                    c = depo.genel()["calisma"]
                    izleme_istenir(kod, True)
                    if sifre:
                        _SIFRELER[kod] = sifre  # yalnızca bellekte
                    return self._json({"tamam": True, "ileti": f"Çalışma saatleri dışında ({c['bas']}–{c['bit']}). İzleme açılışta kendiliğinden başlayacak."})
                ok, m = izleme_baslat(kod, sifre)
                if not ok:
                    return self._json({"hata": m}, 409)
                izleme_istenir(kod, True)
                return self._json({"tamam": True, "izleme": IZLEMELER[kod].ozet()})
        elif yol in ("/api/izleme/durdur", "/api/is/durdur") and g.get("kod"):
            kod = self._kod(g)
            izleme_durdur(kod)  # kullanıcı durdurdu: sabah kendiliğinden başlamaz
            return self._json({"tamam": True})
        elif yol == "/api/is/durdur":
            if self._mesgul():
                AKTIF.dur.set()
                print(f"Durdurma istendi: {AKTIF.baslik}", flush=True)
            return self._json({"tamam": True})
        elif yol == "/api/olay/durum":
            durum_ = str(g.get("durum", ""))
            if durum_ not in ("acik", "ustlenildi", "cozuldu", "yanlis"):
                return self._json({"hata": "Bilinmeyen durum."}, 400)
            kimlikler = [int(x) for x in (g.get("idler") or [g.get("id")]) if x is not None]
            for kimlik in kimlikler:
                depo.yaz("UPDATE olay SET durum = ?, ustlenen = COALESCE(?, ustlenen), notlar = COALESCE(?, notlar), durum_zamani = ? WHERE id = ?",
                         durum_, (str(g["ustlenen"])[:80] if g.get("ustlenen") else None), (str(g["not"])[:2000] if g.get("not") is not None else None),
                         depo.simdi(), kimlik)
            return self._json({"tamam": True})
        elif yol == "/api/gorev":
            baslik = str(g.get("baslik", "")).strip()[:200]
            if not baslik:
                return self._json({"hata": "Görevin başlığı yazılmamış."}, 400)
            durum_ = str(g.get("durum", "acik"))
            if durum_ not in ("acik", "suruyor", "kapandi"):
                return self._json({"hata": "Bilinmeyen durum."}, 400)
            son_tarih = str(g["son_tarih"])[:10] if g.get("son_tarih") else None
            if son_tarih:
                try:
                    dt.date.fromisoformat(son_tarih)
                except ValueError:
                    return self._json({"hata": "Son tarih okunamadı."}, 400)
            kamera_ = g.get("kamera") or None
            if kamera_ is not None and not KOD_RE.match(str(kamera_)):
                return self._json({"hata": "Kamera okunamadı."}, 400)
            alan = {"baslik": baslik, "aciklama": str(g.get("aciklama") or "")[:4000], "sorumlu": str(g.get("sorumlu") or "").strip()[:80],
                    "son_tarih": son_tarih, "durum": durum_, "kamera": kamera_, "kural": (str(g["kural"])[:40] if g.get("kural") else None),
                    "bolge": (str(g["bolge"])[:60] if g.get("bolge") else None), "notlar": str(g.get("notlar") or "")[:4000]}
            simdi_ = depo.simdi()
            if g.get("id"):
                kimlik = int(g["id"])
                eski = depo.sor("SELECT durum, kapanma, baslama, olusturma FROM gorev WHERE id = ?", kimlik)
                if not eski:
                    return self._json({"hata": "Görev bulunamadı."}, 404)
                e = eski[0]
                kapanma = e["kapanma"] if durum_ == "kapandi" and e["durum"] == "kapandi" else (simdi_ if durum_ == "kapandi" else None)
                baslama = e["baslama"] or (simdi_ if durum_ in ("suruyor", "kapandi") and e["durum"] == "acik" else None)
                tepki = None
                if kapanma:
                    try:
                        tepki = max(0.0, (dt.datetime.fromisoformat(kapanma) - dt.datetime.fromisoformat(e["olusturma"])).total_seconds())
                    except ValueError:
                        tepki = None
                depo.yaz("UPDATE gorev SET baslik=?, aciklama=?, sorumlu=?, son_tarih=?, durum=?, kamera=?, kural=?, bolge=?, notlar=?, kapanma=?, "
                         "baslama=?, tepki_sn=? WHERE id=?", *alan.values(), kapanma, baslama, tepki, kimlik)
            else:
                kimlik = depo.ekle("gorev", {**alan, "olusturma": simdi_, "kapanma": simdi_ if durum_ == "kapandi" else None,
                                             "baslama": simdi_ if durum_ != "acik" else None, "ornek": int(depo.ornek_kamera(kamera_))})
            for o in g.get("olaylar") or []:
                depo.yaz("INSERT OR IGNORE INTO gorev_olay (gorev, olay) VALUES (?, ?)", kimlik, int(o))
                depo.yaz("UPDATE olay SET durum = 'ustlenildi', ustlenen = COALESCE(NULLIF(?, ''), ustlenen), durum_zamani = ? WHERE id = ? AND durum = 'acik'",
                         alan["sorumlu"], depo.simdi(), int(o))
            return self._json({"tamam": True, "id": kimlik})
        elif yol == "/api/gorev/sil":
            depo.yaz("DELETE FROM gorev_olay WHERE gorev = ?", int(g.get("id", 0)))
            depo.yaz("DELETE FROM gorev WHERE id = ?", int(g.get("id", 0)))
            return self._json({"tamam": True})
        elif yol == "/api/genel":
            yeni = {}
            if isinstance(g.get("tesis"), str):
                yeni["tesis"] = g["tesis"].strip()[:80] or "Tesis"
            if isinstance(g.get("vardiyalar"), list):
                vs = []
                for v in g["vardiyalar"][:6]:
                    if re.match(r"^\d\d:\d\d$", str(v.get("bas", ""))) and re.match(r"^\d\d:\d\d$", str(v.get("bit", ""))) and str(v.get("ad", "")).strip():
                        vs.append({"ad": str(v["ad"]).strip()[:30], "bas": v["bas"], "bit": v["bit"]})
                if vs:
                    yeni["vardiyalar"] = vs
            if isinstance(g.get("baglantilar"), list):
                import baglanti

                yeni["baglantilar"] = [baglanti.temizle(x) for x in g["baglantilar"][:20] if isinstance(x, dict)]
            if "ag_erisimi" in g:
                yeni["ag_erisimi"] = bool(g["ag_erisimi"])
                if yeni["ag_erisimi"] and not depo.genel().get("api_anahtari"):
                    yeni["api_anahtari"] = secrets.token_urlsafe(32)
            if g.get("anahtar_yenile"):
                yeni["api_anahtari"] = secrets.token_urlsafe(32)
            for alan_, uzun in (("sube", 60), ("adres", 200)):
                if isinstance(g.get(alan_), str):
                    yeni[alan_] = g[alan_].strip()[:uzun]
            if isinstance(g.get("para_birimi"), str) and g["para_birimi"].strip():
                yeni["para_birimi"] = g["para_birimi"].strip()[:4]
            if "calisma" in g:
                c = g["calisma"] if isinstance(g["calisma"], dict) else {}
                if not all(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(c.get(a, ""))) for a in ("bas", "bit")):
                    return self._json({"hata": "Çalışma saatleri SS:DD biçiminde olmalı (ör. 08:00 ve 22:00)."}, 400)
                yeni["calisma"] = {"bas": c["bas"], "bit": c["bit"]}
            for alan_, ad_, en_az in (("saklama_gun", "Kayıt saklama süresi", 7), ("klip_gun", "Klip saklama süresi", 1)):
                if alan_ in g:
                    yeni[alan_] = _sayi(g[alan_], ad_ + " (gün)", en_az, 3650, tam=True)
            if yeni.get("klip_gun", depo.genel()["klip_gun"]) > yeni.get("saklama_gun", depo.genel()["saklama_gun"]):
                return self._json({"hata": "Klip saklama süresi, kayıt saklama süresinden uzun olamaz."}, 400)
            if isinstance(g.get("vardiyalar"), list) and "vardiyalar" not in yeni and g["vardiyalar"]:
                return self._json({"hata": "Vardiyaların adı, başlangıcı ve bitişi yazılmalı."}, 400)
            depo.genel_yaz(yeni)
            return self._json({"tamam": True, "genel": depo.genel()})
        elif yol == "/api/baglanti/dene":
            import baglanti

            tamam, mesaj = baglanti.dene(baglanti.temizle(g.get("baglanti") or {}))
            return self._json({"tamam": tamam, "mesaj": mesaj})
        elif yol == "/api/onvif/kesfet":  # ağdaki ONVIF kameraları ve kayıt cihazları (şifre gerekmez)
            import onvif_istemci

            return self._json({"cihazlar": onvif_istemci.kesfet(3.0)})
        elif yol == "/api/onvif/profiller":  # cihazın kanalları ve profilleri; şifre yalnızca bu istekte kullanılır, saklanmaz
            import onvif_istemci

            try:
                cihaz = onvif_istemci.Cihaz(str(g.get("ip") or "").strip(), int(g.get("port") or 80), str(g.get("kullanici") or "admin"), str(g.get("sifre") or ""))
                profiller = cihaz.profiller()
                return self._json({"cihaz": cihaz.bilgi(), "profiller": profiller})
            except (onvif_istemci.OnvifHatasi, ValueError) as e:
                return self._json({"hata": str(e)}, 400)
        elif yol == "/api/ayar/kanallar":  # kayıt cihazının kanalları ayrı kameralar olarak: ya hepsi eklenir ya hiçbiri
            try:
                return self._json({"tamam": True, **kameralari_olustur(kanal_ayarlari(g.get("taban"), g.get("kanallar"), g.get("profiller")))})
            except AyarHatasi as e:
                return self._json({"hata": str(e)}, 400)
        elif yol == "/api/ayar":
            try:
                if g.get("yeni"):  # yalnızca yeni kamera: var olanın üstüne yazılmaz
                    sonuc = kameralari_olustur([g.get("ayar")])
                    return self._json({"tamam": True, "kod": sonuc["kodlar"][0], "notlar": sonuc["notlar"]})
                kod, notlar = ayar_kaydet(g.get("ayar"))
            except AyarHatasi as e:
                return self._json({"hata": str(e)}, 400)
            return self._json({"tamam": True, "kod": kod, "notlar": notlar, "ayar": ayar_oku(kod)})
        elif yol == "/api/ayar/sil":
            kod = self._kod(g)
            if self._mesgul() and AKTIF.kod == kod:
                return self._json({"hata": "Önce bu kamerada çalışan işi bitirin ya da durdurun."}, 409)
            if izleme_calisiyor(kod):
                return self._json({"hata": "Bu kamera canlı izleniyor. Önce izlemeyi durdurun."}, 409)
            izleme_istenir(kod, False)
            if kod not in yollar.ornek_kodlar():  # örnek kameranın ayarı kalır; olayları ve klipleri silinir
                ayar_yolu(kod).unlink(missing_ok=True)
                (yollar.AYAR / f"_kare_{kod}.jpg").unlink(missing_ok=True)
                (yollar.AYAR / f"_referans_{kod}.jpg").unlink(missing_ok=True)
                (yollar.AYAR / f"_referans_{kod}.json").unlink(missing_ok=True)  # referans karesindeki kişi kutuları
            depo.kamera_sil(kod)
            shutil.rmtree(yollar.CIKTI / kod, ignore_errors=True)
            return self._json({"tamam": True})
        elif yol == "/api/klasor":
            if hasattr(os, "startfile"):
                os.startfile(str(yollar.VERI))  # noqa: S606 - yalnızca kendi veri klasörümüz
            return self._json({"tamam": True})
        elif yol == "/api/kapat":
            self._json({"tamam": True})
            if AKTIF is not None:
                AKTIF.dur.set()
            threading.Thread(target=kapat, args=(self.server,), daemon=True).start()
            return None
        else:
            return self._json({"hata": "Bilinmeyen istek."}, 404)
        if not ok:
            return self._json({"hata": m}, 409)
        if yol in ("/api/is/test", "/api/is/izle", "/api/is/video") and AKTIF is not None:
            AKTIF.kod = kod
        return self._json({"tamam": True, "is": AKTIF.ozet() if AKTIF else None})


def kapat(sunucu) -> None:
    time.sleep(0.4)
    print("Raf Kamera kapatılıyor.", flush=True)
    for i in list(IZLEMELER.values()):  # izlenmesi istenenler listede kalır: program açılınca yeniden başlar
        i.dur.set()
    try:
        import studio

        studio.durdur_hepsi()  # arayüzsüz Studio süreçleri arkada kalmasın
    except Exception:
        pass
    sunucu.shutdown()


# ---------------------------------------------------------------- başlatma


def calisiyor_mu(port: int) -> bool:
    """Bu portta zaten bir Raf Kamera çalışıyor mu?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/durum", timeout=2) as r:
            return json.loads(r.read().decode("utf-8")).get("uygulama") == yollar.UYGULAMA
    except Exception:
        return False


def temizlik_dongusu(dur: threading.Event) -> None:
    """Saklama süresi dolan kayıtları açılışta ve sonra altı saatte bir siler (Ayarlar → Veri saklama)."""
    import depo

    while not dur.wait(30.0 if not getattr(temizlik_dongusu, "ilk", False) else 6 * 3600):
        temizlik_dongusu.ilk = True
        try:
            sonuc = depo.eskileri_temizle()
            if sonuc["satir"] or sonuc["dosya"]:
                print(f"Eski kayıtlar temizlendi: {sonuc['satir']} kayıt, {sonuc['dosya']} dosya.", flush=True)
        except Exception:
            traceback.print_exc(file=sys.__stderr__)


def splash_kapat() -> None:
    try:
        import pyi_splash  # yalnızca exe'de var

        pyi_splash.close()
    except Exception:
        pass


def isin() -> None:
    """Ağır kütüphaneleri arka planda yükle; ilk iş daha çabuk başlasın."""
    try:
        import kamera  # noqa: F401
        import kuyruk  # noqa: F401
    except Exception:
        traceback.print_exc(file=sys.__stderr__)


def main() -> None:
    ap = argparse.ArgumentParser(prog=yollar.UYGULAMA, description="Raf ve müşteri analizi: yerel sunucu")
    ap.add_argument("--port", type=int, default=VARSAYILAN_PORT)
    ap.add_argument("--tarayici-yok", action="store_true", help="tarayıcıyı açma")
    a = ap.parse_args()

    if calisiyor_mu(a.port):
        splash_kapat()
        url = f"http://127.0.0.1:{a.port}/"
        print(f"Raf Kamera zaten çalışıyor: {url}")
        if not a.tarayici_yok:
            webbrowser.open(url)
        time.sleep(2)
        return

    sys.stdout, sys.stderr = YON_OUT, YON_ERR
    print(f"Raf Kamera {yollar.SURUM}")
    if yollar.hazirla():
        print("İlk kurulum: veri klasörü hazırlandı.")
    if yollar.DONDURULMUS:  # modeller arka planda bir kez SHA-256 ile doğrulanır; yoksa ya da bozuksa indirilir
        import studio_kurulum

        studio_kurulum.model_indirmeyi_baslat()
    import depo

    depo.vt()

    ag = bool(depo.genel().get("ag_erisimi")) and len(depo.genel().get("api_anahtari") or "") >= 20
    dinle = "0.0.0.0" if ag else "127.0.0.1"
    sunucu = None
    for port in [a.port] + list(range(a.port + 1, a.port + 25)):
        try:
            sunucu = Sunucu((dinle, port), Istek)
            break
        except OSError:
            if calisiyor_mu(port):
                splash_kapat()
                print(f"Raf Kamera zaten çalışıyor: http://127.0.0.1:{port}/")
                if not a.tarayici_yok:
                    webbrowser.open(f"http://127.0.0.1:{port}/")
                time.sleep(2)
                return
    if sunucu is None:
        splash_kapat()
        print("Boş port bulunamadı.")
        time.sleep(5)
        raise SystemExit(1)
    port = sunucu.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    DINLENEN.update(adres=dinle, port=port)
    if ag:
        try:
            DINLENEN["ag"] = sorted({b[4][0] for b in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if not b[4][0].startswith("127.")})
        except OSError:
            pass
        print("  Ağ erişimi AÇIK: ağdaki sistemler API anahtarıyla /api/v1/... adreslerini okuyabilir (arayüz yine yalnızca bu bilgisayardan).")
    print(f"  Adres   : {url}")
    print(f"  Veriler : {yollar.VERI}")
    print("Kapatmak için bu pencereyi kapatın (ya da Ayarlar sayfasındaki Kapat düğmesine basın).\n", flush=True)
    threading.Thread(target=isin, daemon=True).start()
    import kuyruk

    kuyruk_dur = threading.Event()
    threading.Thread(target=kuyruk.surekli, args=(kuyruk_dur, _bildir), name="kuyruk", daemon=True).start()
    threading.Thread(target=temizlik_dongusu, args=(kuyruk_dur,), name="temizlik", daemon=True).start()
    threading.Thread(target=izleme_dongusu, args=(kuyruk_dur,), name="izleme-plani", daemon=True).start()
    if GELISTIRME:
        print("  GELİŞTİRME KİPİ: AugeLab Studio çalıştırılmaz (RAF_GELISTIRME).", flush=True)
    splash_kapat()
    if not a.tarayici_yok:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        sunucu.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        sunucu.server_close()
    # izleme sürüyorsa kaydın düzgün kapanması için kısa bir süre tanı
    calisan = [i for i in [AKTIF, *IZLEMELER.values()] if i is not None and i.durum == "calisiyor"]
    for i in calisan:
        i.dur.set()
    for _ in range(10):
        if all(i.durum != "calisiyor" for i in calisan):
            break
        time.sleep(0.3)


if __name__ == "__main__":
    main()
