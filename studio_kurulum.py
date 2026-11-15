"""Raf Kamera için Windows'ta AugeLab Studio kurulumu ve lisans kaydı. Studio penceresi hiç açılmaz.

Kurulum dosyası ve panel bunu adım adım gösterir:
1. AugeLab'in resmî kurucusunu indirir ve SHA-256 özetini doğrular,
2. Microsoft Visual C++ 2015-2022 çalışma kitaplığı (x64) yoksa Microsoft'tan indirir, Microsoft imzasını doğrular ve kurar,
3. Studio'yu kullanıcı klasörüne sessizce kurar; olmazsa resmî kurulum penceresini açar,
4. kullanıcının AugeLab hesabından aldığı lisans kodunu Studio'nun kendi komutuyla arayüzsüz kaydeder
   (studio verify; kod komut satırına değil ortam değişkenine konur). Kod saklanmaz ve günlüğe yazılmaz.
Analiz de arayüzsüz yapılır (studio.py). Modeller kurulumda indirilmediyse panel onları da buradan indirir (model_indir)."""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import certifi

import yollar

EXE = "AugeLab AI Studio.exe"
KURULUM_URL = "https://studio-desktop-application.s3.eu-central-1.amazonaws.com/AugeLab%20Ai%20Studio.exe"
KURULUM_SHA256 = "cec1e2613620c57fa51c853fc2b6148bc90f978eaf76e351b4b0b0f393681bd8"
VC_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
HESAP_URL = "https://account.augelab.com/"  # lisans kodu AugeLab hesabında görünür; panel yalnızca bu sayfayı açar
_BASLATMA_KILIDI = threading.Lock()

# Panelin kurulum adımlarını göstermesi için (kur() yazar, durum() okur).
# asama: bos | indiriliyor | vc | kuruluyor | pencere | hata
DURUM: dict = {"asama": "bos", "ne": "", "indirilen": 0, "toplam": 0, "hata": "", "baslangic": 0.0}


def durum() -> dict:
    d = dict(DURUM)
    baslangic = d.pop("baslangic")
    d["gecen"] = round(time.monotonic() - baslangic) if baslangic else 0
    d["calisiyor"] = studio_calisiyor()
    return d


_CALISIYOR = {"an": 0.0, "deger": False}


def studio_calisiyor() -> bool:
    """Studio süreci açık mı (görev listesinden; panel sık yokladığı için 3 saniye saklanır)."""
    if os.name != "nt":
        return False
    if time.monotonic() - _CALISIYOR["an"] < 3:
        return _CALISIYOR["deger"]
    _CALISIYOR["an"] = time.monotonic()
    try:
        cikti = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                               timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    _CALISIYOR["deger"] = EXE.casefold() in cikti.casefold()
    return _CALISIYOR["deger"]


def vc_kurulu() -> bool:
    """Microsoft Visual C++ 2015-2022 çalışma kitaplığı (x64): Studio bu olmadan açılmaz."""
    if os.name != "nt":
        return True
    import winreg

    for yol in (r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, yol) as anahtar:
                if winreg.QueryValueEx(anahtar, "Installed")[0] == 1:
                    return True
        except OSError:
            continue
    return False


def microsoft_imzali(dosya: Path) -> bool:
    """Windows'un kendi imza denetimi (Authenticode): geçerli ve Microsoft Corporation adına imzalı mı."""
    betik = ("$s = Get-AuthenticodeSignature -LiteralPath $env:RAF_DOSYA; "
             "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'O=Microsoft Corporation') { 'ok' }")
    try:
        cikti = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", betik], capture_output=True,
                               text=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                               env={**os.environ, "RAF_DOSYA": str(dosya)}).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return cikti.strip() == "ok"


def varsayilan_klasor() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Programs/AugeLab Studio"


def _studio_exe(klasor: Path) -> Path | None:
    exe = klasor / EXE
    python = klasor / "Python"
    paket = python / "Lib" / "site-packages" / "studio" / "__init__.py"
    if exe.is_file() and (python / "pythonw.exe").is_file() and paket.is_file():
        return exe
    return None


