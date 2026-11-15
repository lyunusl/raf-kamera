"""AugeLab Studio bloklarının çağırdığı işlevler.

Bloklar incedir: görüntüyü ve kamera kodunu bu işlevlere verir. Motor klasörü (raf_engine) Studio'nun özel blok
klasörünün yanındadır ve şunları içerir:

  raf_motor/   bu paket
  modeller/    model dosyaları ya da korumalı paket girdileri (katalog.MODEL_DOSYALARI)
  deps/        Studio'da olmayan kütüphaneler (onnxruntime)
  ayar.json    {"veri": "<panelin veri klasörü>"}  (kamera ayarları, kuyruk ve klipler orada)

Sahne: Raf Video → Raf Kişi → Raf Ürün → Raf Analiz.
  Raf Kişi   kişi tespiti (kisi_fps kez/sn; aradaki karelerde izlerin tahmini konumu), takip, iskelet, baş kutusu, gövde
             özellikleri (raf_motor.kisi)
  Raf Ürün   göz durumu, ürün eşleme, fiyat etiketi (raf_motor.raf, urun, etiket, raf_modeller); tek seferlik işler
             (raf_motor.gorev, kamera kodu _gorev)
  Raf Analiz müşteri ölçümleri ve etkileşimler (raf_motor.musteri), operasyon uyarıları (raf_motor.operasyon), raf sonucu
             kancası, yüz gizleme, kuyruk kayıtları (raf_motor.kayit)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time

import cv2
import numpy as np

from . import katalog, model_lisans, olcu
from .kayit import Kayitci, ciz, kuyruga_birak, yuzleri_gizle

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_KLASORU = os.path.join(KOK, "modeller")
# Arayüzsüz koşu (python -m studio run): panel her kamera için sahne şablonunu ayrı bir süreçte çalıştırır ve kameranın
# kimliğini bu ortam değişkenleriyle verir. Şablondaki "Raf Kamera Kodu" girişi o zaman yok sayılır.
ORTAM_KAMERA = "RAF_KAMERA"        # "kod#koşu"
ORTAM_ADRES = "RAF_KAMERA_ADRES"   # canlı kameranın akış adresi (şifre içerebilir: dosyaya yazılmaz)
ORTAM_DUR = "RAF_DUR"              # bu dosya oluşunca akış biter: açık olaylar kapanış kaydı bırakır
ORTAM_DENEME_SONUC = "RAF_DENEME_SONUC"  # deneme koşusunda modellerin açılıp açılmadığı bu dosyaya yazılır
ORTAM_GOREV, ORTAM_GOREV_GIRDI, ORTAM_GOREV_CIKTI = "RAF_GOREV", "RAF_GOREV_GIRDI", "RAF_GOREV_CIKTI"  # sözleşme 5
ORTAM_IS_PARCACIGI = "RAF_IS_PARCACIGI"  # (isteğe bağlı) onnxruntime iş parçacığı sayısı; yoksa onnxruntime seçer
DENEME_KOD = "_deneme"             # panelin lisans kontrolü: kamera yok, siyah kare ile modeller (ve lisans) sınanır
GOREV_KOD = "_gorev"               # tek seferlik raf işleri (göz önerme, etiket okuma, ürün tanıma)
OLCUM_ARALIGI = 30.0   # saniye: sayılar ve ısı haritası bu aralıkla panele bırakılır
NABIZ_ARALIGI = 5.0    # saniye: panel, sahnenin çalıştığını bu kayıttan anlar
CANLI_KLIP_HIZI = 8.0  # canlı akışta klibin saniyedeki kare sayısı
KISI_FPS = 3.0         # kamera ayarında kisi_fps yoksa
KISI_GIRIS = 640       # kişi tespitinin giriş genişliği (kamera ayarında kisi_giris ile değişir)
ISKELET_EN_COK = 12    # bir karede iskeleti çıkarılan en çok kişi (raf/dolap bölgesine yakın olanlar)
OZELLIK_EN_COK = 8     # bir karede özellik modeline verilen en çok kişi
GIZLE_GUVEN = 0.2      # izi olmayan (yeni, düşük güvenli) tespitlerin de başı gizlenir
ARA_PAY = 0.35         # analiz edilmeyen karede (tahmini konum) baş kutusu bu kadar genişletilerek gizlenir


def _hata_json(neden: str) -> str:
    """Bir analiz bloğu çalışmadığında sonuç yerine verilen değer. Boş liste "bir şey yok" demektir; bu ise "bilinmiyor"
    demektir: Raf Analiz bu karede ölçüm yapmaz, olay kaydetmez, görüntü vermez ve panele hata bırakır."""
    return json.dumps({"hata": neden}, ensure_ascii=False)


def _sonuc_json(alan: str, sira: int, liste: list, **ek) -> str:
    """`sira`: analizin sıra numarası. Aradaki (analiz edilmeyen) karelerde aynı değer yinelenebilir."""
    return json.dumps({"sira": sira, **ek, alan: liste}, ensure_ascii=False)


def kod_ve_kosu(kamera_kod) -> tuple[str, str]:
    """Kamera girişi "kod" ya da "kod#koşu" biçimindedir; koşu değişince bloklar baştan başlar.
    Arayüzsüz koşuda kamera ortam değişkeninden gelir ve girişteki değerin yerini alır."""
    kamera_kod = os.environ.get(ORTAM_KAMERA) or kamera_kod
    kod, _, kosu = str(kamera_kod or "").strip().partition("#")
    return kod.strip(), kosu


def veri_klasoru() -> str:
    with open(os.path.join(KOK, "ayar.json"), encoding="utf-8") as f:
        return json.load(f)["veri"]


def kamera_ayari(kod: str) -> tuple[dict, float]:
    yol = os.path.join(veri_klasoru(), "ayar", f"{kod}.json")
    with open(yol, encoding="utf-8") as f:
        return json.load(f), os.path.getmtime(yol)


def _ayar_onbellekli(state: dict, kod: str) -> tuple[dict, float]:
    """Kamera ayarı; dosya değişmedikçe yeniden okunmaz (her karede çağrılır)."""
    yol = os.path.join(veri_klasoru(), "ayar", f"{kod}.json")
    m = os.path.getmtime(yol)
    if state.get("_ayar_m") != (yol, m):
        with open(yol, encoding="utf-8") as f:
            state["_ayar"] = json.load(f)
        state["_ayar_m"] = (yol, m)
    return state["_ayar"], m


def _goruntu(image) -> np.ndarray | None:
    if image is None:
        return None
    a = np.asarray(image)
    if a.ndim == 2:
        a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    elif a.ndim == 3 and a.shape[2] == 4:
        a = a[:, :, :3]
    return np.ascontiguousarray(a) if a.ndim == 3 and a.size else None


def _saniye(zaman) -> float | None:
    """Zaman girişi: saniye (video dosyası) ya da None (canlı akış: -1, boş ya da bağlı değil)."""
    try:
        t = float(zaman) if zaman is not None and str(zaman) != "" else None
    except (TypeError, ValueError):
        t = None
    return t if t is not None and t >= 0 else None


class _CanliOkuyucu:
    """Canlı akışı arka planda okur ve yalnızca son kareyi tutar: kareler kuyrukta birikmez, analiz hep en yeni kareyle
    yapılır. Bağlantı koparsa birkaç saniyede bir yeniden bağlanır."""

    def __init__(self, adres: str):
        import threading

        self.adres, self.kare, self.sira, self.durum = adres, None, 0, "bekliyor: kameraya bağlanılıyor"
        self._dur = threading.Event()
        self._kilit = threading.Lock()
        threading.Thread(target=self._oku, name="raf-canli", daemon=True).start()

    def _oku(self) -> None:
        bekle = 1.0
        while not self._dur.is_set():
            cap = cv2.VideoCapture(self.adres, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                cap.release()
                self.durum = "bekliyor: kameraya bağlanılamadı, yeniden deneniyor"
                self._dur.wait(bekle)
                bekle = min(10.0, bekle * 2)
                continue
            bekle = 1.0
            while not self._dur.is_set():
                ok, fr = cap.read()
                if not ok:
                    self.durum = "bekliyor: görüntü kesildi, yeniden bağlanılıyor"
                    break
                with self._kilit:
                    self.kare, self.sira = fr, self.sira + 1
            cap.release()

    def son(self):
        with self._kilit:
            return self.kare, self.sira

    def kapat(self) -> None:
        self._dur.set()


def _durduruldu() -> bool:
    """Panel arayüzsüz koşuyu durdururken önce bu dosyayı oluşturur: akış "bitti" olur, açık olaylar kapanır."""
    dur = os.environ.get(ORTAM_DUR)
    return bool(dur) and os.path.exists(dur)


def _video_ac(state: dict, kod: str, kosu: str) -> str | None:
    """Kaynağı açar. Dönüş: hata durumu ya da None."""
    state["kosu"] = kosu
    try:
        ayar, _ = kamera_ayari(kod)
    except Exception as e:
        return f"hata: kamera ayarı okunamadı ({kod}): {e}"
    kamera = ayar.get("kamera") or {}
    if kamera.get("tur") in ("rtsp", "onvif", "http"):
        adres = os.environ.get(ORTAM_ADRES, "")
        if not adres:
            return "hata: kameranın akış adresi verilmedi (sahneyi Raf Kamera paneli başlatır)"
        state.update(kod=kod, canli=_CanliOkuyucu(adres), sira=0, n=0, bitti=False)
        return None
    if kamera.get("tur") != "dosya":
        return "hata: bu kamera türü Raf Video ile okunamıyor"
    yol = kamera.get("yol", "")
    yol = yol if os.path.isabs(yol) else os.path.join(veri_klasoru(), yol)
    cap = cv2.VideoCapture(yol)
    if not cap.isOpened():
        return f"hata: video açılamadı: {os.path.basename(yol)}"
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    state.update(kod=kod, cap=cap, fps=fps if 1 <= fps <= 120 else 25.0, n=0, toplam=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), bitti=False)
    return None


def _video_kapat(state: dict) -> None:
    if state.get("cap") is not None:
        state["cap"].release()
    if state.get("canli") is not None:
        state["canli"].kapat()
    state.clear()


def video(state: dict, kamera_kod: str):
    """Raf Video bloğu: kameranın ayarındaki video dosyasını kare kare okur. Arayüzsüz koşuda canlı kameranın akışını da
    okur (adres ortam değişkeninden gelir).
    Dönüş: (görüntü | None, zaman (sn; canlı akışta -1: duvar saati kullanılır), bitti, durum). Dosya bitince ya da panel
    durdurunca bir kez bitti=True döner, sonra görüntü vermez."""
    kod, kosu = kod_ve_kosu(kamera_kod)
    if kod in (DENEME_KOD, GOREV_KOD):  # deneme / tek seferlik iş: modeli sınamak ya da işi başlatmak için siyah kare yeter
        return np.zeros((360, 640, 3), np.uint8), -1.0, False, "ok deneme karesi"
    if state.get("kod") != kod or state.get("kosu") != kosu:
        _video_kapat(state)
        hata = _video_ac(state, kod, kosu)
        if hata:
            return None, 0.0, False, hata
    canli = state.get("canli")
    if state["bitti"]:
        return None, -1.0 if canli else state["n"] / state["fps"], False, f"bitti: {state['n']} kare"
    if _durduruldu():
        state["bitti"] = True
        if canli:
            canli.kapat()
        else:
            state["cap"].release()
        return None, -1.0 if canli else state["n"] / state["fps"], True, f"bitti: durduruldu, {state['n']} kare"
    if canli:
        kare, sira = canli.son()
        if kare is None or sira == state["sira"]:
            return None, -1.0, False, canli.durum if kare is None else "ok: yeni kare bekleniyor"
        state["sira"] = sira
        state["n"] += 1
        return kare, -1.0, False, f"ok {state['n']} kare"
    ok, fr = state["cap"].read()
    if not ok:
        state["bitti"] = True
        state["cap"].release()
        return None, state["n"] / state["fps"], True, f"bitti: {state['n']} kare"
    t = state["n"] / state["fps"]
    state["n"] += 1
    return fr, t, False, f"ok {state['n']}" + (f" / {state['toplam']}" if state["toplam"] > 0 else "") + " kare"


# ============================================================================================== Raf Kişi
def _is_parcacigi() -> int | None:
    try:
        return int(os.environ.get(ORTAM_IS_PARCACIGI) or 0) or None
    except ValueError:
        return None


def _kisi_modelleri(state: dict, giris: int) -> dict:
    from .kisi import Algilayici, Iskelet, Ozellik

    imza = (giris, _is_parcacigi())
    if state.get("model_imza") != imza:
        state.pop("modeller", None)
        veri, ip = veri_klasoru(), _is_parcacigi()
        state["modeller"] = {
            "tespit": Algilayici(os.path.join(MODEL_KLASORU, katalog.KISI), veri, giris, ip),
            "iskelet": Iskelet(os.path.join(MODEL_KLASORU, katalog.ISKELET), veri, ip),
            "ozellik": Ozellik(os.path.join(MODEL_KLASORU, katalog.OZELLIK), veri, ip),
        }
        state["model_imza"] = imza
    return state["modeller"]


def _yuvarla(b) -> list[float]:
    return [round(float(v), 1) for v in b[:4]]


def kisi(state: dict, image, kamera_kod: str, zaman=None) -> tuple[str, str]:
    """Raf Kişi bloğu. Dönüş: (JSON, durum).

    JSON: {"sira": n, "t": sn, "yeni": analiz bu karede mi yapıldı, "boyut": [W, H], "kisiler": [
            {"iz": takip no, "b": [x1, y1, x2, y2], "p": güven, "durum": "izleniyor" | "kayip", "bas": [x1, y1, x2, y2],
             "baslar": [[x1, y1, x2, y2], ...] (gizlenecek bütün baş bölgeleri; ilki "bas"),
             "k": 17x[x, y, güven] ya da null, "oz": {"n", "kadin", "yas": {"genc", "yetiskin", "yasli"}} ya da null}]}
    Ayrıca izi olmayan tespitlerin başları için {"iz": null, "durum": "gizle", "baslar": [...]} öğesi olabilir.
    Koordinatlar kare pikselidir. "kayip": iz bu analizde görülmedi, tahmini konumdadır (yüzü yine gizlenir, ölçüme girmez).
    Kişi analizi `kisi_fps` kez/sn yapılır; aradaki karelerde izlerin tahmini konumu ("yeni": false, aynı sira) verilir.
    Tespit çalışmazsa {"hata": "..."} verilir: "kimse yok" ile karışmaz. Deneme koşusunda modelleri açar (lisans kontrolü)."""
    fr = _goruntu(image)
    if fr is None:
        return state.get("son_json") or _sonuc_json("kisiler", 0, []), "bekliyor: görüntü yok"
    kod, kosu = kod_ve_kosu(kamera_kod)
    if kod == DENEME_KOD:
        return _model_deneme(state)
    if kod == GOREV_KOD:
        return _sonuc_json("kisiler", 0, []), "ok tek seferlik iş"
    try:
        ayar, _ = _ayar_onbellekli(state, kod)
    except Exception as e:
        return _hata_json(f"kamera ayarı okunamadı ({kod})"), f"hata: kamera ayarı okunamadı ({kod}): {e}"
    H, W = fr.shape[:2]
    t = _saniye(zaman)
    if state.get("kosu") != kosu or state.get("boyut") != (W, H) or (t is not None and state.get("son_t") is not None and t < state["son_t"]):
        from .kisi import Izci, Oylama

        state.update(kosu=kosu, boyut=(W, H), sira=0, son_json=None, son_t=None, son_analiz=None, t0=time.monotonic(),
                     izci=Izci(), oylama=Oylama(), son_bas={})
    if t is None:
        t = time.monotonic() - state["t0"]
    state["son_t"] = t
    try:
        fps = float(ayar.get("kisi_fps") or KISI_FPS)
    except (TypeError, ValueError):
        fps = KISI_FPS
    fps = min(25.0, max(0.5, fps))
    if state["son_analiz"] is not None and t - state["son_analiz"] < 1.0 / fps - 1e-3:
        return _ara_kare(state, t), state.get("son_durum", "ok")
    try:
        modeller = _kisi_modelleri(state, int(ayar.get("kisi_giris") or KISI_GIRIS))
    except model_lisans.LisansHatasi as e:
        state.pop("model_imza", None)
        return _hata_json(f"lisans: {e}"), f"hata: lisans: {e}"
    except Exception as e:
        state.pop("model_imza", None)
        return _hata_json(f"kişi modeli yüklenemedi: {type(e).__name__}"), f"hata: kişi modeli yüklenemedi: {type(e).__name__}: {e}"
    t0 = time.perf_counter()
    try:
        sonuc, ozet = _kisi_analizi(state, fr, ayar, t, modeller)
    except model_lisans.LisansHatasi as e:
        state.pop("model_imza", None)
        return _hata_json(f"lisans: {e}"), f"hata: lisans: {e}"
    except Exception as e:
        return _hata_json(f"kişi analizi çalışmadı: {type(e).__name__}"), f"hata: kişi analizi çalışmadı: {type(e).__name__}: {e}"
    state["son_analiz"] = t
    state["sira"] += 1
    state["son_kisiler"] = sonuc
    state["son_json"] = _sonuc_json("kisiler", state["sira"], sonuc, t=round(t, 3), yeni=True, boyut=[W, H])
    state["son_durum"] = f"ok {sum(1 for k in sonuc if k['durum'] == 'izleniyor')} kişi · {1000 * (time.perf_counter() - t0):.0f} ms · {ozet}"
    return state["son_json"], state["son_durum"]


def _kisi_analizi(state: dict, fr: np.ndarray, ayar: dict, t: float, modeller: dict) -> tuple[list[dict], str]:
    from .kisi import bas_kutulari, bas_kutusu, dik_mi

    H, W = fr.shape[:2]
    kutular, guven = modeller["tespit"].calistir(fr)
    izler = state["izci"].guncelle(t, kutular, guven)
    etkin = [z for z in izler if z["durum"] == "izleniyor"]
    # İskelet yalnızca raf ya da dolap bölgesine yakın kişilerde (uzanma, ilgi); uzaktakilerde baş kutusu kişi kutusundan.
    gerek = any(katalog.ozellik_ayari(ayar, k) is not None for k in ("uzanma", "ilgi", "toplu_alma"))
    yakin_bolgeler = [b["poly"] for b in olcu.bolgeler(ayar, W, H) if b["tur"] in ("raf", "dolap") and b["poly"] is not None]
    iskelet_adaylari = []
    if gerek and yakin_bolgeler:
        iskelet_adaylari = [z for z in etkin if any(olcu.kutu_bolge_ortusur(p, z["b"], 0.3) for p in yakin_bolgeler)]
        iskelet_adaylari = sorted(iskelet_adaylari, key=lambda z: -(z["b"][3] - z["b"][1]))[:ISKELET_EN_COK]
    noktalar = modeller["iskelet"].calistir(fr, [z["b"] for z in iskelet_adaylari]) if iskelet_adaylari else []
    k_iz = {z["iz"]: k for z, k in zip(iskelet_adaylari, noktalar)}
    # Gövde özellikleri: yalnızca demografi açıksa, uygun (büyük, dik, kesik olmayan) kırpıntılarda, iz başına saniyede bir.
    oylama = state["oylama"]
    demo = katalog.ozellik_ayari(ayar, "demografi")
    ozn = 0
    if demo:
        adaylar = [z for z in etkin if oylama.ister_mi(z["iz"], t) and dik_mi(z["b"], k_iz.get(z["iz"]), W, H, demo["en_az_boy"])]
        adaylar = sorted(adaylar, key=lambda z: -(z["b"][3] - z["b"][1]))[:OZELLIK_EN_COK]
        if adaylar:
            olas = modeller["ozellik"].calistir(fr, [z["b"] for z in adaylar])
            for z, o in zip(adaylar, olas):
                oylama.ekle(z["iz"], t, o)
            ozn = len(adaylar)
    oylama.temizle({z["iz"] for z in izler})
    out = []
    for z in izler:
        k = k_iz.get(z["iz"])
        baslar = bas_kutulari(z["b"], k)
        state["son_bas"][z["iz"]] = (np.asarray(z["b"], np.float32).copy(), baslar)
        out.append({"iz": z["iz"], "b": _yuvarla(z["b"]), "p": round(float(z["p"]), 3), "durum": z["durum"], "bas": baslar[0],
                    "baslar": baslar, "k": k, "oz": oylama.ozet(z["iz"])})
    for iz in [i for i in state["son_bas"] if i not in {z["iz"] for z in izler}]:
        del state["son_bas"][iz]
    # Gizlilik: henüz izi olmayan ya da düşük güvenli tespitlerin başı da gizlenir (ölçüme girmez).
    from .kisi import iou_matris

    izli = np.array([z["b"] for z in izler], np.float32).reshape(-1, 4)
    sec = guven >= GIZLE_GUVEN
    ek = kutular[sec]
    if len(ek) and len(izli):
        ek = ek[iou_matris(ek, izli).max(1) < 0.5]
    state["ek_bas"] = [bas_kutusu(b) for b in ek]
    if state["ek_bas"]:
        out.append({"iz": None, "durum": "gizle", "baslar": state["ek_bas"]})
    return out, f"iskelet {len([k for k in noktalar if k])}/{len(etkin)}" + (f" · özellik {ozn}" if demo else "")


def _ara_kare(state: dict, t: float) -> str:
    """Analiz edilmeyen kare: izlerin tahmini kutuları; baş kutusu kutuyla birlikte kaydırılır."""
    if state.get("son_kisiler") is None:
        return state.get("son_json") or _sonuc_json("kisiler", state.get("sira", 0), [])
    tahmin = {z["iz"]: z for z in state["izci"].tahmin(t)}
    out = []
    for k in state["son_kisiler"]:
        if k.get("durum") == "gizle":
            out.append(k)
            continue
        z = tahmin.get(k["iz"])
        onceki = state["son_bas"].get(k["iz"])
        if z is None or onceki is None:
            out.append({**k, "k": None})
            continue
        b0, baslar = onceki
        b = np.asarray(z["b"], np.float32)
        dx = float((b[0] + b[2]) / 2 - (b0[0] + b0[2]) / 2)
        dy = float(b[1] - b0[1])
        kaymis = [[round(x[0] + dx, 1), round(x[1] + dy, 1), round(x[2] + dx, 1), round(x[3] + dy, 1)] for x in baslar]
        out.append({**k, "b": _yuvarla(b), "bas": kaymis[0], "baslar": kaymis, "k": None})
    W, H = state["boyut"]
    return _sonuc_json("kisiler", state["sira"], out, t=round(t, 3), yeni=False, boyut=[W, H])


# ============================================================================================== Raf Ürün
def urun(state: dict, image, kamera_kod: str, zaman=None) -> tuple[str, str]:
    """Raf Ürün bloğu. Dönüş: (JSON {"sira": n, "gozler": [...], "doluluk", "uyum", "referans"}, durum).

    Göz durumu, ürün eşleme ve fiyat etiketi `raf_motor.raf.analiz(state, fr, ayar, t, veri_klasoru) -> (JSON, durum)`.
    Raf analizi yüklenemez ya da çalışmazsa {"hata": "..."} verilir (boş liste "göz yok" ile karışmaz).
    Tek seferlik işler (kamera kodu _gorev) `_gorev_kancasi` ile `raf_motor.gorev`e gider."""
    fr = _goruntu(image)
    if fr is None:
        return state.get("son_json") or _sonuc_json("gozler", 0, []), "bekliyor: görüntü yok"
    kod, kosu = kod_ve_kosu(kamera_kod)
    if kod == DENEME_KOD:
        return _sonuc_json("gozler", 0, []), "ok deneme"
    if kod == GOREV_KOD:
        return _gorev_kancasi(state)
    if state.get("kosu") != kosu:
        state.update(kosu=kosu, sira=0, son_json=None, raf={})
    try:
        from . import raf as raf_modulu
    except Exception as e:  # boş liste "göz yok" demek olurdu: yüklenemeyen raf analizi hata değeri verir
        return _hata_json(f"raf analizi yüklenemedi: {type(e).__name__}"), f"hata: raf analizi yüklenemedi: {type(e).__name__}: {e}"
    try:
        ayar, _ = _ayar_onbellekli(state, kod)
        gozler, durum = raf_modulu.analiz(state["raf"], fr, ayar, _saniye(zaman), veri_klasoru())
    except model_lisans.LisansHatasi as e:
        return _hata_json(f"lisans: {e}"), f"hata: lisans: {e}"
    except Exception as e:
        neden = str(e)[:120] if isinstance(e, RuntimeError) else type(e).__name__
        return _hata_json(f"raf analizi çalışmadı: {neden}"), f"hata: raf analizi çalışmadı: {type(e).__name__}: {e}"
    if isinstance(gozler, str):  # raf tarafı JSON'u kendisi üretti
        state["son_json"] = gozler
    else:
        state["sira"] = state.get("sira", 0) + 1
        state["son_json"] = _sonuc_json("gozler", state["sira"], gozler)
    return state["son_json"], durum


def _gorev_kancasi(state: dict) -> tuple[str, str]:
    """RAF KANCASI (sözleşme 5): tek seferlik iş bir kez çalışır. `raf_motor.gorev.calistir(is_adi, girdi: dict, veri: str)
    -> dict` çağrılır; çıktı RAF_GOREV_CIKTI'ya .tmp + os.replace ile yazılır. Hata olursa {"hata": "..."} yazılır."""
    if state.get("gorev_bitti"):
        return _sonuc_json("gozler", 0, []), state.get("gorev_durum", "ok iş bitti")
    state["gorev_bitti"] = True
    is_adi = os.environ.get(ORTAM_GOREV, "")
    cikti = os.environ.get(ORTAM_GOREV_CIKTI, "")
    try:
        with open(os.environ.get(ORTAM_GOREV_GIRDI, ""), encoding="utf-8") as f:
            girdi = json.load(f)
        from . import gorev

        sonuc = gorev.calistir(is_adi, girdi, veri_klasoru())
    except ImportError:
        sonuc = {"hata": "bu sürümde tek seferlik raf işleri yok"}
    except Exception as e:
        sonuc = {"hata": f"{type(e).__name__}: {e}"}
    if cikti:
        try:
            with open(cikti + ".tmp", "w", encoding="utf-8") as f:
                json.dump(sonuc, f, ensure_ascii=False)
            os.replace(cikti + ".tmp", cikti)
        except OSError:
            pass
    state["gorev_durum"] = "hata: " + str(sonuc["hata"]) if isinstance(sonuc, dict) and sonuc.get("hata") else f"ok iş bitti: {is_adi}"
    return _sonuc_json("gozler", 0, []), state["gorev_durum"]


