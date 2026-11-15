"""Veritabanı (SQLite, tek dosya: veri/raf.db): olaylar, görevler, ölçüm parçaları.

Bu sürümde analiz motoru olay ve sayı üretmez; tablolar ileride dolacak biçimde hazırdır.

Bütün zamanlar yerel saatle ISO biçiminde ("2026-11-11T09:30:00") tutulur.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading

import yollar

_KILIT = threading.RLock()

SEMA = """
CREATE TABLE IF NOT EXISTS olay (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kimlik TEXT,                    -- motorun verdiği kimlik (olay başlarken ve kapanırken aynı)
  suruyor INTEGER NOT NULL DEFAULT 0,  -- olay şu an sürüyor mu
  zaman TEXT NOT NULL,            -- olayın başladığı an
  kamera TEXT NOT NULL,           -- kamera kodu
  kamera_ad TEXT NOT NULL,
  kural TEXT NOT NULL,            -- kural kodu
  kural_ad TEXT NOT NULL,
  kategori TEXT NOT NULL,
  duzey TEXT NOT NULL,            -- kritik | yuksek | orta | dusuk
  bolge TEXT,                     -- bölge adı (varsa)
  onem INTEGER NOT NULL,          -- 1-5
  olasilik INTEGER NOT NULL,      -- 1-5
  puan INTEGER NOT NULL,          -- onem × olasilik
  ciddi INTEGER NOT NULL,         -- düzeyi kritik olan olay
  sure_sn REAL NOT NULL,
  x REAL, y REAL,                 -- görüntüdeki konum (0-1)
  klip TEXT, kare TEXT,           -- cikti/ altındaki göreli yollar
  aciklama TEXT,
  ornek INTEGER NOT NULL DEFAULT 0,
  durum TEXT NOT NULL DEFAULT 'acik',   -- acik | ustlenildi | cozuldu | yanlis
  ustlenen TEXT, notlar TEXT, durum_zamani TEXT
);
CREATE INDEX IF NOT EXISTS olay_zaman ON olay(zaman);
CREATE INDEX IF NOT EXISTS olay_kamera ON olay(kamera, zaman);
CREATE INDEX IF NOT EXISTS olay_kimlik ON olay(kimlik);

