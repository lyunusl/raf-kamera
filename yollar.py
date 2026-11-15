"""Klasörler ve programla gelen dosyalar.

KAYNAK: programla gelen dosyalar (web sayfaları, motor, örnekler). Exe'de geçici açılma klasörü.
VERI:   kullanıcının verisi (ayarlar, veritabanı, klipler). Exe'de %LOCALAPPDATA%\\RafKamera,
        kaynak koddan çalışırken proje içindeki veri/ klasörü. RAF_KAMERA_VERI ortam değişkeniyle değiştirilebilir.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

SURUM = "0.1.0"
UYGULAMA = "RafKamera"
DONDURULMUS = bool(getattr(sys, "frozen", False))
KAYNAK = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _veri() -> Path:
    ortam = os.environ.get("RAF_KAMERA_VERI")
    if ortam:
        return Path(ortam).resolve()
    if DONDURULMUS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / UYGULAMA
    return Path(__file__).resolve().parent / "veri"


VERI = _veri()


def _profil_kokleri() -> list[tuple[str, str]]:
    """(gerçek klasör, gösterilecek ad): kullanıcı adını taşıyan klasörler, en uzunu önce (LOCALAPPDATA, APPDATA'dan önce)."""
    kokler = []
    for ad in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        if os.environ.get(ad):
            kokler.append((os.environ[ad], f"%{ad}%"))
    try:
        kokler.append((str(Path.home()), "%USERPROFILE%"))
    except RuntimeError:
        pass
    out, gorulen = [], set()
    for yol, ad in sorted(kokler, key=lambda k: -len(k[0].rstrip("\\/"))):
        yol = yol.rstrip("\\/")
        if len(yol) > 3 and yol.lower() not in gorulen:  # "C:\" gibi kök sürücü gizlenmez
            gorulen.add(yol.lower())
            out.append((yol, ad))
    return out


def gizle(metin: str) -> str:
    """Tarayıcıya giden metindeki kullanıcı profili yollarını kısaltır: C:\\Users\\ad\\AppData\\Local\\RafKamera →
    %LOCALAPPDATA%\\RafKamera. Kullanıcı adı ekrana ve API yanıtına çıkmasın diye (konsol ve günlük dosyası tam yolu tutar)."""
    if not isinstance(metin, str) or not metin:
        return metin
    for yol, ad in _profil_kokleri():
        desen = r"[\\/]+".join(re.escape(p) for p in re.split(r"[\\/]+", yol))
        metin = re.sub(desen + r"(?=[\\/]|$|[^\w.-])", lambda _m, ad=ad: ad, metin, flags=re.IGNORECASE)
    return metin


def gizle_her(veri):
    """gizle() sözlük ve listelerdeki bütün metinlere (anahtarlara değil)."""
    if isinstance(veri, str):
        return gizle(veri)
    if isinstance(veri, dict):
        return {k: gizle_her(v) for k, v in veri.items()}
    if isinstance(veri, (list, tuple)):
        return [gizle_her(v) for v in veri]
    return veri
AYAR = VERI / "ayar"          # kamera başına <kod>.json ve bölge çizme karesi _kare_<kod>.jpg
VIDEOLAR = VERI / "videolar"  # video dosyaları (örnekler ve kullanıcının koydukları)
CIKTI = VERI / "cikti"        # klipler, olay kareleri, kameraların son karesi
VT = VERI / "raf.db"
GENEL_AYAR = VERI / "genel.json"

WEB = KAYNAK / "web"
ORNEKLER = KAYNAK / "ornekler"
MOTOR = KAYNAK / "motor"                                    # AugeLab Studio'ya yerleştirilen motor (raf_motor, modeller, deps)
# PAKET_MODELLER: programla gelen model paketi dosyaları (işaret, DLL; düz derlemede düz modeller). Güvenilir kopyadır.
# MODELLER: büyük model dosyalarının yeri. Exe'de veri klasöründedir: kurulumda (ya da ilk açılışta panelde) indirilip
# oraya konur ve motora yalnızca SHA-256 ile doğrulanmışsa girer (studio_kurulum.motor_modelleri). Kaynak koddan ikisi aynıdır.
# Hangi modellerin indirileceği studio_kurulum.MODELLER tablosundadır.
PAKET_MODELLER = MOTOR / "modeller"
MODELLER = VERI / "modeller" if DONDURULMUS else PAKET_MODELLER

# Örnek videolar (ornekler/videolar/<kod>.mp4). Ayarı ornekler/ayar/<kod>.json dosyasından okunur; dosya yoksa kod adıyla,
# bölgesiz ve varsayılan ayarlarla kurulur. Liste klasördeki dosyalardan çıkarılır (ad sabit yazılmaz); her kod kamera
# koduna ayrılır (kullanıcı aynı kodla kamera ekleyemez).


def _ornek_adlari() -> dict[str, str]:
    out: dict[str, str] = {}
    klasor = ORNEKLER / "videolar"
    for video in sorted(klasor.glob("*.mp4")) if klasor.is_dir() else []:
        kod = video.stem
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,39}$", kod):
            continue
        ad = kod
        try:
            a = json.loads((ORNEKLER / "ayar" / f"{kod}.json").read_text(encoding="utf-8"))
            ad = str(a.get("ad") or kod) if isinstance(a, dict) else kod
        except (OSError, ValueError):
            pass
        out[kod] = ad
    return out