# ============================================================================================== modeller, deneme
def modelleri_ac() -> dict:
    """katalog.MODEL_DOSYALARI içindeki her modeli açar (korumalı pakette AugeLab Studio lisansı burada doğrulanır).
    Dönüş: {ad: oturum}. Hiç model tanımlı değilse onnxruntime yüklenmez ve boş sözlük döner."""
    if not katalog.MODEL_DOSYALARI:
        return {}
    from .kisi import oturum

    out = {}
    for ad in katalog.MODEL_DOSYALARI:
        yol = os.path.join(MODEL_KLASORU, ad)
        if not katalog.model_var(yol):
            raise RuntimeError(f"model dosyası yok: {ad}")
        out[ad] = oturum(yol, veri_klasoru())
    return out


def _ort_bilgisi() -> dict | None:
    """Yüklenen onnxruntime: sürümü ve nereden geldiği ("studio": Studio'nun kendi paketi, "deps": motorla gelen kopya).
    deps sys.path'in sonuna eklenir: Studio'da onnxruntime varsa o kullanılır, yoksa motorun kopyası."""
    import sys

    ort = sys.modules.get("onnxruntime")
    if ort is None:
        return None
    yol = os.path.abspath(getattr(ort, "__file__", "") or "")
    kaynak = "deps" if os.path.join(KOK, "deps") in yol else "studio"
    return {"surum": getattr(ort, "__version__", "?"), "kaynak": kaynak}