def kurulu_studio() -> Path | None:
    if os.name != "nt":
        return None
    import winreg

    varsayilan = _studio_exe(varsayilan_klasor())
    if varsayilan is not None:
        return varsayilan
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                            try:
                                ad = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                                if "augelab" in ad.casefold() and "studio" in ad.casefold():
                                    yol = str(winreg.QueryValueEx(sub, "InstallLocation")[0]).strip('"')
                                    klasor = Path(yol)
                                    if yol and klasor.is_absolute():
                                        exe = _studio_exe(klasor)
                                        if exe is not None:
                                            return exe
                            except OSError:
                                continue
            except OSError:
                continue
    return None


@contextlib.contextmanager
def _temiz_dll_dizini():
    """Studio ve kurucular, paketlenmiş Python'un DLL dizinini devralmamalı."""
    if not yollar.DONDURULMUS:
        yield
        return
    import ctypes
    from ctypes import wintypes

    dll_dizini = ctypes.WinDLL("kernel32", use_last_error=True).SetDllDirectoryW
    dll_dizini.argtypes = [wintypes.LPCWSTR]
    dll_dizini.restype = wintypes.BOOL
    with _BASLATMA_KILIDI:
        if not dll_dizini(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            dll_dizini(sys._MEIPASS)


def _harici_program(program: Path, *args: str, **options) -> subprocess.Popen:
    with _temiz_dll_dizini():
        return subprocess.Popen([str(program), *args], **options)


def _izinle_calistir(program: Path, parametre: str = "", goster: bool = True) -> int:
    """Programı Gezgin'in açtığı gibi başlatır (Windows izin sorabilir) ve bitmesini bekler. Dönüş: çıkış kodu.
    İzin verilmezse OSError (winerror 1223)."""
    import ctypes
    from ctypes import wintypes

    class Bilgi(ctypes.Structure):  # SHELLEXECUTEINFOW
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    bilgi = Bilgi()
    bilgi.cbSize = ctypes.sizeof(bilgi)
    bilgi.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS: beklemek için süreç tutamacı
    bilgi.lpVerb, bilgi.lpFile, bilgi.lpParameters = "open", str(program), parametre or None
    bilgi.lpDirectory, bilgi.nShow = str(program.parent), 1 if goster else 0
    kabuk = ctypes.WinDLL("shell32", use_last_error=True)
    kabuk.ShellExecuteExW.argtypes = [ctypes.POINTER(Bilgi)]
    kabuk.ShellExecuteExW.restype = wintypes.BOOL
    with _temiz_dll_dizini():
        if not kabuk.ShellExecuteExW(ctypes.byref(bilgi)):
            raise ctypes.WinError(ctypes.get_last_error())
    if not bilgi.hProcess:
        return 0
    k32 = ctypes.WinDLL("kernel32")
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        k32.WaitForSingleObject(bilgi.hProcess, 0xFFFFFFFF)
        kod = wintypes.DWORD()
        k32.GetExitCodeProcess(bilgi.hProcess, ctypes.byref(kod))
        return kod.value
    finally:
        k32.CloseHandle(bilgi.hProcess)


def _tls() -> ssl.SSLContext:
    tls = ssl.create_default_context()
    tls.load_verify_locations(cafile=certifi.where())
    return tls


def _indir(url: str, dosya: Path, ne: str, is_, sha256: str | None = None) -> bool:
    """`url`'yi `dosya`ya indirir (TLS, certifi ile doğrulanır). `sha256` verilirse özet tutmalı. Durdurulursa False."""
    gecici = dosya.with_suffix(".part")
    tls = _tls()
    DURUM.update(asama="vc" if dosya.name.startswith("vc_") else "indiriliyor", ne=ne, indirilen=0, toplam=0)
    istek = urllib.request.Request(url, headers={"User-Agent": "RafKamera"})
    try:
        ozet = hashlib.sha256()
        with urllib.request.urlopen(istek, timeout=30, context=tls) as yanit, gecici.open("wb") as cikti:
            DURUM["toplam"] = int(yanit.headers.get("Content-Length") or 0)
            for parca in iter(lambda: yanit.read(256 * 1024), b""):
                if is_.dur.is_set():
                    return False
                ozet.update(parca)
                cikti.write(parca)
                DURUM["indirilen"] += len(parca)
        with gecici.open("rb") as f:
            bozuk = f.read(2) != b"MZ"
        if bozuk or (DURUM["toplam"] and gecici.stat().st_size != DURUM["toplam"]):
            raise SystemExit(f"İndirilen {ne} dosyası eksik ya da bozuk. Tekrar deneyin.")
        if sha256 and ozet.hexdigest() != sha256:
            raise SystemExit("AugeLab kurucusunun doğrulaması başarısız. Resmî AugeLab hesabından güncel kurucuyu indirin.")
        gecici.replace(dosya)
        return True
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise SystemExit(f"{ne} indirme adresinin TLS sertifikası doğrulanamadı.") from exc
        raise SystemExit(f"{ne} indirilemedi: internet bağlantısını kontrol edin.") from exc
    finally:
        gecici.unlink(missing_ok=True)


def _vc_kur(klasor: Path, is_) -> bool:
    """Visual C++ çalışma kitaplığını Microsoft'tan indirip imzasını doğrulayarak kurar. Durdurulursa False."""
    vc = klasor / "vc_redist.x64.exe"
    print("Visual C++ çalışma kitaplığı (Microsoft) indiriliyor.", flush=True)
    if not _indir(VC_URL, vc, "Visual C++ bileşeni", is_):
        return False
    if not microsoft_imzali(vc):
        vc.unlink(missing_ok=True)
        raise SystemExit("Visual C++ bileşeninin Microsoft imzası doğrulanamadı; kurulmadı.")
    DURUM.update(asama="vc", ne="Visual C++ bileşeni kuruluyor", indirilen=0, toplam=0)
    print("Visual C++ çalışma kitaplığı kuruluyor. Windows izin sorarsa Evet deyin.", flush=True)
    try:
        kod = _izinle_calistir(vc, "/install /passive /norestart")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1223:
            raise SystemExit("Windows izni verilmedi. Tekrar deneyip izin isteğine Evet deyin.") from exc
        raise
    if kod not in (0, 1638, 3010) or not vc_kurulu():
        raise SystemExit(f"Visual C++ bileşeni kurulamadı (kod {kod}).")
    return True


def _kurulumu_bekle(sinir_dk: float, is_) -> Path | None:
    """Studio'nun program dosyaları yerine oturana kadar bekler."""
    bitis = time.monotonic() + sinir_dk * 60
    while time.monotonic() < bitis and not is_.dur.is_set():
        studio = kurulu_studio()
        if studio is not None:
            return studio
        time.sleep(2)
    return kurulu_studio()


LISANS_KODU = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/=-]{5,1023}")
# `studio verify <kod>` ile aynı komut; kod komut satırında görünmesin diye ortam değişkeniyle verilir (kurulum dosyası da böyle).
VERIFY = ("import os,runpy,sys; sys.argv=['studio','verify',os.environ.pop('RAF_LISANS_KODU','')]; "
          "runpy.run_module('studio',run_name='__main__',alter_sys=True)")