CREATE TABLE IF NOT EXISTS olcum (            -- izlenen her zaman dilimi (yaklaşık 30 sn)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kamera TEXT NOT NULL, kamera_ad TEXT NOT NULL,
  bas TEXT NOT NULL, sure_sn REAL NOT NULL,
  analiz INTEGER NOT NULL,        -- analiz edilen kare sayısı
  veri TEXT NOT NULL DEFAULT '{}',  -- JSON: dönemin sayıları ({ad: sayı}); analiz motoru doldurur
  izgara TEXT,                    -- JSON (isteğe bağlı): {"gen": 32, "yuk": 18, "katmanlar": {ad: [[...], ...]}}
  son_kare TEXT,
  ornek INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS olcum_kamera ON olcum(kamera, bas);

CREATE TABLE IF NOT EXISTS gorev (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  baslik TEXT NOT NULL, aciklama TEXT,
  sorumlu TEXT, son_tarih TEXT,
  durum TEXT NOT NULL DEFAULT 'acik',   -- acik | suruyor | kapandi
  kamera TEXT, kural TEXT, bolge TEXT,
  olusturma TEXT NOT NULL, kapanma TEXT
);
CREATE TABLE IF NOT EXISTS gorev_olay (gorev INTEGER NOT NULL, olay INTEGER NOT NULL, PRIMARY KEY (gorev, olay));

CREATE TABLE IF NOT EXISTS raf_durum (        -- göz durum değişiklikleri (yalnızca durum, etiket, görülen ürün ya da fiyat değişince)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kamera TEXT NOT NULL, bolge TEXT NOT NULL, goz TEXT NOT NULL,
  zaman TEXT NOT NULL,
  durum TEXT NOT NULL,            -- dolu | az | bos | yanlis | kapali | bilinmiyor
  doluluk REAL, adet INTEGER, urun TEXT, gorulen TEXT, benzerlik REAL,
  etiket TEXT,                    -- uygun | farkli | yok | okunamadi | bakilmadi
  fiyat REAL,                     -- etiketten okunan fiyat
  ornek INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS raf_durum_goz ON raf_durum(kamera, bolge, goz, zaman);
CREATE INDEX IF NOT EXISTS raf_durum_zaman ON raf_durum(zaman);

CREATE TABLE IF NOT EXISTS raf_son (          -- her gözün son bilinen durumu
  kamera TEXT NOT NULL, bolge TEXT NOT NULL, goz TEXT NOT NULL,
  zaman TEXT NOT NULL,            -- son görülme
  degisim TEXT NOT NULL,          -- bu duruma geçtiği an
  durum TEXT NOT NULL, doluluk REAL, adet INTEGER, urun TEXT, gorulen TEXT, benzerlik REAL, etiket TEXT, fiyat REAL,
  ornek INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (kamera, bolge, goz)
);

CREATE TABLE IF NOT EXISTS raf_ozet (         -- kameranın raf özeti (her raf kaydında): ortalama doluluk ve planogram uyumu
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kamera TEXT NOT NULL, zaman TEXT NOT NULL, doluluk REAL, uyum REAL,
  ornek INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS raf_ozet_kamera ON raf_ozet(kamera, zaman);

CREATE TABLE IF NOT EXISTS etkilesim (        -- müşteri-raf etkileşimi (kimliksiz)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kamera TEXT NOT NULL, zaman TEXT NOT NULL, bolge TEXT, goz TEXT,
  eylem TEXT NOT NULL,            -- durdu | uzandi | aldi | birakti
  sure_sn REAL,
  ornek INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS etkilesim_kamera ON etkilesim(kamera, zaman);
"""

# Var olan veritabanına sonradan eklenen sütunlar (tablo, sütun, tanım). Eksikse eklenir; veri silinmez.
GOC = [
    ("olay", "bolge_kimlik", "TEXT"), ("olay", "goz", "TEXT"), ("olay", "urun", "TEXT"), ("olay", "urun_ad", "TEXT"),
    ("olay", "gorev", "INTEGER NOT NULL DEFAULT 0"), ("olay", "deger", "REAL"), ("olay", "beklenen", "TEXT"), ("olay", "bitis", "TEXT"),
    ("gorev", "olay", "INTEGER"), ("gorev", "otomatik", "INTEGER NOT NULL DEFAULT 0"), ("gorev", "goz", "TEXT"), ("gorev", "urun", "TEXT"),
    ("raf_ozet", "referans", "TEXT"),
    ("gorev", "baslama", "TEXT"), ("gorev", "tepki_sn", "REAL"), ("gorev", "notlar", "TEXT"), ("gorev", "ornek", "INTEGER NOT NULL DEFAULT 0"),
]
GOC_INDEKS = """
CREATE INDEX IF NOT EXISTS gorev_olay_kaynak ON gorev(olay);
CREATE INDEX IF NOT EXISTS olay_goz ON olay(kamera, goz);
"""


def _goc(c: sqlite3.Connection) -> None:
    """Eski veritabanına yeni sütunları ekler (ALTER TABLE ADD COLUMN: var olan satırlar korunur)."""
    for tablo in {t for t, _, _ in GOC}:
        var = {r[1] for r in c.execute(f"PRAGMA table_info({tablo})").fetchall()}
        for t, sutun, tanim in GOC:
            if t == tablo and sutun not in var:
                c.execute(f"ALTER TABLE {tablo} ADD COLUMN {sutun} {tanim}")
    c.executescript(GOC_INDEKS)
    c.commit()


def baglan() -> sqlite3.Connection:
    yollar.VERI.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(yollar.VT), timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SEMA)
    _goc(c)
    return c


_VT: sqlite3.Connection | None = None


def vt() -> sqlite3.Connection:
    global _VT
    with _KILIT:
        if _VT is None:
            _VT = baglan()
        return _VT


def kapat() -> None:
    global _VT
    with _KILIT:
        if _VT is not None:
            _VT.close()
            _VT = None


def simdi() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def sor(sql: str, *p) -> list[dict]:
    with _KILIT:
        return [dict(r) for r in vt().execute(sql, p).fetchall()]


_TOPLU = threading.local()


class islem:
    """Toplu yazma: blok içindeki yazmalar tek seferde kaydedilir (kuyruktan binlerce kayıt gelirken hız için).
    Blok süresince veritabanı kilidi bu iş parçacığında tutulur; hata çıkarsa yapılanlar geri alınır."""

    def __enter__(self):
        _KILIT.acquire()
        _TOPLU.derinlik = getattr(_TOPLU, "derinlik", 0) + 1
        return self

    def __exit__(self, tur, deger, iz):
        _TOPLU.derinlik -= 1
        try:
            if _TOPLU.derinlik == 0:
                if tur is None:
                    vt().commit()
                else:
                    vt().rollback()
        finally:
            _KILIT.release()
        return False


def yaz(sql: str, *p) -> int:
    with _KILIT:
        c = vt().execute(sql, p)
        if not getattr(_TOPLU, "derinlik", 0):
            vt().commit()
        return c.lastrowid


def ekle(tablo: str, kayit: dict) -> int:
    alanlar = list(kayit)
    return yaz(f"INSERT INTO {tablo} ({', '.join(alanlar)}) VALUES ({', '.join('?' * len(alanlar))})",
               *[json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in kayit.values()])


KAMERA_TABLOLARI = ("olay", "olcum", "raf_durum", "raf_son", "raf_ozet", "etkilesim")


def kamera_sil(kod: str, yalniz_ornek: bool = False) -> None:
    ek = " AND ornek != 0" if yalniz_ornek else ""
    with _KILIT:
        vt().execute(f"DELETE FROM gorev_olay WHERE olay IN (SELECT id FROM olay WHERE kamera = ?{ek})", (kod,))
        for tablo in KAMERA_TABLOLARI:
            vt().execute(f"DELETE FROM {tablo} WHERE kamera = ?{ek}", (kod,))
        if yalniz_ornek:
            # örnek (video / demo) çözümlemesinin kendiliğinden açtığı görevler de gider: örnekler yeniden çözümlenince
            # görev listesi her seferinde aynı görevlerle çoğalmasın. Gerçek kameranın görevleri silinmez (geçmiş).
            vt().execute("DELETE FROM gorev_olay WHERE gorev IN (SELECT id FROM gorev WHERE kamera = ? AND ornek != 0)", (kod,))
            vt().execute("DELETE FROM gorev WHERE kamera = ? AND ornek != 0", (kod,))
        vt().commit()


# ---------------------------------------------------------------- örnek veri (demo) kayıtları

ORNEK_ON = "ornek-"  # örnek kameraların kod öneki: gerçek kameralar bu önekle kaydedilemez


def ornek_kamera(kod: str | None) -> bool:
    return bool(kod) and str(kod).startswith(ORNEK_ON)


def ornek_sayilari() -> dict:
    """Veritabanındaki örnek (demo) kayıtların sayıları."""
    out = {t: sor(f"SELECT COUNT(*) AS n FROM {t} WHERE ornek = 1")[0]["n"] for t in KAMERA_TABLOLARI}
    out["gorev"] = sor("SELECT COUNT(*) AS n FROM gorev WHERE ornek = 1")[0]["n"]
    return out


def ornekleri_sil() -> None:
    """Yalnızca örnek işaretli satırları siler (ornek = 1). Gerçek kayıtlar hiçbir koşulda bu sorguya girmez."""
    with _KILIT:
        vt().execute("DELETE FROM gorev_olay WHERE gorev IN (SELECT id FROM gorev WHERE ornek = 1) "
                     "OR olay IN (SELECT id FROM olay WHERE ornek = 1)")
        vt().execute("DELETE FROM gorev WHERE ornek = 1")
        for tablo in KAMERA_TABLOLARI:
            vt().execute(f"DELETE FROM {tablo} WHERE ornek = 1")
        vt().commit()


# ---------------------------------------------------------------- eski kayıtların temizliği

def eskileri_temizle(simdi: dt.datetime | None = None) -> dict:
    """Saklama süresi dolan kayıtları siler: olay, ölçüm, raf ve etkileşim kayıtları `saklama_gun`, olay klip ve kareleri
    `klip_gun` gün tutulur. Açık (sürmekte olan) olaylar ve görevlere bağlı olaylar silinmez; görevler silinmez.
    Dönüş: silinen satır ve dosya sayıları."""
    g = genel()
    simdi = simdi or dt.datetime.now()
    sinir = (simdi - dt.timedelta(days=int(g["saklama_gun"]))).replace(microsecond=0).isoformat()
    klip_sinir = (simdi - dt.timedelta(days=int(g["klip_gun"]))).replace(microsecond=0).isoformat()
    out = {"satir": 0, "dosya": 0}
    with _KILIT:
        silinecek = [dict(r) for r in vt().execute(
            "SELECT id, klip, kare FROM olay WHERE zaman < ? AND suruyor = 0 AND id NOT IN (SELECT olay FROM gorev_olay)", (sinir,)).fetchall()]
        medya = [dict(r) for r in vt().execute("SELECT id, klip, kare FROM olay WHERE zaman < ? AND (klip IS NOT NULL OR kare IS NOT NULL)", (klip_sinir,)).fetchall()]
        for tablo, alan in (("olcum", "bas"), ("raf_ozet", "zaman"), ("etkilesim", "zaman")):
            out["satir"] += vt().execute(f"DELETE FROM {tablo} WHERE {alan} < ?", (sinir,)).rowcount
        # göz geçmişi: her gözün sınırdan önceki son kaydı kalır (o andaki durumu bilinsin)
        out["satir"] += vt().execute(
            "DELETE FROM raf_durum WHERE zaman < ? AND id NOT IN (SELECT MAX(id) FROM raf_durum WHERE zaman < ? GROUP BY kamera, bolge, goz)",
            (sinir, sinir)).rowcount
        if silinecek:
            out["satir"] += vt().execute(f"DELETE FROM olay WHERE id IN ({','.join(str(o['id']) for o in silinecek)})").rowcount
        if medya:
            vt().execute(f"UPDATE olay SET klip = NULL, kare = NULL WHERE id IN ({','.join(str(o['id']) for o in medya)})")
        vt().commit()
    paylasilan = {r["kare"] for r in sor("SELECT DISTINCT kare FROM olay WHERE kare IS NOT NULL")}  # örnek kareler paylaşılabilir
    for o in silinecek + medya:
        for alan in ("klip", "kare"):
            if o.get(alan) and o[alan] not in paylasilan:
                hedef = (yollar.CIKTI / o[alan]).resolve()
                if yollar.CIKTI.resolve() in hedef.parents and hedef.is_file():
                    try:
                        hedef.unlink()
                        out["dosya"] += 1
                    except OSError:
                        pass
    out["dosya"] += _artiklari_sil(simdi, int(g["klip_gun"]))
    return out


KALICI_CIKTI = {"son_kare.jpg", "temiz_kare.jpg", "temiz_kare.json"}  # kameranın güncel kareleri: yaşına bakılmaz
ARTIK_KUYRUK_SN = 3600.0  # kuyrukta bu kadar eski .tmp ya da okunamayan .json: yarıda kalmış yazım (motor kapandı)


def _artiklari_sil(simdi: dt.datetime, klip_gun: int) -> int:
    """Hiçbir kayda bağlı olmayan artıkları siler: cikti/ altında klip süresinden eski, olay kaydında geçmeyen dosyalar
    (silinmiş kameranın klipleri, kapanmamış olayın yarım .ham.mp4'ü, kaydı hiç gelmeyen olay karesi) ve kuyrukta bir
    saatten eski yarım yazımlar (.tmp) ile okunamayan kayıtlar. Dönüş: silinen dosya sayısı."""
    n = 0
    sinir_ts = (simdi - dt.timedelta(days=klip_gun)).timestamp()
    bagli = set()
    for r in sor("SELECT klip, kare FROM olay WHERE klip IS NOT NULL OR kare IS NOT NULL"):
        bagli.update(v for v in (r["klip"], r["kare"]) if v)
    bagli.update(r["son_kare"] for r in sor("SELECT DISTINCT son_kare FROM olcum WHERE son_kare IS NOT NULL"))
    if yollar.CIKTI.is_dir():
        for klasor in (k for k in yollar.CIKTI.iterdir() if k.is_dir()):
            for f in klasor.iterdir():
                try:
                    if (not f.is_file() or f.name in KALICI_CIKTI or f"{klasor.name}/{f.name}" in bagli
                            or f.stat().st_mtime >= sinir_ts):
                        continue
                    f.unlink()
                    n += 1
                except OSError:
                    pass
    kuyruk = yollar.VERI / "kuyruk"
    if kuyruk.is_dir():
        esik = simdi.timestamp() - ARTIK_KUYRUK_SN
        for f in list(kuyruk.glob("*.tmp")) + list(kuyruk.glob("*.json")):
            try:
                if f.stat().st_mtime >= esik:
                    continue
                if f.suffix == ".json":
                    try:
                        json.loads(f.read_text(encoding="utf-8"))
                        continue  # okunabilir kayıt: panel içeri alacak, silinmez
                    except ValueError:
                        pass
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


# ---------------------------------------------------------------- genel ayarlar

VARSAYILAN_GENEL = {
    "tesis": "Mağaza",
    "sube": "",
    "adres": "",
    "para_birimi": "₺",
    "calisma": {"bas": "08:00", "bit": "22:00"},   # çalışma saatleri: analiz ve raporlar bu saatlere göre
    "saklama_gun": 180,                            # olay, ölçüm ve raf kayıtları kaç gün tutulur
    "klip_gun": 30,                                # olay klipleri ve kareleri kaç gün tutulur
    "vardiyalar": [{"ad": "Sabah", "bas": "08:00", "bit": "15:00"}, {"ad": "Akşam", "bas": "15:00", "bit": "22:00"}],
    "baglantilar": [],   # [{"ad": "...", "tur": "webhook", "adres": "https://...", "en_az_puan": 9}]
}


def _dk(saat: str) -> int:
    return int(saat[:2]) * 60 + int(saat[3:5])


def calisma_araligi(g: dict | None = None) -> tuple[int, int]:
    """Çalışma saatleri dakika olarak (başlangıç, bitiş). Bitiş başlangıçtan küçükse gece yarısını geçer."""
    c = (g or genel()).get("calisma") or VARSAYILAN_GENEL["calisma"]
    try:
        return _dk(c["bas"]), _dk(c["bit"])
    except (KeyError, ValueError, TypeError):
        return 8 * 60, 22 * 60


def calisma_saatinde(an: dt.datetime, g: dict | None = None) -> bool:
    a, b = calisma_araligi(g)
    dk = an.hour * 60 + an.minute
    if a == b:
        return True  # 24 saat açık
    return (a <= dk < b) if a < b else (dk >= a or dk < b)


def calisma_parcalari(t0: dt.datetime, t1: dt.datetime, g: dict | None = None):
    """[t0, t1) aralığının çalışma saatlerine düşen parçaları: (başlangıç, bitiş) çiftleri."""
    if t1 <= t0:
        return
    a, b = calisma_araligi(g)
    if a == b:
        yield t0, t1
        return
    gun = t0.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)
    while gun < t1:
        if a < b:
            pencereler = [(gun + dt.timedelta(minutes=a), gun + dt.timedelta(minutes=b))]
        else:  # gece yarısını geçen çalışma
            pencereler = [(gun + dt.timedelta(minutes=a), gun + dt.timedelta(days=1, minutes=b))]
        for p0, p1 in pencereler:
            x0, x1 = max(t0, p0), min(t1, p1)
            if x1 > x0:
                yield x0, x1
        gun += dt.timedelta(days=1)


def calisma_suresi(t0: dt.datetime, t1: dt.datetime, g: dict | None = None) -> float:
    return sum((b - a).total_seconds() for a, b in calisma_parcalari(t0, t1, g))


def genel() -> dict:
    try:
        g = json.loads(yollar.GENEL_AYAR.read_text(encoding="utf-8"))
    except Exception:
        g = {}
    return {**VARSAYILAN_GENEL, **(g if isinstance(g, dict) else {})}


_GENEL_KILIDI = threading.Lock()


def genel_yaz(g: dict) -> None:
    with _GENEL_KILIDI:
        yollar.VERI.mkdir(parents=True, exist_ok=True)
        gecici = yollar.GENEL_AYAR.with_suffix(".json.tmp")
        gecici.write_text(json.dumps({**genel(), **g}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, yollar.GENEL_AYAR)


# ---------------------------------------------------------------- ürün kataloğu (<VERI>/urunler/urunler.json; motor okur)

URUN_KLASORU_ADI = "urunler"
_URUN_KILIDI = threading.RLock()


def urun_klasoru():
    return yollar.VERI / URUN_KLASORU_ADI


def gorsel_klasoru():
    return urun_klasoru() / "gorsel"


def urunler() -> list[dict]:
    try:
        liste = json.loads((urun_klasoru() / "urunler.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [u for u in liste if isinstance(u, dict) and u.get("kimlik")] if isinstance(liste, list) else []


def urunleri_yaz(liste: list[dict]) -> None:
    """Kataloğu bütün olarak yazar (önce geçici dosya, sonra yer değiştirme: motor yarım dosya okumaz)."""
    with _URUN_KILIDI:
        urun_klasoru().mkdir(parents=True, exist_ok=True)
        gorsel_klasoru().mkdir(parents=True, exist_ok=True)
        gecici = urun_klasoru() / "urunler.json.tmp"
        gecici.write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, urun_klasoru() / "urunler.json")


def yeni_urun_kimligi(liste: list[dict]) -> str:
    var = {u["kimlik"] for u in liste}
    n = 1 + max([int(k[1:]) for k in var if k[:1] == "u" and k[1:].isdigit()] or [0])
    while f"u{n}" in var:
        n += 1
    return f"u{n}"


def vardiya(zaman: str, vardiyalar: list[dict] | None = None) -> str:
    """Verilen anın düştüğü vardiyanın adı."""
    vardiyalar = vardiyalar or genel()["vardiyalar"]
    dk = int(zaman[11:13]) * 60 + int(zaman[14:16])
    for v in vardiyalar:
        a = int(v["bas"][:2]) * 60 + int(v["bas"][3:5])
        b = int(v["bit"][:2]) * 60 + int(v["bit"][3:5])
        if (a <= dk < b) if a < b else (dk >= a or dk < b):
            return v["ad"]
    return "–"