def _model_deneme(state: dict) -> tuple[str, str]:
    """Lisans kontrolü: bütün modelleri açar ve sonucu ORTAM_DENEME_SONUC dosyasına bir kez yazar. Kamera ayarı gerekmez."""
    if state.get("deneme_yazildi"):
        return _sonuc_json("kisiler", 0, []), state.get("deneme_durum", "deneme bitti")
    sonuc = {"ok": False, "hata": ""}
    try:
        oturumlar = modelleri_ac()
        sonuc = {"ok": True, "modeller": sorted(oturumlar), "onnxruntime": _ort_bilgisi()}
    except model_lisans.LisansHatasi as e:
        sonuc["hata"] = f"lisans: {e}"
    except Exception as e:  # model dosyası yok, paket açılamadı, onnxruntime yüklenemedi...
        sonuc["hata"] = f"{type(e).__name__}: {e}"
    yol = os.environ.get(ORTAM_DENEME_SONUC)
    if yol:
        try:
            with open(yol, "w", encoding="utf-8") as f:
                json.dump(sonuc, f, ensure_ascii=False)
        except OSError:
            pass
    state["deneme_yazildi"] = True
    state["deneme_durum"] = (f"ok {len(sonuc['modeller'])} model açıldı" if sonuc["ok"] else f"hata: {sonuc['hata']}")
    return _sonuc_json("kisiler", 0, []), state["deneme_durum"]


