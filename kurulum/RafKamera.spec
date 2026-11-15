import json
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
import studio_kurulum  # noqa: E402  (model tablosu: studio_kurulum.MODELLER)

# Hazır sahne: sahne dosyası yalnızca Studio'dan kaydedilebildiği için bir kez Studio'da kurulup kaydedilir (kurulum/sablon.py).
# Depoda tutulmaz (.gitignore: *.pmod); exe'ye girer ve panel onu arayüzsüz çalıştırır.
sahne = root / "kurulum" / "sahne" / "raf-kamera.pmod"
if not sahne.is_file():
    raise SystemExit(f"Hazır sahne yok: {sahne}. kurulum/sablon.py ile üretip Studio'da Farklı Kaydet ile kaydedin.")
data = [
    (str(sahne), "kurulum/sahne"),
    (str(root / "web"), "web"),
    (str(root / "motor" / "raf_motor"), "motor/raf_motor"),
    (str(root / "motor" / "deps"), "motor/deps"),
    (str(root / "LICENSE"), "."),
    (str(root / "ATIFLAR.md"), "."),
]
if (root / "ornekler").is_dir():  # örnek videolar ve ayarları (yoksa program örneksiz açılır)
    data.append((str(root / "ornekler"), "ornekler"))
kip = os.environ.get("RAF_MODEL_PAKETI", "").strip().lower()
if kip == "community":
    # Korumalı paket: modeller yalnızca AugeLab Studio'nun içinde, etkin lisansla açılır. Model dosyaları exe'ye girmez.
    paket = Path(os.environ.get("RAF_COMMUNITY_MODEL_KLASORU") or root / "kurulum" / "community-modeller")
    isaret = paket / "community-paket.json"
    try:
        bildirim = json.loads(isaret.read_text(encoding="ascii"))
        kimlik = bytes.fromhex(bildirim["id"])
        if len(kimlik) != 16 or bildirim["fixture"] is not False:
            raise ValueError("Test paketi dağıtımda kullanılamaz.")
        dll = paket / f"goruntu-{kimlik.hex()}.dll"
        if not dll.is_file():
            raise ValueError("Rust model bileşeni eksik.")
        bildirimler = paket / "RUST-NOTICES.txt"
        if not bildirimler.is_file() or not bildirimler.stat().st_size:
            raise ValueError("Rust bağımlılık bildirimleri eksik.")
        for satir in studio_kurulum.MODELLER:  # tablo boşsa denetlenecek model yok
            m = paket / satir["ad"]
            if m.stat().st_size != satir["boyut"]:
                raise ValueError(f"Boyut tabloyla aynı değil: {m.name}")
            if satir.get("duz"):  # yardımcı dosya (ör. karakter listesi): paket başlığı aranmaz
                continue
            with m.open("rb") as f:
                if f.read(24) != b"ISGMOD\x01\x00" + kimlik or m.stat().st_size <= 68:
                    raise ValueError(f"Paket başlığı geçersiz: {m.name}")
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise SystemExit(f"Korumalı model paketi eksik veya geçersiz ({paket.name}): {e}") from e
    # Büyük model dosyaları (.isgm) exe'ye girmez: kurulum dosyası onları kurulumda Google Drive'dan indirir (SHA-256 ile
    # doğrulanır), olmazsa panel ilk açılışta indirir (studio_kurulum.model_indir). Yerel dosyalar yalnızca denetlenir.
    data += [(str(m), "motor/modeller") for m in [isaret, dll]]
    data.append((str(bildirimler), "."))
elif kip == "":
    duz = root / "motor" / "modeller"  # geliştirme derlemesi: düz modeller (varsa)
    if duz.is_dir():
        data += [(str(m), "motor/modeller") for m in sorted(duz.iterdir()) if m.is_file()]
else:
    raise SystemExit(f"Bilinmeyen RAF_MODEL_PAKETI: {kip} (community ya da boş)")

a = Analysis(
    [str(root / "uygulama.py")],
    pathex=[str(root), str(root / "motor")],
    datas=data,
    hiddenimports=(
        collect_submodules("raf_motor")
    ),
    excludes=["torch", "tensorflow", "matplotlib", "pytest"],
)
# Kaynak ağacındaki derleme önbelleği (__pycache__) pakete girmez: içinde derleyen bilgisayarın dosya yolları kalır.
a.datas = [(ad, yol, tur) for ad, yol, tur in a.datas if "__pycache__" not in ad.replace("\\", "/").split("/")]
# pip --target ile gelen başlatıcılar (motor/deps/bin/*.exe) da girmez: içlerinde derleyen bilgisayarın Python yolu yazar.
a.datas = [(ad, yol, tur) for ad, yol, tur in a.datas if not ad.replace("\\", "/").startswith("motor/deps/bin/")]
# Üretilmiş kliplerin ham kopyaları (ornekler/ham, depoda da yok) programla gitmez.
a.datas = [(ad, yol, tur) for ad, yol, tur in a.datas if not ad.replace("\\", "/").startswith("ornekler/ham/")]
if kip == "community":
    # ONNX Runtime'ın örnek grafikleri Community kurulumunda kullanılmaz.
    a.datas = [(ad, yol, tur) for ad, yol, tur in a.datas if not ad.lower().endswith(".onnx")]
# Visual C++ çalışma kitaplıkları Windows'un kendi klasöründen alınır. PyInstaller bunları PATH'te ilk bulduğu yerden
# toplar; PATH'teki başka bir programın eski msvcp140.dll dosyası pakete girerse onnxruntime modeli yüklerken
# erişim ihlaliyle (0xC0000005) kapanır.
_sistem = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
_crt = {"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
        "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll", "vcomp140.dll"}
a.binaries = [(ad, str(_sistem / ad), tur) if ad.lower() in _crt and (_sistem / ad).is_file() else (ad, yol, tur) for ad, yol, tur in a.binaries]
for _ad, _yol, _tur in a.binaries:
    if _ad.lower() == "msvcp140.dll":
        import ctypes, ctypes.wintypes

        _boy = ctypes.windll.version.GetFileVersionInfoSizeW(_yol, None)
        _veri = ctypes.create_string_buffer(_boy)
        ctypes.windll.version.GetFileVersionInfoW(_yol, 0, _boy, _veri)
        _bilgi, _n = ctypes.c_void_p(), ctypes.wintypes.UINT()
        ctypes.windll.version.VerQueryValueW(_veri, "\\", ctypes.byref(_bilgi), ctypes.byref(_n))
        _ms = ctypes.cast(_bilgi, ctypes.POINTER(ctypes.wintypes.DWORD * 4)).contents[2]  # dwFileVersionMS
        if (_ms >> 16, _ms & 0xFFFF) < (14, 40):
            raise SystemExit(f"msvcp140.dll eski ({_ms >> 16}.{_ms & 0xFFFF}, kaynak: {_yol}); güncel Visual C++ 2015-2022 Redistributable (x64) kurun.")

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="RafKamera-community" if kip == "community" else "RafKamera",
    console=True,
    upx=False,
    icon=str(root / "kurulum" / "raf-kamera.ico"),  # kurulum/simge.py çizer
)