def lisans_kaydet(kod: str) -> None:
    """AugeLab hesabından alınan lisans (doğrulama) kodunu Studio'nun kendi komutuyla, Studio penceresi açılmadan bu
    bilgisayara kaydeder. Kod yalnızca Studio'ya verilir: saklanmaz, günlüğe ve hata metnine yazılmaz."""
    kod = (kod or "").strip()
    if not LISANS_KODU.fullmatch(kod):
        raise SystemExit("Lisans kodu geçersiz görünüyor. AugeLab hesabınızdaki kodu boşluksuz, olduğu gibi yapıştırın.")
    studio = kurulu_studio()
    if studio is None:
        raise SystemExit("AugeLab Studio kurulu değil. Önce Studio'yu kurun.")
    py = studio.parent / "Python" / "python.exe"
    try:
        with _temiz_dll_dizini():
            # Yeni kurulmuş Studio'da ilk deneme başarısız dönebiliyor (temiz makinede görüldü: ikinci deneme kabul edildi);
            # bu yüzden komut bir kez daha denenir.
            for _ in range(2):
                r = subprocess.run([str(py), "-c", VERIFY], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=180, cwd=str(studio.parent), stdin=subprocess.DEVNULL,
                                   env=dict(os.environ, RAF_LISANS_KODU=kod), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if r.returncode == 0:
                    break
    except subprocess.TimeoutExpired:
        raise SystemExit("AugeLab Studio lisans kodunu zamanında doğrulamadı. İnternet bağlantısını kontrol edip tekrar deneyin.") from None
    except OSError as e:
        raise SystemExit(f"AugeLab Studio çalıştırılamadı: {e}") from None
    if r.returncode != 0:  # Studio'nun çıktısı gösterilmez: kodun bir parçasını içerebilir
        raise SystemExit("Lisans kodu kaydedilemedi. Kodu AugeLab hesabınızdan yeniden alıp deneyin.")


def kur(is_) -> dict:
    try:
        return _kur(is_)
    except SystemExit as e:
        DURUM.update(asama="hata", hata=str(e.code or ""), baslangic=0.0)
        raise
    except Exception as e:
        DURUM.update(asama="hata", hata=f"Kurulum durdu: {e}", baslangic=0.0)
        raise


def _kur(is_) -> dict:
    DURUM.update(asama="bos", ne="", indirilen=0, toplam=0, hata="", baslangic=0.0)
    mimari = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE", "")
    if os.name != "nt" or mimari.upper() != "AMD64":
        raise SystemExit("Bu kurulum Windows x64 içindir.")
    mevcut = kurulu_studio()
    if mevcut is not None:
        print("AugeLab Studio zaten kurulu.", flush=True)
        return {"kurulu": True}

    hedef = varsayilan_klasor()
    if hedef.exists() and any(hedef.iterdir()):
        raise SystemExit("AugeLab Studio klasörü dolu fakat Studio kurulumu eksik. Resmî kurucuyla mevcut kurulumu onarın.")
    klasor = yollar.VERI / "kurulum"
    klasor.mkdir(parents=True, exist_ok=True)
    dosya = klasor / f"AugeLab-Studio-{KURULUM_SHA256[:12]}.exe"
    dogrulandi = False
    if dosya.is_file():
        with dosya.open("rb") as akim:
            dogrulandi = hashlib.file_digest(akim, "sha256").hexdigest() == KURULUM_SHA256
    if not dogrulandi:
        print("AugeLab Studio'nun resmî kurucusu indiriliyor.", flush=True)
        if not _indir(KURULUM_URL, dosya, "AugeLab Studio kurucusu", is_, KURULUM_SHA256):
            return {}
    if is_.dur.is_set():
        return {}
    if not vc_kurulu() and not _vc_kur(klasor, is_):
        return {}
    if is_.dur.is_set():
        return {}
    # Önce sessiz kurulum (Visual C++ artık yerinde); olmazsa resmî kurulum penceresi.
    DURUM.update(asama="kuruluyor", ne="AugeLab Studio kuruluyor", indirilen=0, toplam=0, baslangic=time.monotonic())
    print("AugeLab Studio kuruluyor. Birkaç dakika sürebilir.", flush=True)
    try:
        kod = _izinle_calistir(dosya, f'--silent --install-dir "{hedef}" --start-menu-shortcut', goster=False)
    except OSError as exc:
        kod = getattr(exc, "winerror", None) or -1
    studio = _kurulumu_bekle(20, is_) if kod == 0 else kurulu_studio()
    if studio is None and not is_.dur.is_set():
        DURUM.update(asama="pencere", ne="AugeLab Studio kurulum penceresinde kuruluyor", baslangic=time.monotonic())
        print(f"Sessiz kurulum tamamlanmadı (kod {kod}). Resmî kurulum penceresi açıldı; adımları o pencerede tamamlayın.", flush=True)
        with _harici_program(dosya, cwd=klasor) as kurucu:
            kod = kurucu.wait()
        studio = _kurulumu_bekle(1, is_)
    if is_.dur.is_set():
        return {}
    if studio is None:
        raise SystemExit(f"Studio kurulumu tamamlanmadı veya bulunamadı (kod {kod}). Kurulumu kontrol edin ve paneli yenileyin.")
    time.sleep(3)  # kurucu dosyalarını bıraksın
    _studio_penceresini_kapat()
    DURUM.update(asama="bos", ne="", baslangic=0.0)
    print("AugeLab Studio kuruldu. Sıradaki adım: AugeLab hesabınızdaki lisans kodunu girin.", flush=True)
    return {"kurulu": True}


def _studio_penceresini_kapat() -> None:
    """Resmî kurucu bitince Studio'yu kendiliğinden açarsa kapatır: Raf Kamera Studio'yu arayüzsüz kullanır."""
    for _ in range(10):
        if studio_calisiyor():
            subprocess.run(["taskkill", "/IM", EXE, "/T"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return
        time.sleep(1)
        _CALISIYOR["an"] = 0.0


# ---------------------------------------------------------------- modeller
# Korumalı model paketinin büyük dosyaları programla gelmez: kurulum dosyası kurulum sırasında Google Drive'dan indirir.
# İndirme olmadıysa panel ilk açılışta indirir (yollar.MODELLER içine). Drive dosya yerine bir uyarı sayfası verebilir
# (kota, kaldırılmış dosya): her indirme boyut ve SHA-256 ile doğrulanır.
#
# MODELLER tablosu tek kaynaktır: kurulum/modeller_iss.py bundan kurulum/modeller.iss dosyasını üretir (Inno kurulumu
# aynı dosyaları aynı adres ve özetle indirir; egitim/dene_kurulum.py ikisinin aynı olduğunu denetler).
# Bir model eklemek için tabloya bir satır yazın:
#   {"ad": "kisi.onnx.isgm", "boyut": 12_345_678, "sha256": "<64 onaltılık>", "drive": "<Google Drive dosya kimliği>"}
# "ad", motorun açtığı düz adın (raf_motor.katalog.MODEL_DOSYALARI) korumalı paket girdisidir (<düz ad>.isgm).
# Modelin yanındaki yardımcı dosya (ör. etiket okuyucunun karakter listesi etiket-oku.txt) aynı tabloya
# "duz": True ile yazılır: aynı biçimde indirilir, boyut ve SHA-256 ile doğrulanır ve motor klasörüne aynı adla gider;
# yalnızca korumalı paket başlığı (SIHIR + paket kimliği) aranmaz:
#   {"ad": "etiket-oku.txt", "boyut": 2616, "sha256": "<64 onaltılık>", "drive": "<kimlik>", "duz": True}
# Tablo boşken indirme yapılmaz ve hiçbir şey eksik sayılmaz.
MODELLER: list[dict] = [
    {"ad": "kisi.onnx.isgm", "boyut": 38626242, "sha256": "01b81e1e0406aeba49955fa281d0e1f77be30cfd39dfd78bb543b3493ff2e6a6",
     "drive": "1x85kHFRrm0fxlkaUCxyunnTsuQ6RyzSO"},
    {"ad": "iskelet.onnx.isgm", "boyut": 12065782, "sha256": "f3f034b82d33913ef5bd24f79bd85da7fc700250ea43504f25d39b624768f67f",
     "drive": "1QkOXSoLbWL5XyKGBKV0IUSYs8sTBDhua"},
    {"ad": "ozellik.onnx.isgm", "boyut": 6888956, "sha256": "139e631ca638af257848a2020085fa00b68e15c70b6a5b0ab89b93be3163ef33",
     "drive": "1w4AVdk_GGgSuxtblnLdN55L-ILk5jXG_"},
    {"ad": "urun.onnx.isgm", "boyut": 37927895, "sha256": "1889cc1e670815cf9bf50f4caaebf1c86a129bdc6adbb66f51f8097ad73a4223",
     "drive": "1R_OPYNjVH-KqnGDe7qA_7HuQPjFeM-R9"},
    {"ad": "gomme.onnx.isgm", "boyut": 16007066, "sha256": "b191ac2c99fb3cb0d40fed377b5571db5f94f268f5768e890a0f1b5af9f1649f",
     "drive": "1Qa1_Ird3gibphHlo6kDqunSd4nmeYoon"},
    {"ad": "etiket-bul.onnx.isgm", "boyut": 4826586, "sha256": "519fe76f4bcd3a4a0207378f926874f472cdcedc7ceed93dae71548269930947",
     "drive": "1P7vui5JN-0Bdc1SoQFMODN9P4b2JVLL9"},
    {"ad": "etiket-oku.onnx.isgm", "boyut": 8042091, "sha256": "2509579739a56519a80e3551860430edb32ce9216c95ba94ab54f74ac937c048",
     "drive": "14VbN6k1xJLgAcWzePM5vTg2xc7hbEH7-"},
    {"ad": "etiket-oku.txt", "boyut": 2616, "sha256": "ccbcc45730b3fbbd9050c5bc74db6a99067141ef1035e3d14889a84a6b9b1aff",
     "drive": "1Ku3NXFD6mYfCpM1rs72QK_6iO28rJt88", "duz": True},
]


def korumali(m: dict) -> bool:
    """Tablo satırı korumalı paket girdisi mi (<ad>.isgm, başlığı paket kimliğini taşır); "duz" satırlar düz dosyadır."""
    return not m.get("duz")
DRIVE_URL = "https://drive.usercontent.google.com/download?id={}&export=download&confirm=t"
MODEL_ISARETI = "community-paket.json"  # korumalı paketin işareti (raf_motor.community_model.ISARET)

# Panelin göstermesi için (model_indir yazar, model_durumu okur). asama: bos | dogrulaniyor | indiriliyor | hata
MODEL_DURUM: dict = {"asama": "bos", "ne": "", "indirilen": 0, "toplam": 0, "hata": ""}
_MODEL_KILIDI = threading.Lock()
# Bu süreçte SHA-256 ile doğrulanan model dosyaları: {ad: (yol, boyut, değişme zamanı)}. Dosya değişirse doğrulama geçersizdir.
_DOGRULANAN: dict[str, tuple] = {}
GECICI_UZANTI = ".indiriliyor"  # panelin yarım indirmesi: <ad>.<pid>.indiriliyor (kurulum dosyası kendi .yeni adını kullanır)


def model_url(m: dict) -> str:
    """Modelin indirme adresi: tabloda "url" varsa o (sınamalar), yoksa Drive kimliğinden."""
    return m.get("url") or DRIVE_URL.format(m["drive"])


def model_yolu(m: dict) -> Path:
    return yollar.MODELLER / m["ad"]


def model_gerekli() -> bool:
    """Korumalı model paketi mi kullanılıyor (işaret dosyası programla gelen paket klasöründe) ve indirilecek model var mı.
    Düz modelle ya da tablo boşken indirme gerekmez."""
    return bool(MODELLER) and (yollar.PAKET_MODELLER / MODEL_ISARETI).is_file()


def model_indirildi(m: dict) -> bool:
    """Model dosyası yerinde ve boyutu doğru mu (yalnızca boyut; tam doğrulama model_dogrulandi)."""
    try:
        return model_yolu(m).stat().st_size == m["boyut"]
    except OSError:
        return False


def _dogrulandi_isaretle(m: dict, yol: Path) -> None:
    s = yol.stat()
    _DOGRULANAN[m["ad"]] = (str(yol), s.st_size, s.st_mtime_ns)


def model_dogrulandi(m: dict) -> bool:
    """Model dosyası bu süreçte SHA-256 ile doğrulandı mı ve o andan beri değişmedi mi (dosya yeniden okunmaz)."""
    yol = model_yolu(m)
    try:
        s = yol.stat()
    except OSError:
        return False
    return _DOGRULANAN.get(m["ad"]) == (str(yol), s.st_size, s.st_mtime_ns) and s.st_size == m["boyut"]


def model_hazir(m: dict) -> bool:
    """Model kullanılabilir mi. Exe'de veri klasöründeki dosya yalnızca bu süreçte doğrulanmışsa kullanılır; kaynak koddan
    çalışırken (motor/modeller) boyut yeter."""
    return model_dogrulandi(m) if yollar.DONDURULMUS else model_indirildi(m)


def eksik_modeller() -> list[dict]:
    """Kullanılabilir olmayan modeller (korumalı paket yoksa ya da tablo boşsa boş liste)."""
    if not model_gerekli():
        return []
    return [m for m in MODELLER if not model_hazir(m)]


def model_durumu() -> dict:
    eksik = eksik_modeller()
    return {**MODEL_DURUM, "eksik": bool(eksik), "eksik_sayi": len(eksik), "sayi": len(MODELLER),
            "boyut": sum(m["boyut"] for m in eksik)}


def motor_modelleri() -> list[tuple[str, Path]]:
    """Studio'nun motor klasörüne giden model dosyaları: [(ad, kaynak yol)].
    Kaynak koddan: motor/modeller'deki dosyalar. Exe: paket dosyaları (işaret, DLL, bildirimler) yalnızca programla gelen
    güvenilir kopyadan (yollar.PAKET_MODELLER); veri klasöründen yalnızca bu süreçte doğrulanmış model dosyaları."""
    def dosyalar(klasor: Path) -> list[Path]:
        if not klasor.is_dir():
            return []
        return sorted(p for p in klasor.iterdir() if p.is_file() and not p.name.endswith((".yeni", GECICI_UZANTI)))

    if not yollar.DONDURULMUS:
        return [(p.name, p) for p in dosyalar(yollar.MODELLER)]
    tablodakiler = {m["ad"] for m in MODELLER}
    out = [(p.name, p) for p in dosyalar(yollar.PAKET_MODELLER) if p.name not in tablodakiler]
    if model_gerekli():
        out += [(m["ad"], model_yolu(m)) for m in MODELLER if model_dogrulandi(m)]
    return out


def dogrulanmis_ozet(yol: Path) -> bytes | None:
    """Yol bu süreçte doğrulanmış bir model dosyasıysa SHA-256 özeti (dosya yeniden okunmaz); değilse None."""
    for m in MODELLER:
        if Path(yol) == model_yolu(m) and model_dogrulandi(m):
            return bytes.fromhex(m["sha256"])
    return None


def _gecici_yol(m: dict) -> Path:
    return yollar.MODELLER / f"{m['ad']}.{os.getpid()}{GECICI_UZANTI}"


def _eski_gecicileri_sil() -> None:
    """Önceki açılışlardan kalan yarım indirmeleri siler (indirme sürerken çağrılmaz: _MODEL_KILIDI ile korunur)."""
    for p in yollar.MODELLER.glob(f"*{GECICI_UZANTI}") if yollar.MODELLER.is_dir() else []:
        try:
            p.unlink()
        except OSError:
            pass


def model_indir(m: dict, dur: threading.Event | None = None) -> bool:
    """Modeli bu indirmeye özgü geçici dosyaya (<ad>.<pid>.indiriliyor) indirir, boyutunu ve SHA-256 özetini doğrular,
    sonra yerine koyar ve doğrulanmış sayar. Yarım ya da doğrulanmamış dosya hiçbir zaman asıl adla kalmaz.
    Durdurulursa False; hata: SystemExit."""
    hedef = model_yolu(m)
    gecici = _gecici_yol(m)
    bozuk = (f"İndirilen dosya ({m['ad']}) model değil ya da eksik (boyut veya SHA-256 tutmuyor). Google Drive dosya yerine "
             "bir uyarı sayfası vermiş olabilir; biraz sonra yeniden deneyin.")
    MODEL_DURUM.update(asama="indiriliyor", ne=m["ad"], indirilen=0, toplam=m["boyut"], hata="")
    istek = urllib.request.Request(model_url(m), headers={"User-Agent": "RafKamera"})
    try:
        hedef.parent.mkdir(parents=True, exist_ok=True)
        ozet = hashlib.sha256()
        with urllib.request.urlopen(istek, timeout=30, context=_tls()) as yanit:
            uzunluk = int(yanit.headers.get("Content-Length") or 0)
            if uzunluk and uzunluk != m["boyut"]:
                raise SystemExit(bozuk)
            with gecici.open("wb") as cikti:
                for parca in iter(lambda: yanit.read(256 * 1024), b""):
                    if dur is not None and dur.is_set():
                        MODEL_DURUM.update(asama="bos")
                        return False
                    MODEL_DURUM["indirilen"] += len(parca)
                    if MODEL_DURUM["indirilen"] > m["boyut"]:
                        raise SystemExit(bozuk)
                    ozet.update(parca)
                    cikti.write(parca)
        if MODEL_DURUM["indirilen"] != m["boyut"] or ozet.hexdigest() != m["sha256"]:
            raise SystemExit(bozuk)
        os.replace(gecici, hedef)
        _dogrulandi_isaretle(m, hedef)
        MODEL_DURUM.update(asama="bos")
        return True
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise SystemExit("Model indirme adresinin TLS sertifikası doğrulanamadı.") from exc
        raise SystemExit("Model indirilemedi: internet bağlantısını kontrol edip yeniden deneyin.") from exc
    except (OSError, http.client.HTTPException) as exc:  # bağlantı koptu, zaman aşımı ya da diske yazılamadı
        neden = getattr(exc, "strerror", None) or "bağlantı kesildi"
        raise SystemExit(f"Model indirilemedi ({neden}). Yeniden deneyin.") from exc
    finally:
        try:
            gecici.unlink(missing_ok=True)
        except OSError:
            pass


def model_dogrula(m: dict) -> bool:
    """Yerindeki model dosyasının tam SHA-256 özetini bir kez hesaplar. Tutarsa doğrulanmış sayılır; tutmazsa dosya
    silinir (yeniden indirilsin). Dönüş: doğrulandı mı."""
    yol = model_yolu(m)
    try:
        once = yol.stat()
        if once.st_size != m["boyut"]:
            return False
        with yol.open("rb") as f:
            ozet = hashlib.file_digest(f, "sha256").hexdigest()
        sonra = yol.stat()
    except OSError:
        return False
    if ozet == m["sha256"] and (once.st_size, once.st_mtime_ns) == (sonra.st_size, sonra.st_mtime_ns):
        _DOGRULANAN[m["ad"]] = (str(yol), sonra.st_size, sonra.st_mtime_ns)
        return True
    print(f"Model dosyası bozuk ({m['ad']}: SHA-256 tutmuyor); silinip yeniden indirilecek.", flush=True)
    try:
        yol.unlink()
    except OSError:
        pass
    return False


def _model_hazirla_arkada() -> None:
    """Açılışta (ya da Yeniden dene ile): yarım indirmeleri temizler, yerindeki dosyaları doğrular, olmazsa indirir."""
    try:
        _eski_gecicileri_sil()
        for m in eksik_modeller():
            if model_indirildi(m):
                MODEL_DURUM.update(asama="dogrulaniyor", ne=m["ad"], indirilen=0, toplam=0, hata="")
                if model_dogrula(m):
                    continue
            print(f"Model indiriliyor: {m['ad']} (yaklaşık {m['boyut'] // 1_000_000} MB).", flush=True)
            model_indir(m)
            print(f"Model indirildi ve doğrulandı: {m['ad']}.", flush=True)
        MODEL_DURUM.update(asama="bos", ne="")
    except SystemExit as e:
        MODEL_DURUM.update(asama="hata", hata=str(e.code or "Model indirilemedi."))
        print(MODEL_DURUM["hata"], flush=True)
    except Exception as e:
        MODEL_DURUM.update(asama="hata", hata=f"Model indirilemedi: {e}")
        print(MODEL_DURUM["hata"], flush=True)


def model_indirmeyi_baslat() -> tuple[bool, str]:
    """Doğrulanmamış model varsa arka planda doğrular, gerekirse indirir (panelin diğer işlerini bekletmez).
    Dönüş: (başladı ya da sürüyor, mesaj)."""
    with _MODEL_KILIDI:
        if MODEL_DURUM["asama"] in ("dogrulaniyor", "indiriliyor"):
            return True, "Modeller zaten hazırlanıyor."
        eksik = eksik_modeller()
        if not eksik:
            return False, "Modeller zaten yerinde."
        ilk = eksik[0]
        MODEL_DURUM.update(asama="dogrulaniyor" if model_indirildi(ilk) else "indiriliyor", ne=ilk["ad"], indirilen=0,
                           toplam=0 if model_indirildi(ilk) else ilk["boyut"], hata="")
        threading.Thread(target=_model_hazirla_arkada, name="model-indirme", daemon=True).start()
    return True, ""