# ============================================================================================== Raf Analiz
def _oku(metin, alan: str) -> tuple[list, dict, str | None]:
    """Kişi ya da Raf girişini okur. Dönüş: (liste, bütün JSON, hata nedeni ya da None)."""
    try:
        veri = json.loads(metin) if metin else []
    except (TypeError, ValueError):
        return [], {}, f"{alan} okunamadı"
    if isinstance(veri, dict) and isinstance(veri.get(alan), list):
        return veri[alan], veri, None
    if isinstance(veri, list):
        return veri, {}, None
    return [], {}, (str(veri.get("hata") or "bilinmiyor") if isinstance(veri, dict) else f"{alan} okunamadı")


def _kur(state: dict, kod: str, ayar: dict, degisim: float, W: int, H: int) -> None:
    from .musteri import Musteri
    from .operasyon import Operasyon

    kamera = ayar.get("kamera") or {}
    bas = dt.datetime.now().replace(microsecond=0)
    if kamera.get("tur") == "dosya" and kamera.get("baslangic"):
        try:
            bas = dt.datetime.fromisoformat(kamera["baslangic"])
        except ValueError:
            pass
    veri = veri_klasoru()
    kayitci = Kayitci(veri, kod, ayar.get("ad", kod), W, H, CANLI_KLIP_HIZI)
    kayitci.kosu = state.get("kosu") or ""
    bolgeler = olcu.bolgeler(ayar, W, H)
    state.update(kod=kod, degisim=degisim, boyut=(W, H), n=0, t0=time.monotonic(), son_t=None, bas_zaman=bas,
                 olcum_bas=None, olcum_n=0, son_cizili=None, kayitci=kayitci, ayar=ayar, bolgeler=bolgeler,
                 musteri=Musteri(bolgeler, ayar, W, H, bas),
                 operasyon=Operasyon(bolgeler, ayar, W, H, bas, os.path.join(veri, "ayar", f"_referans_{kod}.jpg")),
                 son_sira=None, son_analiz_t=None, vurgu=[], duranlar={}, raf_kanca={})