ORNEK_ADLARI: dict[str, str] = _ornek_adlari()


def ornek_kodlar() -> list[str]:
    """Videosu programla gelmiş örneklerin kodları (video yoksa örnek de yoktur)."""
    return [kod for kod in ORNEK_ADLARI if (ORNEKLER / "videolar" / f"{kod}.mp4").is_file()]


def ornek_ayari(kod: str) -> dict:
    """Örneğin kamera ayarı: hazır dosyası varsa o, yoksa varsayılan. Video yolu her durumda veri klasörüne göredir."""
    ayar = {}
    try:
        ayar = json.loads((ORNEKLER / "ayar" / f"{kod}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not isinstance(ayar, dict):
        ayar = {}
    ayar.setdefault("ad", ORNEK_ADLARI.get(kod, kod))
    ayar.setdefault("bolgeler", [])
    ayar.update(kod=kod, kamera={"tur": "dosya", "yol": f"videolar/{kod}.mp4"}, ornek_video=True)
    return ayar


def ffmpeg() -> str:
    """Programla gelen ffmpeg (imageio-ffmpeg paketi); yoksa PATH'teki."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    yol = shutil.which("ffmpeg")
    if not yol:
        raise SystemExit("ffmpeg bulunamadı.")
    return yol


_IS_NESNESI = None


def cocuk_bagla(surec) -> None:
    """Program kapanınca (pencere kapatılsa bile) bu alt süreç de kapansın: Windows iş nesnesi (job object)."""
    global _IS_NESNESI
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _IS_NESNESI is None:
            class Temel(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

            class GirdiCikti(ctypes.Structure):
                _fields_ = [(ad, ctypes.c_uint64) for ad in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                             "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class Genis(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", Temel), ("IoInfo", GirdiCikti), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            h = k32.CreateJobObjectW(None, None)
            bilgi = Genis()
            bilgi.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not h or not k32.SetInformationJobObject(h, 9, ctypes.byref(bilgi), ctypes.sizeof(bilgi)):
                return
            _IS_NESNESI = h
        k32.AssignProcessToJobObject(_IS_NESNESI, int(surec._handle))
    except Exception:
        pass


def hazirla() -> bool:
    """Veri klasörünü kurar, örnek videoları ve ayarlarını (yoksa) kopyalar. İlk kurulumsa True döner."""
    ilk = not VERI.exists()
    for d in (AYAR, VIDEOLAR, CIKTI):
        d.mkdir(parents=True, exist_ok=True)
    for kod in ornek_kodlar():
        video, ayar = VIDEOLAR / f"{kod}.mp4", AYAR / f"{kod}.json"
        if not video.exists():
            shutil.copy2(ORNEKLER / "videolar" / f"{kod}.mp4", video)
        if not ayar.exists():
            ayar.write_text(json.dumps(ornek_ayari(kod), ensure_ascii=False, indent=1), encoding="utf-8")
    return ilk