def _olcum_birak(state: dict, t: float) -> None:
    """Son ölçüm döneminin sayılarını (sözleşme 4.2) kuyruğa bırakır."""
    if state.get("olcum_bas") is None or not state.get("olcum_n"):
        return
    veri, izgara = state["musteri"].olcum()
    bas = state["bas_zaman"] + dt.timedelta(seconds=state["olcum_bas"])
    state["kayitci"].olcum({"bas": bas.isoformat(), "sure_sn": round(max(0.0, t - state["olcum_bas"]), 1),
                            "analiz": state["olcum_n"], "veri": veri, "izgara": izgara})
    state["olcum_bas"], state["olcum_n"] = t, 0


def _etkilesim_birak(state: dict, kayitlar: list[dict]) -> None:
    for e in kayitlar:
        state["kayitci"]._birak({**e, "kamera": state["kod"]})


def _bitir(state: dict, isaret: bool = True) -> None:
    kayitci = state.get("kayitci")
    if kayitci is None:
        return
    t = state.get("son_t") or 0.0
    _etkilesim_birak(state, state["musteri"].bitir(t))
    _olcum_birak(state, t)
    kayitci.bitir(state["operasyon"].bitir() + _raf_kancasi_bitir(state), isaret)
    if state.get("son_cizili") is not None:
        kayitci.son_kare(state["son_cizili"], zorla=True, temiz=state.get("son_temiz"), kisiler=state.get("son_temiz_kisiler"))
    state["kayitci"] = None


def _raf_kancasi(state: dict, t: float, fr: np.ndarray, gozler: list, raf_veri: dict, musteri_sonuc: dict) -> dict:
    """RAF KANCASI (raf/ürün tarafı doldurur). Raf Ürün'ün çıktısı (sözleşme 4.3 için göz durumları) burada olaya, `raf`
    kaydına ve alma/geri koyma doğrulamasına çevrilir. Beklenen modül işlevi:
        raf.analiz_sonucu(state["raf_kanca"], t, gozler, raf_veri, musteri_sonuc, baglam) -> {
            "baslayan": [...], "suren": [...], "biten": [...],     # sözleşme 4.1 olay kayıtları (raf_motor.olay.Olaylar ile)
            "kayitlar": [...],                                       # kuyruğa bırakılacak "raf" kayıtları (4.3, kamera eklenir)
            "isaretler": [{"eylem": "aldi"|"birakti", "bolge", "goz", "t", "sure_sn"}]}   # uzanma doğrulamaları
    `musteri_sonuc["uzanma_biten"]` ([{"bolge", "goz", "bas", "son"}]) göz değişimiyle eşlenecek uzanmalardır;
    `baglam` = {"kod", "bas_zaman", "boyut", "bolgeler", "ayar", "kisiler"}. Modül yoksa boş sonuç verilir."""
    bos = {"baslayan": [], "suren": [], "biten": []}
    try:
        from . import raf as raf_modulu
    except ImportError:
        return bos
    islev = getattr(raf_modulu, "analiz_sonucu", None)
    if islev is None:
        return bos
    baglam = {"kod": state["kod"], "bas_zaman": state["bas_zaman"], "boyut": state["boyut"], "bolgeler": state["bolgeler"],
              "ayar": state["ayar"], "kisiler": musteri_sonuc.get("kisiler", [])}
    s = islev(state["raf_kanca"], t, gozler, raf_veri, musteri_sonuc, baglam) or {}
    for kayit in s.get("kayitlar") or []:
        state["kayitci"]._birak({"kamera": state["kod"], "kamera_ad": state["ayar"].get("ad", state["kod"]), **kayit})
    acik = {"aldi": state["musteri"].oz.get("alma"), "birakti": state["musteri"].oz.get("geri_koyma")}
    for i in s.get("isaretler") or []:
        if not acik.get(i.get("eylem")):
            continue  # alma / geri_koyma özelliği kapalı
        # iz ve adet yalnızca motor içinde kalır (toplu_alma); etkileşim kaydına girmez
        _etkilesim_birak(state, [state["musteri"].raf_isareti(i["eylem"], i["bolge"], i.get("goz"), i["t"], i.get("sure_sn", 0.0),
                                                             iz=i.get("iz"), adet=i.get("adet") or 1)])
    return {k: list(s.get(k) or []) for k in bos}


def _raf_kancasi_bitir(state: dict) -> list[dict]:
    """RAF KANCASI: akış bitince açık raf olayları. Beklenen: raf.bitir(state["raf_kanca"]) -> [kapanan olay kayıtları]."""
    try:
        from . import raf as raf_modulu
    except ImportError:
        return []
    islev = getattr(raf_modulu, "bitir", None)
    return list(islev(state["raf_kanca"]) or []) if islev else []


def _kisi_kutulari(kisiler: list[dict], ek_baslar: list, W: int, H: int) -> list[list[float]]:
    """Karedeki bütün kişi kutuları (kayıp izler ve izi olmayan başlar dahil), 0-1: temiz karenin yanına yazılır."""
    out = []
    for b in [k["b"] for k in kisiler if k.get("b")] + list(ek_baslar):
        try:
            x1, y1, x2, y2 = (float(v) for v in b[:4])
        except (TypeError, ValueError):
            continue
        out.append([max(0.0, x1 / W), max(0.0, y1 / H), min(1.0, x2 / W), min(1.0, y2 / H)])
    return out


def _kutular(kisiler: list[dict], duranlar: dict) -> list[dict]:
    out = []
    for k in kisiler:
        if not isinstance(k, dict) or "b" not in k or k.get("durum") == "kayip":
            continue
        out.append({"b": k["b"], "renk": (40, 150, 245) if k.get("iz") in duranlar else (180, 150, 20)})
    return out


def analiz(state: dict, image, kisiler_json: str, raf_json: str, kamera_kod: str, zaman=None, bitti: bool = False):
    """Raf Analiz bloğu. `zaman`: görüntünün saniye cinsinden zamanı (video dosyasında Raf Video'dan gelir; canlı akışta
    duvar saati kullanılır). `bitti`: akış bitti, açık olayları kapat ve "bitti" kaydını bırak.
    Dönüş: (yüzleri gizlenmiş işaretli görüntü, başlayan olaylar JSON, durum, yeni olay var mı).
    Gizlilik: diske ya da çıkışa giden her kare önce yüzleri gizlenmiş kopyadır; kişi analizi çalışmıyorsa görüntü verilmez."""
    if bitti:  # akış bitti: kayıtçı henüz kurulmamış olsa da görüntü çıkışı boş kalır
        if state.get("kayitci") is None:
            return None, "[]", "bitti: akış kapandı", False
        _bitir(state)
        return None, "[]", "bitti: akış kapandı", False
    fr = _goruntu(image)
    if fr is None:
        return None, "[]", "bekliyor: görüntü yok", False
    kod, kosu = kod_ve_kosu(kamera_kod)
    if kod in (DENEME_KOD, GOREV_KOD):
        return np.zeros_like(fr), "[]", "ok deneme", False
    if state.get("kosu") != kosu:  # yeni çalıştırma: önceki akıştan kalanı kapat, baştan başla
        _bitir(state, isaret=False)
        state["kosu"] = kosu
    try:
        ayar, degisim = _ayar_onbellekli(state, kod)
    except Exception as e:
        return np.zeros_like(fr), "[]", f"hata: kamera ayarı okunamadı ({kod}): {e}", False
    H, W = fr.shape[:2]
    if state.get("kayitci") is None or state.get("kod") != kod or state.get("degisim") != degisim or state.get("boyut") != (W, H):
        _bitir(state, isaret=False)
        _kur(state, kod, ayar, degisim, W, H)
    kayitci = state["kayitci"]
    kisiler, kisi_veri, hata = _oku(kisiler_json, "kisiler")
    ek_baslar = [bb for k in kisiler if isinstance(k, dict) and k.get("durum") == "gizle" for bb in k.get("baslar") or []]
    kisiler = [k for k in kisiler if isinstance(k, dict) and "b" in k]
    gozler, raf_veri, hata2 = _oku(raf_json, "gozler")
    neden = hata or hata2
    if hata:
        # Kişi analizi çalışmıyor (model yok, yüklenemedi, lisans yok). Bu "kimse yok" sayılmaz: yüzler bilinmediği için kare
        # kaydedilmez ve çıkışa da verilmez; ölçüm yapılmaz, olay kaydedilmez; panel işi hatayla durdurur.
        if time.monotonic() - state.get("hata_kaydi", 0.0) >= 5.0:
            state["hata_kaydi"] = time.monotonic()
            try:
                kuyruga_birak(veri_klasoru(), kod, {"tur": "hata", "kamera": kod, "kosu": kosu, "metin": neden})
            except OSError:
                pass
        return np.zeros_like(fr), "[]", f"hata: analiz çalışmıyor, görüntü kaydedilmiyor: {neden}", False
    t = _saniye(zaman)
    if t is None:  # canlı akış (Raf Video -1 verir) ya da zaman girişi bağlı değil: duvar saati
        t = time.monotonic() - state["t0"]
    state["son_t"] = t
    state["n"] += 1
    if state["olcum_bas"] is None:
        state["olcum_bas"] = t
    if time.monotonic() - state.get("nabiz", 0.0) >= NABIZ_ARALIGI:
        state["nabiz"] = time.monotonic()
        nabiz = {"tur": "nabiz", "kamera": kod, "kare": state["n"]}
        if hata2:  # raf analizi çalışmıyor: kişi analizi sürer ("hata" kaydı işi durdururdu); panel bunu nabızdan görebilir
            nabiz["raf_hata"] = hata2
        kayitci._birak(nabiz)
    sonuc = {"baslayan": [], "biten": [], "suren": []}
    yeni = kisi_veri.get("yeni", True) and kisi_veri.get("sira") != state["son_sira"]
    if yeni:
        state["son_sira"] = kisi_veri.get("sira")
        aralik = t - state["son_analiz_t"] if state["son_analiz_t"] is not None else 1.0 / KISI_FPS
        state["son_analiz_t"] = t
        state["olcum_n"] += 1
        m = state["musteri"].adim(t, aralik, kisiler)
        m["kisiler"] = kisiler
        state["duranlar"] = m["duranlar"]
        state["son_kuyruk"] = m["kuyruk"]  # (sınama ve durum satırı için) kasa bölgesi → bekleyen kişi
        _etkilesim_birak(state, m["etkilesim"])
        o = state["operasyon"].adim(t, fr, kisiler, m)
        state["vurgu"] = o["vurgu"]
        r = _raf_kancasi(state, t, fr, gozler, raf_veri, m) if not hata2 else {"baslayan": [], "suren": [], "biten": []}
        for a in sonuc:
            sonuc[a] = o[a] + r[a]
    an = (state["bas_zaman"] + dt.timedelta(seconds=t)).strftime("%d.%m.%Y %H:%M:%S")
    # Gizlilik: diske giden her kare önce yüzleri gizlenmiş kopyadır. Tahmini konumdaki (analiz edilmeyen kare ya da kayıp
    # iz) baş kutusu daha geniş gizlenir.
    cizili = fr.copy()
    for k in kisiler:
        baslar = k.get("baslar") or ([k["bas"]] if k.get("bas") else [])
        yuzleri_gizle(cizili, baslar, 0.15 if (yeni and k.get("durum") != "kayip") else ARA_PAY)
    yuzleri_gizle(cizili, ek_baslar, 0.15 if yeni else ARA_PAY)
    # temiz_kare.jpg: yüzleri gizlenmiş, çizimsiz kopya (yalnızca kişi analizi yapılan karede; Kayitci saniyede bir yazar)
    temiz = cizili.copy() if yeni else None
    vurgulu = {v["bolge"] for v in state["vurgu"]}
    ust = " · ".join(dict.fromkeys(v["etiket"] for v in state["vurgu"]))
    cizili = ciz(cizili, state["bolgeler"], ust, f"{ayar.get('ad', kod)} · {an} · yüzler gizlendi",
                 _kutular(kisiler, state["duranlar"]), vurgulu)
    if yeni:
        # Kayıtçıya (son kare, olay karesi, klip) yalnızca kişi analizinin yapıldığı kareler gider: aradaki karelerde yeni
        # giren bir kişinin başı henüz bilinmez. Klip bu yüzden analiz hızındadır (Kayitci boşlukları son kareyle doldurur).
        kutular = _kisi_kutulari(kisiler, ek_baslar, W, H)
        kayitci.kare(t, cizili, sonuc, temiz, kisiler=kutular)
        state["son_cizili"] = cizili
        state["son_temiz"] = temiz
        state["son_temiz_kisiler"] = kutular
    if t - state["olcum_bas"] >= OLCUM_ARALIGI:
        _olcum_birak(state, t)
    durum = f"ok {sum(1 for k in kisiler if k.get('durum') != 'kayip')} kişi, {len(gozler)} göz · {an}"
    if hata2:
        durum += f" · raf analizi çalışmıyor: {hata2}"
    return cizili, json.dumps(sonuc["baslayan"], ensure_ascii=False), durum, bool(sonuc["baslayan"])


def kapat(state: dict) -> None:
    """Sahne durdurulurken çağrılabilir: açık olayları ve sayıları kuyruğa bırakır."""
    _bitir(state)
