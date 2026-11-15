"""Motorun birleşik uçtan uca sınaması: dört blok zinciri (Raf Video -> Raf Kişi -> Raf Ürün -> Raf Analiz) -> Kayitci ->
kuyruk dosyaları. Studio'nun yaptığı gibi blokların processCode'u derlenir ve motor geçici bir marketplace/raf_engine
klasörüne konur (motor_ortak.Zincir). Studio'nun kendi Python'uyla doğrudan çalıştırılabilir (Studio açılmaz, lisans
gerekmez):

  "%LOCALAPPDATA%\\Programs\\AugeLab Studio\\Python\\python.exe" egitim/dene_motor_birlesik.py [bölüm ...]

Bölümler: katalog, gorev, raf, musteri, birlikte, hata, hiz, bellek (verilmezse katalog gorev raf musteri birlikte hata).
Görüntüler depoda değildir: RAF_TEST_GORSELLERI (yoksa depo yanındaki raf-kamera-modeller/test-gorselleri) ve
RAF_DENEME_VIDEOLARI (kafe videoları). İsteğe bağlı RAF_DEPS: motor/deps yoksa raf_engine/deps'e kopyalanacak klasör.
Çıktı (işaretli, yüzü gizli kareler + rapor.json): RAF_BIRLESIK_CIKTI ya da %TEMP%/raf_birlesik.

UYARI: raf senaryosu durağan bir Commons raf fotoğrafının düzenlenmesiyle (yama, takas, etiket yapıştırma) üretilmiş
videodur; "birlikte" senaryosu gerçek kafe videosuna yapıştırılmış raf fotoğrafıdır (yapay birleşim). Gerçek mağaza
kamerası görüntüsü değildir.
"""
from __future__ import annotations

import gc
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BURA = Path(__file__).resolve().parent
sys.path.insert(0, str(BURA))
sys.path.insert(0, str(BURA / "raf"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import senaryo  # noqa: E402  (raf düzenleme yardımcıları; içe aktarırken depodaki motoru yola ekler: aşağıda temizlenir)
import ortak as raf_ortak  # noqa: E402
from motor_ortak import KOK, Zincir, video_klasoru  # noqa: E402

# senaryo/ortak depodaki motor klasörünü yola ekledi: zincir motoru raf_engine kopyasından yüklemeli (Studio gibi)
sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p)) != os.path.normcase(raf_ortak.MOTOR)]
for _m in [m for m in sys.modules if m == "raf_motor" or m.startswith("raf_motor.")]:
    del sys.modules[_m]

CIKTI = Path(os.environ.get("RAF_BIRLESIK_CIKTI") or Path(tempfile.gettempdir()) / "raf_birlesik")
CIKTI.mkdir(parents=True, exist_ok=True)
GORSELLER = Path(raf_ortak.GORSELLER)
RAPOR: dict = {}
SONUC: list[tuple[str, str, bool]] = []
_BOLUM = [""]


def denetle(ad: str, kosul, ek: str = "") -> bool:
    SONUC.append((_BOLUM[0], ad, bool(kosul)))
    print(("  geçti  " if kosul else "  KALDI  ") + ad + (f" ({ek})" if ek else ""), flush=True)
    return bool(kosul)


def bolum(ad: str) -> None:
    _BOLUM[0] = ad
    print(f"\n=== {ad}", flush=True)


# --------------------------------------------------------------------------------------------------- ortak
OLAY_ALANLARI = {"tur", "kosu", "kimlik", "zaman", "kamera", "kamera_ad", "kural", "kural_ad", "kategori", "duzey", "onem",
                 "olasilik", "puan", "ciddi", "sure_sn", "x", "y", "aciklama", "bitti"}
RAF_OLAY_EK = {"bolge", "bolge_ad", "goz", "urun", "urun_ad", "gorev", "deger", "beklenen"}
GOZ_ALANLARI = {"bolge", "goz", "durum", "doluluk", "adet", "urun", "gorulen", "benzerlik", "etiket", "fiyat"}
OLCUM_GENEL = {"gecen", "duran", "uzanan", "alan", "birakan", "bekleme_sn", "bekleme_sayi", "giren", "cikan", "kuyruk_ort",
               "kuyruk_en_cok", "kadin", "erkek", "yas_genc", "yas_yetiskin", "yas_yasli", "kisi_ort"}
OLCUM_BOLGE = {"gecen", "duran", "uzanan", "alan", "birakan", "bekleme_sn", "bekleme_sayi", "kadin", "erkek", "yas_genc",
               "yas_yetiskin", "yas_yasli", "ilgi_sn"}
YASAK = {"iz", "track", "kadin", "erkek", "yas", "yas_genc", "yas_yetiskin", "yas_yasli", "oz", "cinsiyet", "b", "bas", "baslar"}


def adim(z: Zincir, kam: str, st: tuple) -> dict:
    sv, sk, su, sa = st
    v = z._cagir(z.V, sv, Kamera=kam)
    k = z._cagir(z.K, sk, Image=v["Image"], Kamera=kam, Zaman=v["Zaman"])
    u = z._cagir(z.U, su, Image=v["Image"], Kamera=kam, Zaman=v["Zaman"])
    a = z._cagir(z.A, sa, Image=v["Image"], Kisiler=k["Kisiler"], Raf=u["Raf"], Kamera=kam, Zaman=v["Zaman"], Bitti=v["Bitti"])
    return {"v": v, "k": k, "u": u, "a": a}


def motor(z: Zincir, ad: str):
    """Zincirin yüklediği (raf_engine kopyasındaki) motor modülü."""
    import importlib

    m = importlib.import_module(f"raf_motor.{ad}")
    assert os.path.normcase(str(z.motor)) in os.path.normcase(m.__file__), m.__file__
    return m


def gorev_kos(z: Zincir, ad: str, girdi: dict) -> tuple[dict, str]:
    """Tek seferlik iş: Studio'nun --step koşusu gibi kamera kodu _gorev ile zinciri üç adım çalıştırır."""
    gp, cp = z.gecici / f"gorev_{ad}_girdi.json", z.gecici / f"gorev_{ad}_cikti.json"
    gp.write_text(json.dumps(girdi, ensure_ascii=False), encoding="utf-8")
    cp.unlink(missing_ok=True)
    os.environ.update(RAF_GOREV=ad, RAF_GOREV_GIRDI=str(gp), RAF_GOREV_CIKTI=str(cp))
    try:
        st: tuple = ({}, {}, {}, {})
        for _ in range(3):
            s = adim(z, "_gorev#g1", st)
    finally:
        for k in ("RAF_GOREV", "RAF_GOREV_GIRDI", "RAF_GOREV_CIKTI"):
            os.environ.pop(k, None)
    return (json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else {"hata": "çıktı yazılmadı"}), s["u"]["Durum"]


def kayit_denetle(kayitlar: list[dict], ad: str) -> dict:
    """Bütün kayıtların sözleşme alanları ve gizlilik (etkileşim ve olayda iz/yaş/cinsiyet yok)."""
    olaylar = [k for k in kayitlar if k["tur"] == "olay"]
    eksik = [sorted(OLAY_ALANLARI - set(o)) for o in olaylar if OLAY_ALANLARI - set(o)]
    denetle(f"{ad}: {len(olaylar)} olay kaydında 4.1 + iskelet alanları tam", not eksik, str(eksik[:2]))
    raf_olay = [o for o in olaylar if o["kategori"] == "raf"]
    if raf_olay:
        eks = [sorted(RAF_OLAY_EK - set(o)) for o in raf_olay if RAF_OLAY_EK - set(o)]
        denetle(f"{ad}: raf olaylarında bolge/goz/urun/urun_ad/gorev/deger/beklenen var", not eks, str(eks[:2]))
    rafk = [k for k in kayitlar if k["tur"] == "raf"]
    if rafk:
        ust = [sorted({"kosu", "kamera", "kamera_ad", "zaman", "doluluk", "uyum", "gozler"} - set(k)) for k in rafk]
        ust = [u for u in ust if u]
        gz = [sorted(GOZ_ALANLARI - set(g)) for k in rafk for g in k["gozler"] if GOZ_ALANLARI - set(g)]
        denetle(f"{ad}: {len(rafk)} raf kaydında 4.3 alanları tam", not ust and not gz, str((ust[:1], gz[:1])))
    olc = [k for k in kayitlar if k["tur"] == "olcum"]
    if olc:
        yanlis = set()
        for o in olc:
            for a, v in o["veri"].items():
                if a.startswith("b:"):
                    if a.split(":")[-1] not in OLCUM_BOLGE:
                        yanlis.add(a)
                elif a not in OLCUM_GENEL:
                    yanlis.add(a)
                if not isinstance(v, (int, float)):
                    yanlis.add(a + "(sayı değil)")
        iz = [o["izgara"] for o in olc if o.get("izgara")]
        boy_ok = all(len(m) == 18 and all(len(r) == 32 for r in m) for g in iz for m in g["katmanlar"].values())
        denetle(f"{ad}: {len(olc)} ölçüm kaydının anahtarları 4.2'de, ısı ızgarası 32x18", not yanlis and boy_ok,
                f"yanlış {sorted(yanlis)[:5]}, ızgara {len(iz)}")
    sizan = []
    for k in kayitlar:
        if k["tur"] in ("etkilesim", "olay"):
            bul = YASAK.intersection(k)
            if bul:
                sizan.append((k["tur"], sorted(bul)))
    denetle(f"{ad}: etkileşim/olay kayıtlarında iz, yaş, cinsiyet ya da kutu yok", not sizan, str(sizan[:3]))
    return {"olay": len(olaylar), "raf": len(rafk), "olcum": len(olc),
            "etkilesim": sum(1 for k in kayitlar if k["tur"] == "etkilesim"),
            "nabiz": sum(1 for k in kayitlar if k["tur"] == "nabiz"), "hata": sum(1 for k in kayitlar if k["tur"] == "hata"),
            "bitti": sum(1 for k in kayitlar if k["tur"] == "bitti")}


def olay_ozeti(kayitlar: list[dict]) -> dict:
    """kimlik -> {kural, goz, bolge, bas (ilk kayıt saati), bit (bitti kaydı saati), deger, beklenen, gorev, son_sure}."""
    out: dict = {}
    for k in kayitlar:
        if k["tur"] != "olay":
            continue
        o = out.setdefault(k["kimlik"], {"kural": k["kural"], "bolge": k.get("bolge"), "goz": k.get("goz"),
                                         "bas_kayit": k["zaman"], "bitti": False, "deger": k.get("deger"),
                                         "beklenen": k.get("beklenen"), "gorev": k.get("gorev"), "urun_ad": k.get("urun_ad"),
                                         "aciklama": k.get("aciklama")})
        o["son_sure"] = k.get("sure_sn")
        if k.get("bitti"):
            o["bitti"] = True
    return out


def onnx_bilgisi() -> str:
    o = sys.modules.get("onnxruntime")
    return f"onnxruntime {getattr(o, '__version__', '?')} {getattr(o, '__file__', '?')}" if o else "onnxruntime yüklenmedi"


def kucult(im: np.ndarray, gen: int = 960) -> np.ndarray:
    H, W = im.shape[:2]
    return cv2.resize(im, (gen, int(gen * H / W)), interpolation=cv2.INTER_AREA) if W > gen else im


def gozleri_ciz(im: np.ndarray, raf_json: str, ayar_gozler: dict) -> np.ndarray:
    """Analiz çıkışının üstüne Raf JSON'undaki göz durumları (yalnız göz kontrolü için)."""
    out = im.copy()
    H, W = out.shape[:2]
    renk = {"dolu": (0, 200, 0), "az": (0, 200, 255), "bos": (0, 0, 255), "yanlis": (255, 0, 255), "kapali": (160, 160, 160),
            "bilinmiyor": (255, 255, 255)}
    try:
        gozler = json.loads(raf_json).get("gozler") or []
    except Exception:
        gozler = []
    for g in gozler:
        k = ayar_gozler.get(g["goz"])
        if k is None:
            continue
        x1, y1, x2, y2 = int(k[0] * W), int(k[1] * H), int(k[2] * W), int(k[3] * H)
        cv2.rectangle(out, (x1, y1), (x2, y2), renk.get(g["durum"], (255, 255, 255)), 2)
        t = f"{g['goz']}:{g['durum']}" + (f" {g.get('etiket')}" if g.get("etiket") not in (None, "bakilmadi") else "")
        cv2.putText(out, t, (x1 + 2, y1 + 14), 0, 0.45, (0, 0, 0), 3)
        cv2.putText(out, t, (x1 + 2, y1 + 14), 0, 0.45, (255, 255, 255), 1)
    return out


def damga(im: np.ndarray, metin: str) -> np.ndarray:
    out = im.copy()
    cv2.putText(out, metin, (10, out.shape[0] - 40), 0, 0.9, (0, 0, 0), 4)
    cv2.putText(out, metin, (10, out.shape[0] - 40), 0, 0.9, (0, 255, 255), 2)
    return out


def video_yaz(yol: Path, kareler, fps: float, boyut: tuple[int, int]) -> int:
    w = cv2.VideoWriter(str(yol), cv2.VideoWriter_fourcc(*"mp4v"), fps, boyut)
    if not w.isOpened():
        raise RuntimeError("VideoWriter açılmadı")
    n = 0
    for fr in kareler:
        w.write(fr)
        n += 1
    w.release()
    return n


# =================================================================================================== katalog
def b_katalog() -> None:
    bolum("katalog bağlantısı (model adları, varsayılanlar, durumlar)")
    z = Zincir("raf_bir_")
    try:
        st = ({}, {}, {}, {})
        adim(z, "_deneme#d1", st)  # motoru raf_engine kopyasından yükler (deneme koşusu)
        katalog, rm = motor(z, "katalog"), motor(z, "raf_modeller")
        sinama = motor(z, "sinama")
        denetle("katalog raf model adları raf_modeller ile aynı",
                [katalog.URUN, katalog.GOMME, katalog.ETIKET_BUL, katalog.ETIKET_OKU] == rm.MODEL_DOSYALARI)
        denetle("MODEL_DOSYALARI 7 model, karakter listesi içinde değil",
                len(katalog.MODEL_DOSYALARI) == 7 and rm.ETIKET_HARF not in katalog.MODEL_DOSYALARI)
        denetle("az_stok.doluluk_esik 0.55, yanlis_urun.benzerlik_esik 0.45",
                katalog.varsayilan_ayarlar("az_stok")["doluluk_esik"] == 0.55
                and katalog.varsayilan_ayarlar("yanlis_urun")["benzerlik_esik"] == 0.45)
        raf_kod = ("bos_raf", "az_stok", "yanlis_urun", "etiket_yok", "fiyat_farkli")
        denetle("raf özelliklerinin modelleri tanımlı",
                all(katalog.KURAL[k]["modeller"] for k in raf_kod))
        uyumsuz = [k["kod"] for k in katalog.KURALLAR if k["durum"] != ((sinama.SINAMA.get(k["kod"]) or {}).get("durum") or "deneysel")]
        denetle("katalog durumları sinama.py ile tutarlı", not uyumsuz, str(uyumsuz))
        denetle("21 özellik kodu", len(katalog.KURALLAR) == 21)
        RAPOR["durumlar"] = {k["kod"]: k["durum"] for k in katalog.KURALLAR}
        print("  ", onnx_bilgisi())
    finally:
        z.temizle()


# =================================================================================================== gorev + raf
RAF_FOTO = "raf_08"


def raf_hazirla(z: Zincir, kod: str, foto: str = RAF_FOTO, yol: Path | None = None) -> dict:
    """Tek seferlik işlerle (sözleşme 5) planogram ve katalog kurar: gozler -> katalog görselleri -> etiketler -> urun_tani."""
    yol = yol or GORSELLER / f"{foto}.jpg"
    im = cv2.imread(str(yol))
    H, W = im.shape[:2]
    poly = senaryo.FOTOLAR[foto]["poly"]
    g, durum_g = gorev_kos(z, "gozler", {"kare": str(yol), "bolgeler": [{"kimlik": "b1", "poly": poly}]})
    gozler = [x for x in g.get("gozler") or [] if (x["kutu"][2] - x["kutu"][0]) * W >= 20 and (x["kutu"][3] - x["kutu"][1]) * H >= 20]
    etiketli = [x for x in gozler if x.get("etiket")]
    e, durum_e = gorev_kos(z, "etiketler", {"kare": str(yol), "kutular": [x["etiket"] for x in etiketli]})
    fiyat = {i: r.get("fiyat") for i, r in enumerate(e.get("etiketler") or [])}
    # katalog: her gözün ilk yüzü (panel kameradaki kareden kırpar); aynı ürün kuralına uyan gözler aynı ürün
    rm, gv, ur = motor(z, "raf_modeller"), motor(z, "gorev"), motor(z, "urun")
    m = rm.paylasilan()
    veri = z.veri
    (veri / "urunler" / "gorsel").mkdir(parents=True, exist_ok=True)
    yuzler = []
    for x in gozler:
        x1, y1, x2, y2 = x["kutu"][0] * W, x["kutu"][1] * H, x["kutu"][2] * W, x["kutu"][3] * H
        yuzler.append(im[int(y1):int(y2), int(x1):int(x1 + (x2 - x1) / max(1, x["adet"]))])
    v = m.gomme(yuzler)
    rk = [ur.renk_ozeti(y) for y in yuzler]
    urunler, kimlik, ayar_gozler = [], [], []
    for i, x in enumerate(gozler):
        u = next((kimlik[j] for j in range(i) if gv.ayni_urun(float(v[i] @ v[j]), float(rk[i] @ rk[j]))), None)
        f = fiyat.get(etiketli.index(x)) if x in etiketli else None
        if u is None:
            u = f"u{i}"
            cv2.imwrite(str(veri / "urunler" / "gorsel" / f"{u}.jpg"), yuzler[i])
            urunler.append({"kimlik": u, "ad": f"Ürün {i}", "barkod": "", "kategori": "", "fiyat": f, "gorseller": [f"{u}.jpg"]})
        kimlik.append(u)
        ayar_gozler.append({"kimlik": f"g{i}", "kutu": x["kutu"], "urun": u, "adet": x["adet"], "etiket": x.get("etiket"),
                            "fiyat": f})
    (veri / "urunler" / "urunler.json").write_text(json.dumps(urunler, ensure_ascii=False), encoding="utf-8")
    t, durum_t = gorev_kos(z, "urun_tani", {"kare": str(yol), "kutular": [x["kutu"] for x in gozler]})
    dogru = sum(1 for r, u in zip(t.get("urunler") or [], kimlik) if r.get("urun") == u)
    return {"im": im, "W": W, "H": H, "poly": poly, "gozler": ayar_gozler, "urunler": urunler, "gorev": {
        "gozler": (len(gozler), len(etiketli), durum_g, g.get("sure_ms")), "etiketler": (e, durum_e),
        "urun_tani": (dogru, len(gozler), durum_t, t.get("sure_ms"), t.get("hata"))}}


def b_gorev() -> None:
    bolum("d. tek seferlik işler (_gorev, RAF_GOREV*) gerçek raf fotoğrafında")
    z = Zincir("raf_bir_")
    try:
        h = raf_hazirla(z, "gv")
        ng, ne, dg, sg = h["gorev"]["gozler"]
        denetle("gozler işi göz önerdi", ng > 0 and dg.startswith("ok"), f"{ng} göz, {ne} etiket kutusu, {sg} ms, durum '{dg}'")
        e, de = h["gorev"]["etiketler"]
        okunan = [(r["metin"], r["fiyat"]) for r in e.get("etiketler") or []]
        denetle("etiketler işi okudu", "etiketler" in e and de.startswith("ok"), f"{okunan}")
        dogru, n, dt_, st_, ht = h["gorev"]["urun_tani"]
        denetle("urun_tani işi kendi gözünün ürününü buldu", n and dogru >= 0.7 * n, f"{dogru}/{n}, {st_} ms, hata {ht}")
        # bilinmeyen iş ve bozuk girdi: hata değeri
        r, d = gorev_kos(z, "olmayan_is", {"kare": "x"})
        denetle("bilinmeyen iş {hata} yazar", "hata" in r and d.startswith("hata"), str(r))
        r, d = gorev_kos(z, "gozler", {"kare": str(z.gecici / "yok.jpg"), "bolgeler": []})
        denetle("okunamayan kare {hata} yazar", "hata" in r, str(r))
        RAPOR["gorev"] = {"gozler": [ng, ne, sg], "etiketler": okunan, "urun_tani": [dogru, n, st_]}
        im = h["im"].copy()
        raf_ortak.ciz_kutular(im, [g["kutu"] for g in h["gozler"]], yazi=[f"{g['kimlik']}/{g['urun']}x{g['adet']}" for g in h["gozler"]])
        raf_ortak.ciz_kutular(im, [g["etiket"] for g in h["gozler"] if g["etiket"]], renk=(0, 160, 255),
                              yazi=[str(g["fiyat"]) for g in h["gozler"] if g["etiket"]])
        cv2.imwrite(str(CIKTI / "d_gorev_gozler.jpg"), im)
    finally:
        z.temizle()


def raf_videosu(h: dict, yol: Path, fps: float = 2.0) -> dict:
    """Düzenlenmiş durağan kareler: dolu -> bir göz boş -> yeniden dolu -> ürün takası -> geri -> etiket fiyatı değişti ->
    başka gözün etiketi kaldırıldı. Her kareye gürültü + JPEG."""
    im, W, H = h["im"], h["W"], h["H"]
    gz = h["gozler"]
    px = lambda k: [k[0] * W, k[1] * H, k[2] * W, k[3] * H]  # noqa: E731
    alan = lambda g: (g["kutu"][2] - g["kutu"][0]) * (g["kutu"][3] - g["kutu"][1])  # noqa: E731
    sirali = sorted(range(len(gz)), key=lambda i: -alan(gz[i]))
    bos_kaynak = senaryo.FOTOLAR[RAF_FOTO]["bos"]
    etiketli = [i for i in range(len(gz)) if gz[i]["etiket"] and gz[i]["fiyat"] is not None]
    A = sirali[0]
    # takas: farklı ürünlü, en büyük ikinci göz; kaynak başka üründen büyük bir göz
    B = next(i for i in sirali[1:] if i != A and i not in etiketli)
    C = next(i for i in sirali if gz[i]["urun"] != gz[B]["urun"] and i not in (A, B))
    D = etiketli[0] if etiketli else None
    E = next((i for i in etiketli if gz[i]["fiyat"] != gz[D]["fiyat"]), None) if D is not None else None
    F = etiketli[1] if len(etiketli) > 1 and etiketli[1] != E else (etiketli[2] if len(etiketli) > 2 else None)
    asamalar = [("dolu", 0, 40), ("bos", 40, 100), ("dolu2", 100, 150), ("takas", 150, 260), ("dolu3", 260, 300),
                ("fiyat", 300, 520), ("etiketsiz", 520, 660)]
    bos_im = senaryo.bosalt(im, bos_kaynak, px(gz[A]["kutu"]))
    takas_im = senaryo.yapistir(im, px(gz[C]["kutu"]), px(gz[B]["kutu"]))
    fiyat_im = im
    if E is not None:  # etiketteki büyük fiyat rakamları silinip başka gözün fiyatı aynı boyda yeniden basılır
        x1, y1, x2, y2 = (int(v) for v in px(gz[D]["etiket"]))
        w, h = x2 - x1, y2 - y1
        fiyat_im = im.copy()
        a, b, c, d = x1 + int(0.18 * w), y1 + int(0.22 * h), x2 - int(0.12 * w), y1 + int(0.62 * h)
        zemin = np.median(im[y1:y2, x1:x2].reshape(-1, 3), 0)
        fiyat_im[b:d, a:c] = zemin
        metin = f"{gz[E]['fiyat'] / 1000:.3f}" if gz[E]["fiyat"] >= 1000 else f"{gz[E]['fiyat']:.2f}"
        olcek = (d - b) / 24.0
        (tw, th), _ = cv2.getTextSize(metin, cv2.FONT_HERSHEY_SIMPLEX, olcek, max(1, int(olcek * 2)))
        cv2.putText(fiyat_im, metin, (a + max(0, (c - a - tw) // 2), d - 1), cv2.FONT_HERSHEY_SIMPLEX, olcek, (20, 20, 20),
                    max(1, int(olcek * 2)), cv2.LINE_AA)
    etiketsiz_im = fiyat_im
    if F is not None:
        fx = [int(v) for v in px(gz[F]["etiket"])]
        etiketsiz_im = fiyat_im.copy()
        etiketsiz_im[fx[1]:fx[3], fx[0]:fx[2]] = senaryo.bos_yama(im, bos_kaynak, fx[2] - fx[0], fx[3] - fx[1])
    goruntu = {"dolu": im, "bos": bos_im, "dolu2": im, "takas": takas_im, "dolu3": im, "fiyat": fiyat_im, "etiketsiz": etiketsiz_im}
    rng = np.random.default_rng(7)

    def kareler():
        for ad, a, b in asamalar:
            for _ in range(int((b - a) * fps)):
                yield senaryo.gurultu(goruntu[ad], rng)

    n = video_yaz(yol, kareler(), fps, (W, H))
    cv2.imwrite(str(yol.parent / "fiyat_duzenli.jpg"), fiyat_im)
    if D is not None:
        a = [int(v) for v in px(gz[D]["etiket"])]
        pay = 30
        once = im[max(0, a[1] - pay):a[3] + pay, max(0, a[0] - pay):a[2] + pay]
        sonra = fiyat_im[max(0, a[1] - pay):a[3] + pay, max(0, a[0] - pay):a[2] + pay]
        cv2.imwrite(str(CIKTI / "a_etiket_once_sonra.jpg"), cv2.resize(np.hstack([once, sonra]), None, fx=3, fy=3,
                                                                     interpolation=cv2.INTER_NEAREST))
    cv2.imwrite(str(CIKTI / "a_duzenlemeler.jpg"), np.vstack([np.hstack([kucult(bos_im, 640), kucult(takas_im, 640)]),
                                                              np.hstack([kucult(fiyat_im, 640), kucult(etiketsiz_im, 640)])]))
    return {"A": gz[A]["kimlik"], "B": gz[B]["kimlik"], "C": gz[C]["kimlik"], "D": gz[D]["kimlik"] if D is not None else None,
            "E": gz[E]["kimlik"] if E is not None else None, "F": gz[F]["kimlik"] if F is not None else None,
            "asamalar": asamalar, "kare": n, "fiyat_D": gz[D]["fiyat"] if D is not None else None,
            "fiyat_E": gz[E]["fiyat"] if E is not None else None}


def b_raf() -> None:
    bolum("a. raf senaryosu (düzenlenmiş durağan raf fotoğrafı videosu, gerçek zincir)")
    z = Zincir("raf_bir_")
    try:
        h = raf_hazirla(z, "rafv")
        vid = z.gecici / "raf_senaryo.mp4"
        s = raf_videosu(h, vid)
        print("  gözler:", len(h["gozler"]), "ürün:", len(h["urunler"]), "senaryo:", {k: v for k, v in s.items() if k != "asamalar"})
        if s["D"]:
            dk = next(g["etiket"] for g in h["gozler"] if g["kimlik"] == s["D"])
            r_, _ = gorev_kos(z, "etiketler", {"kare": str(z.gecici / "fiyat_duzenli.jpg"), "kutular": [dk]})
            print("  düzenlenmiş etiketin tek seferlik okuması:", r_)
            RAPOR["raf_etiket_tek_okuma"] = r_
        cv2.imwrite(str(z.veri / "ayar" / "_referans_rafv.jpg"), h["im"])  # "Rafı dolu olarak kaydet"
        z.kamera("rafv", str(vid), [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": h["poly"], "gozler": h["gozler"]}],
                 {"yanlis_urun": {"acik": True}, "etiket_yok": {"acik": True, "sure_sn": 30},
                  "fiyat_farkli": {"acik": True, "sure_sn": 30}, "raf_ayar": {"etiket_araligi_sn": 60}},
                 raf_araligi_sn=10, referans={"zaman": "2026-11-15T09:59:00"})
        kutu = {g["kimlik"]: g["kutu"] for g in h["gozler"]}
        anlar = {30: "dolu", 90: "bos", 240: "takas", 500: "fiyat", 650: "etiketsiz"}
        resimler, durumlar, t0 = [], [], time.perf_counter()
        st = ({}, {}, {}, {})
        while True:
            r = adim(z, "rafv#k1", st)
            if r["v"]["Image"] is None:
                if r["v"]["Bitti"] or str(r["v"]["Durum"]).startswith(("hata", "bitti")):
                    break
                continue
            tt = float(r["v"]["Zaman"])
            durumlar.append(r["u"]["Durum"])
            for a in [a for a in anlar if tt >= a]:
                resimler.append(damga(kucult(gozleri_ciz(r["a"]["Image"], r["u"]["Raf"], kutu), 800), f"t={tt:.0f} {anlar.pop(a)}"))
        sure = time.perf_counter() - t0
        cv2.imwrite(str(CIKTI / "a_raf_kareler.jpg"), np.vstack([np.hstack(resimler[i:i + 2]) if len(resimler[i:i + 2]) == 2
                                                                else np.hstack([resimler[i], np.zeros_like(resimler[i])])
                                                                for i in range(0, len(resimler), 2)]))
        kay = z.kayitlar()
        say = kayit_denetle(kay, "raf")
        olaylar = olay_ozeti(kay)
        print("  zincir süresi", round(sure, 1), "sn, kayıtlar", say)
        for k, o in olaylar.items():
            print("   olay", o["kural"], o["goz"], "ilk", o["bas_kayit"][11:], "bitti" if o["bitti"] else "AÇIK", "süre", o["son_sure"],
                  "değer", o["deger"], "beklenen", o["beklenen"], "görev", o["gorev"], o["urun_ad"], "-", o["aciklama"])
        rafk = [k for k in kay if k["tur"] == "raf"]
        for g_ in (s["D"], s["F"]):
            print("   etiket akışı", g_, [(k["zaman"][14:], gg["etiket"], gg["fiyat"]) for k in rafk for gg in k["gozler"] if gg["goz"] == g_])
        temiz = z.veri / "cikti" / "rafv" / "temiz_kare.jpg"
        denetle("temiz_kare.jpg ve son_kare.jpg yazıldı", temiz.is_file() and (temiz.parent / "son_kare.jpg").is_file())
        denetle("raf kayıtları referans 'kayitli'", rafk and all(k.get("referans") == "kayitli" for k in rafk), f"{len(rafk)} kayıt")

        def bul(kural, goz):
            return [o for o in olaylar.values() if o["kural"] == kural and o["goz"] == goz]

        bas = lambda o: (time.mktime(time.strptime(o["bas_kayit"], "%Y-%m-%dT%H:%M:%S")) - time.mktime(time.strptime("2026-11-15T10:00:00", "%Y-%m-%dT%H:%M:%S")))  # noqa: E731
        b = bul("bos_raf", s["A"])
        denetle(f"boşaltılan göz {s['A']}: bos_raf açıldı (40 sn'de boşaldı) ve dolunca kapandı",
                len(b) == 1 and 40 < bas(b[0]) <= 100 and b[0]["bitti"] and b[0]["gorev"] is True,
                f"{[(bas(o), o['bitti'], o['son_sure'], o['deger'], o['beklenen']) for o in b]}")
        y = bul("yanlis_urun", s["B"])
        denetle(f"takas edilen göz {s['B']}: yanlis_urun açıldı (150 sn'de) ve geri konunca kapandı",
                len(y) == 1 and 150 < bas(y[0]) <= 300 and y[0]["bitti"],
                f"{[(bas(o), o['bitti'], o['son_sure'], o['deger'], o['beklenen']) for o in y]}")
        if s["D"]:
            f = bul("fiyat_farkli", s["D"])
            denetle(f"etiketi değişen göz {s['D']}: fiyat_farkli (beklenen {s['fiyat_D']}, yapıştırılan {s['fiyat_E']})",
                    len(f) >= 1 and bas(f[0]) > 300, f"{[(bas(o), o['bitti'], o['deger'], o['beklenen']) for o in f]}")
        if s["F"]:
            e = bul("etiket_yok", s["F"])
            denetle(f"etiketi kaldırılan göz {s['F']}: etiket_yok", len(e) >= 1 and bas(e[0]) > 520,
                    f"{[(bas(o), o['bitti'], o['deger']) for o in e]}")
        beklenen = {("bos_raf", s["A"]), ("yanlis_urun", s["B"]), ("fiyat_farkli", s["D"]), ("etiket_yok", s["F"])}
        fazla = [(o["kural"], o["goz"]) for o in olaylar.values() if (o["kural"], o["goz"]) not in beklenen]
        denetle("düzenlenmeyen gözlerde raf olayı yok", not fazla, str(fazla))
        denetle("akış bitince bütün olaylar kapandı", all(o["bitti"] for o in olaylar.values()))
        denetle("raf olaylarının hepsi gorev: true", all(o["gorev"] is True for o in olaylar.values() if o["kural"] in
                                                         ("bos_raf", "az_stok", "yanlis_urun", "etiket_yok", "fiyat_farkli")))
        son = rafk[-1]["gozler"] if rafk else []
        RAPOR["raf"] = {"goz": len(h["gozler"]), "urun": len(h["urunler"]), "kare": s["kare"], "sure_sn": round(sure, 1),
                        "kayit": say, "olaylar": [(o["kural"], o["goz"], bas(o), o["bitti"], o["son_sure"], o["deger"], o["beklenen"])
                                                   for o in olaylar.values()],
                        "son_durumlar": {g["goz"]: (g["durum"], g["etiket"], g["fiyat"]) for g in son},
                        "senaryo": {k: v for k, v in s.items() if k != "asamalar"}}
    finally:
        z.temizle()


# =================================================================================================== gizlilik
def pikselli(fr: np.ndarray, b, ic: float = 0.5) -> float:
    """dene_motor_yuz.py ile aynı ölçü: kutunun iç kısmında yatay komşusuyla aynı piksel oranı (pikselli bölgede yüksek)."""
    H, W = fr.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in b[:4])
    w, h = x2 - x1, y2 - y1
    a1, b1 = int(max(0, x1 + (1 - ic) / 2 * w)), int(max(0, y1 + (1 - ic) / 2 * h))
    a2, b2 = int(min(W, x2 - (1 - ic) / 2 * w)), int(min(H, y2 - (1 - ic) / 2 * h))
    if a2 - a1 < 3 or b2 - b1 < 2:
        return 1.0
    p = fr[b1:b2, a1:a2].astype(np.int16)
    return float((np.abs(p[:, 1:] - p[:, :-1]).sum(2) == 0).mean())


def _renk_cesidi(fr: np.ndarray, b, ic: float = 0.5) -> float:
    """Kutunun iç kısmındaki farklı renk sayısı / piksel sayısı (pikselli bölgede çok düşük)."""
    H, W = fr.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in b[:4])
    w, h = x2 - x1, y2 - y1
    a1, b1 = int(max(0, x1 + (1 - ic) / 2 * w)), int(max(0, y1 + (1 - ic) / 2 * h))
    a2, b2 = int(min(W, x2 - (1 - ic) / 2 * w)), int(min(H, y2 - (1 - ic) / 2 * h))
    p = fr[b1:b2, a1:a2].reshape(-1, 3)
    return len(np.unique(p, axis=0)) / max(1, len(p))


def motoru_yukle(z: Zincir):
    """Motoru bloklardan önce raf_engine kopyasından yükler (blok kodu aynı imzayı görüp yeniden yüklemez)."""
    import importlib

    for ad in [m for m in sys.modules if m == "raf_motor" or m.startswith("raf_motor.")]:
        del sys.modules[ad]
    sys.path[:] = [p for p in sys.path if "raf_engine" not in p or p.startswith(str(z.motor))]
    if str(z.motor) not in sys.path:
        sys.path.append(str(z.motor))
    blok = importlib.import_module("raf_motor.blok")
    sys.modules["raf_motor"]._imza = (z.motor / "surum.txt").read_text(encoding="ascii")
    assert os.path.normcase(str(z.motor)) in os.path.normcase(blok.__file__)
    return blok


class Gizlilik:
    """Kayitci'ye giden her karede (olay karesi/klip/ön tampon/son_kare: Kayitci.kare; akış sonu: son_kare(zorla)) ve
    temiz_kare kopyasında, referans koşusunun (her kare analiz) o karedeki baş kutularının ortası pikselli mi."""

    def __init__(self, referans: dict):
        self.ref, self.kare, self.bas, self.kotu, self.en_kotu, self.temiz, self.son_t = referans, 0, 0, 0, 1.0, 0, None
        self.ornekler: list = []
        self.kalanlar: list = []
        self.ust_uste = 0

    def _bak(self, t, fr) -> None:
        for b in self.ref.get(round(float(t), 3), []):
            self.bas += 1
            o = pikselli(fr, b)
            if o < 0.6 and _renk_cesidi(fr, b) < 0.15:
                # üst üste binen iki pikselleştirme blok sınırlarını çoğaltır (yatay komşu ölçüsü düşer); bölgedeki farklı
                # renk sayısı yine de az ise pikselli sayılır (doğal yüzde neredeyse her piksel farklıdır)
                self.ust_uste += 1
                o = 0.6
            self.en_kotu = min(self.en_kotu, o)
            if o < 0.6:
                self.kotu += 1
                # yüz göstermeden incelemek için: "yatay komşusuyla aynı piksel" maskesi (beyaz = pikselli), kutu kırmızı
                H, W = fr.shape[:2]
                x1, y1, x2, y2 = (int(v) for v in b[:4])
                w, h = x2 - x1, y2 - y1
                a1, b1, a2, b2 = max(0, x1 - w), max(0, y1 - h), min(W, x2 + w), min(H, y2 + h)
                p = fr[b1:b2, a1:a2].astype(np.int16)
                m = np.zeros(p.shape[:2], np.uint8)
                m[:, 1:] = (np.abs(p[:, 1:] - p[:, :-1]).sum(2) == 0) * 255
                m = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)
                cv2.rectangle(m, (x1 - a1, y1 - b1), (x2 - a1, y2 - b1), (0, 0, 255), 1)
                self.kalanlar.append((round(float(t), 2), [round(v) for v in b[:4]], round(o, 2), m))

    def tak(self) -> None:
        K = sys.modules["raf_motor.kayit"].Kayitci
        asil_kare, asil_son = K.kare, K.son_kare
        d = self

        def kare(self_, t, cizili, sonuc, temiz=None):
            d.kare += 1
            d.son_t = t
            d._bak(t, cizili)
            if temiz is not None:
                d.temiz += 1
                d._bak(t, temiz)
                if len(d.ornekler) < 3 and d.ref.get(round(float(t), 3)) and d.kare % 20 == 0:
                    d.ornekler.append((t, temiz.copy()))
            return asil_kare(self_, t, cizili, sonuc, temiz)

        def son_kare(self_, cizili, zorla=False, temiz=None):
            if zorla and d.son_t is not None:
                d._bak(d.son_t, cizili)
                if temiz is not None:
                    d._bak(d.son_t, temiz)
            return asil_son(self_, cizili, zorla, temiz)

        K.kare, K.son_kare = kare, son_kare


def referans_kosusu(video: str, bolgeler, ozellikler, bitis: float | None = None) -> tuple[dict, dict]:
    """Her karede kişi analizi (kisi_fps 25): {t: baş kutuları}, {t: kişi listesi}."""
    z = Zincir("raf_bir_ref_")
    ref, kisiler = {}, {}
    try:
        z.kamera("ref", video, bolgeler, ozellikler, kisi_fps=25)
        for s in z.calistir("ref"):
            if s["v"]["Image"] is None:
                continue
            t = round(float(s["v"]["Zaman"]), 3)
            if bitis is not None and t > bitis:
                break
            k = json.loads(s["k"]["Kisiler"])
            ref[t] = [p["bas"] for p in k.get("kisiler", []) if p.get("durum") == "izleniyor" and p.get("bas")
                      and (p["bas"][3] - p["bas"][1]) >= 12]
            kisiler[t] = [p for p in k.get("kisiler", []) if p.get("durum") == "izleniyor"]
    finally:
        z.temizle()
    return ref, kisiler


def gizlilik_denetle(g: Gizlilik, ad: str) -> dict:
    denetle(f"{ad}: Kayitci'ye giden {g.kare} karede (ve {g.temiz} temiz_kare kopyasında) {g.bas} baş bölgesinin ortası pikselli",
            g.bas > 0 and g.kotu == 0, f"pikselsiz {g.kotu}, en düşük oran {g.en_kotu:.2f}, üst üste pikselli {g.ust_uste}")
    for i, (t, b, o, m) in enumerate(g.kalanlar[:4]):
        print(f"    pikselsiz: t={t} kutu={b} oran={o}")
        cv2.imwrite(str(CIKTI / f"gizlilik_maske_{ad.replace('.', '_')}_{i}.png"), cv2.resize(m, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    return {"kare": g.kare, "temiz": g.temiz, "bas": g.bas, "pikselsiz": g.kotu, "en_dusuk": round(g.en_kotu, 2),
            "ust_uste": g.ust_uste}


# =================================================================================================== müşteri
def b_musteri() -> None:
    bolum("b. müşteri senaryosu (gerçek zincir, kafe videoları, müşteri ajanının bölgeleri)")
    kl = video_klasoru()
    if kl is None:
        print("  atlandı: RAF_DENEME_VIDEOLARI yok")
        return
    from dene_musteri_video import DENEMELER

    rapor = {}
    for ad, d in DENEMELER.items():
        print(f"  -- {ad}", flush=True)
        ref, _ = referans_kosusu(str(kl / ad), d["bolgeler"], d["ozellikler"])
        z = Zincir("raf_bir_")
        try:
            kod = "m" + Path(ad).stem.replace("_", "")
            z.kamera(kod, str(kl / ad), d["bolgeler"], d["ozellikler"])
            motoru_yukle(z)
            g = Gizlilik(ref)
            g.tak()
            resim = None
            for s in z.calistir(kod):
                if resim is None and s["v"]["Image"] is not None and float(s["v"]["Zaman"]) >= 5 and json.loads(s["k"]["Kisiler"]).get("yeni"):
                    resim = damga(kucult(s["a"]["Image"], 800), f"{ad} t={float(s['v']['Zaman']):.1f}")
            kay = z.kayitlar()
            say = kayit_denetle(kay, ad)
            gz = gizlilik_denetle(g, ad)
            if resim is not None:
                cv2.imwrite(str(CIKTI / f"b_{kod}.jpg"), resim)
            for i, (t, im) in enumerate(g.ornekler[:1]):
                cv2.imwrite(str(CIKTI / f"b_{kod}_temiz.jpg"), kucult(im, 800))
            olc = [k for k in kay if k["tur"] == "olcum"]
            top: dict = {}
            for o in olc:
                for a, v in o["veri"].items():
                    top[a] = max(top.get(a, 0), v) if a.startswith(("kisi_ort", "kuyruk_")) else top.get(a, 0) + v
            etk = [(e["eylem"], e["bolge"], e.get("goz"), e["sure_sn"]) for e in kay if e["tur"] == "etkilesim"]
            ol = olay_ozeti(kay)
            if ad == "kasa.mp4":
                k = [o for o in ol.values() if o["kural"] == "kasa_kuyrugu"]
                denetle("kasa: kasa_kuyrugu olayı açıldı ve kapandı", k and k[0]["bitti"] and (k[0]["deger"] or 0) >= 4,
                        str([(o["deger"], o["beklenen"], o["bitti"]) for o in k]))
                denetle("kasa: kuyruk_ort / kuyruk_en_cok ölçüldü", "kuyruk_en_cok" in top, str({a: top.get(a) for a in ("kuyruk_ort", "kuyruk_en_cok")}))
            if ad == "teras.mp4":
                denetle("teras: uzandi ve durdu etkileşimleri", any(e[0] == "uzandi" for e in etk) and any(e[0] == "durdu" for e in etk), str(etk))
                denetle("teras: alan/birakan yazılmadı (raf doğrulaması yok)", "alan" not in top)
            if ad == "salon.mp4":
                denetle("salon: giren 2, cikan 2", top.get("giren") == 2 and top.get("cikan") == 2, str({a: top.get(a) for a in ("giren", "cikan")}))
            if ad == "gercek_kafe.mp4":
                denetle("gercek_kafe: dolap/koridor olayı yok", not ol, str([o["kural"] for o in ol.values()]))
            izg = [o for o in olc if o.get("izgara")]
            denetle(f"{ad}: ısı haritası katmanları yogunluk/durma", izg and set(izg[0]["izgara"]["katmanlar"]) >= {"yogunluk", "durma"})
            rapor[ad] = {"kayit": say, "olcum_toplam": {a: round(v, 1) for a, v in top.items()}, "etkilesim": etk,
                         "olaylar": [(o["kural"], o["deger"], o["bitti"]) for o in ol.values()], "gizlilik": gz}
            print("    ", json.dumps(rapor[ad], ensure_ascii=False)[:900])
        finally:
            z.temizle()
    RAPOR["musteri"] = rapor


# =================================================================================================== birlikte
def _yapistir_kisi(arka: np.ndarray, parca: np.ndarray, x: int, y: int) -> np.ndarray:
    out = arka.copy()
    H, W = out.shape[:2]
    h, w = parca.shape[:2]
    x1, y1, x2, y2 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x2 > x1 and y2 > y1:
        out[y1:y2, x1:x2] = parca[y1 - y:y2 - y, x1 - x:x2 - x]
    return out


def b_birlikte() -> None:
    bolum("c. birlikte (YAPAY: kafe videosundaki garson, raf fotoğrafının önüne yapıştırıldı)")
    kl = video_klasoru()
    if kl is None:
        print("  atlandı: RAF_DENEME_VIDEOLARI yok")
        return
    from dene_musteri_video import DENEMELER

    foto = "raf_44"
    teras = DENEMELER["teras.mp4"]
    # 1) garsonun kareleri ve bilek noktaları (teras, her kare analiz)
    _, kisiler = referans_kosusu(str(kl / "teras.mp4"), teras["bolgeler"], {}, bitis=9.6)
    cap = cv2.VideoCapture(str(kl / "teras.mp4"))
    Wt, Ht = int(cap.get(3)), int(cap.get(4))
    r1 = [0.71 * Wt, 0.6 * Ht, 0.86 * Wt, 0.8 * Ht]
    t0 = min(t for t in kisiler if t >= 1.0 and kisiler[t])
    gars = max((p for p in kisiler[t0]), key=lambda p: (min(p["b"][2], r1[2]) - max(p["b"][0], r1[0])) * (p["b"][3] - p["b"][1]))
    iz = gars["iz"]
    kareler, ofs = [], []
    zamanlar = sorted(kisiler)
    for t in zamanlar:
        p = next((q for q in kisiler[t] if q["iz"] == iz), None)
        if p is None:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * cap.get(5))))
        ok, fr = cap.read()
        if not ok:
            continue
        x1, y1, x2, y2 = p["b"]
        # kırpıntı = kişi kutusu (pay yok): kutu dışına yapışan zemin rafta "değişen göz" yaratmasın
        px_, py_ = 0.0, 0.0
        a, b, c, d = int(max(0, x1 - px_)), int(max(0, y1 - py_)), int(min(Wt, x2 + px_)), int(min(Ht, y2 + py_))
        kareler.append((t, fr[b:d, a:c].copy(), (a, b)))
        for j in (9, 10):
            if p.get("k") and p["k"][j][2] > 0.3 and r1[0] <= p["k"][j][0] <= r1[2] and r1[1] <= p["k"][j][1] <= r1[3]:
                ofs.append((p["k"][j][0] - a, p["k"][j][1] - b))
    cap.release()
    if not kareler or not ofs:
        denetle("garson kareleri ve bilek noktası bulundu", False, f"{len(kareler)} kare, {len(ofs)} bilek")
        return
    ox, oy = float(np.median([o[0] for o in ofs])), float(np.median([o[1] for o in ofs]))
    sabit_ofs = kareler[0][2]
    print(f"  garson izi {iz}: {len(kareler)} kare, bilek ofseti ({ox:.0f}, {oy:.0f}), {len(ofs)} bilek gözlemi")

    z = Zincir("raf_bir_")
    try:
        h = raf_hazirla(z, "birv", foto)
        im, W, H = h["im"], h["W"], h["H"]
        gz = h["gozler"]
        px = lambda k: [k[0] * W, k[1] * H, k[2] * W, k[3] * H]  # noqa: E731
        ch = max(p[1].shape[0] for p in kareler)
        cw = max(p[1].shape[1] for p in kareler)

        def sigar(g):  # yapıştırılan kişi kareden taşmasın
            k = px(g["kutu"])
            cx, cy = (k[0] + k[2]) / 2, (k[1] + k[3]) / 2
            return cy - oy >= 0 and cy - oy + ch <= H and cx - ox >= 0 and cx - ox + cw <= W

        aday = sorted([g for g in gz if sigar(g)] or gz,
                      key=lambda g: (-g["adet"], -(g["kutu"][2] - g["kutu"][0]) * (g["kutu"][3] - g["kutu"][1])))
        print("  göz adetleri (sığan):", [(g["kimlik"], g["adet"]) for g in aday])
        S1 = aday[0]
        S2 = next((g for g in aday[1:] if g["adet"] >= 2 and abs((g["kutu"][1] + g["kutu"][3]) - (S1["kutu"][1] + S1["kutu"][3])) > 0.1),
                  aday[1])
        bos = senaryo.FOTOLAR[foto]["bos"]

        def eksilt(base, g):
            n = 2 if g["adet"] >= 3 else 1
            return senaryo.bosalt(base, bos, px(g["kutu"]), oran_sol=max(0.0, 1 - n / max(g["adet"], 1)))

        E1 = eksilt(im, S1)
        E2 = eksilt(E1, S2)
        print(f"  hedef gözler {S1['kimlik']} (adet {S1['adet']}), {S2['kimlik']} (adet {S2['adet']})")

        def yer(g):  # bileği gözün ortasına getiren yapıştırma köşesi
            k = px(g["kutu"])
            return int((k[0] + k[2]) / 2 - ox), int((k[1] + k[3]) / 2 - oy)

        park = (int(0.05 * W), int(0.35 * H))
        fps = 8.0
        rng = np.random.default_rng(11)
        plan = []  # (t_video, arka, parça | None, (x, y))

        def uzanma(bas, g, arka):
            x, y = yer(g)
            for i, (tt, parca, (a, b)) in enumerate(kareler):
                plan.append((bas + tt - kareler[0][0], arka, parca, (x + a - sabit_ofs[0], y + b - sabit_ofs[1])))
            return bas + kareler[-1][0] - kareler[0][0]

        def yuru(bas, sure, arka, a_xy, b_xy):
            n = int(sure * fps)
            for i in range(n):
                f = (i + 1) / n
                plan.append((bas + i / fps, arka, kareler[-1][1], (int(a_xy[0] + f * (b_xy[0] - a_xy[0])),
                                                                    int(a_xy[1] + f * (b_xy[1] - a_xy[1])))))
            return bas + sure

        def bekle(bas, sure, arka, xy):
            for i in range(int(sure * fps)):
                plan.append((bas + i / fps, arka, kareler[-1][1] if xy else None, xy))
            return bas + sure

        def son_yer(g):
            x, y = yer(g)
            a, b = kareler[-1][2]
            return x + a - sabit_ofs[0], y + b - sabit_ofs[1]

        t = bekle(0.0, 15.0, im, None)
        t_u1 = t
        t = uzanma(t, S1, im)
        t = yuru(t, 2.0, E1, son_yer(S1), park)
        t = bekle(t, 10.0, E1, park)
        t = yuru(t, 2.0, E1, park, son_yer(S2))
        t_u2 = t
        t = uzanma(t, S2, E1)
        t = yuru(t, 2.0, E2, son_yer(S2), park)
        t = bekle(t, 14.0, E2, park)
        t = bekle(t, 12.0, E2, None)
        plan.sort(key=lambda p: p[0])
        # sabit kare hızına örnekle
        n = int(t * fps)
        vid = z.gecici / "birlikte.mp4"
        j = 0

        def uret():
            nonlocal j
            for i in range(n):
                tv = i / fps
                while j + 1 < len(plan) and plan[j + 1][0] <= tv:
                    j += 1
                _, arka, parca, xy = plan[j]
                fr = arka if parca is None else _yapistir_kisi(arka, parca, *xy)
                yield senaryo.gurultu(fr, rng)

        video_yaz(vid, uret(), fps, (W, H))
        print(f"  video {n} kare, {t:.0f} sn; uzanma 1 @ {t_u1:.0f} sn, uzanma 2 @ {t_u2:.0f} sn")
        cv2.imwrite(str(z.veri / "ayar" / "_referans_birv.jpg"), im)
        bolge = [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": h["poly"], "gozler": gz}]
        oz = {"toplu_alma": {"acik": True, "uzanma_sayi": 2, "pencere_sn": 60}}
        ref, _ = referans_kosusu(str(vid), bolge, oz)
        z.kamera("birv", str(vid), bolge, oz, raf_araligi_sn=10, referans={"zaman": "2026-11-15T09:59:00"})
        import shutil  # bellek bölümü için: video, ayar, katalog ve referans çıktı klasörüne (depoya değil)

        shutil.copyfile(vid, CIKTI / "birlikte_video.mp4")
        shutil.copyfile(z.veri / "ayar" / "_referans_birv.jpg", CIKTI / "birlikte_referans.jpg")
        shutil.rmtree(CIKTI / "birlikte_urunler", ignore_errors=True)
        shutil.copytree(z.veri / "urunler", CIKTI / "birlikte_urunler")
        (CIKTI / "birlikte_ayar.json").write_text(json.dumps({"bolgeler": bolge, "ozellikler": oz}, ensure_ascii=False), encoding="utf-8")
        motoru_yukle(z)
        g = Gizlilik(ref)
        g.tak()
        kutu = {x["kimlik"]: x["kutu"] for x in gz}
        resimler, anlar, kapali, kontroller = [], {t_u1 + 4: "uzanma 1", t_u2 + 4: "uzanma 2", t - 5: "son"}, 0, []
        st = ({}, {}, {}, {})
        while True:
            r = adim(z, "birv#k1", st)
            if r["v"]["Image"] is None:
                if r["v"]["Bitti"] or str(r["v"]["Durum"]).startswith(("hata", "bitti")):
                    break
                continue
            tt = float(r["v"]["Zaman"])
            try:
                rj = json.loads(r["u"]["Raf"])
                kapali += any(x["durum"] == "kapali" for x in rj.get("gozler") or [])
                if rj.get("sira") != getattr(b_birlikte, "_sira", None):
                    b_birlikte._sira = rj.get("sira")
                    kontroller.append((round(tt, 1), {x["goz"]: (x["durum"][:3], x["adet"]) for x in rj.get("gozler") or []}))
            except Exception:
                pass
            for a in [a for a in anlar if tt >= a]:
                resimler.append(damga(kucult(gozleri_ciz(r["a"]["Image"], r["u"]["Raf"], kutu), 800), f"t={tt:.0f} {anlar.pop(a)}"))
        if resimler:
            cv2.imwrite(str(CIKTI / "c_birlikte_kareler.jpg"), np.vstack(resimler))
        kay = z.kayitlar()
        say = kayit_denetle(kay, "birlikte")
        gzr = gizlilik_denetle(g, "birlikte")
        etk = [(e["eylem"], e["goz"], e["sure_sn"], e["zaman"][14:]) for e in kay if e["tur"] == "etkilesim"]
        print("   etkileşimler", etk)
        ol = olay_ozeti(kay)
        print("   olaylar", [(o["kural"], o.get("goz"), o["deger"], o["bitti"], o["aciklama"]) for o in ol.values()])
        rafk = [k for k in kay if k["tur"] == "raf"]
        izle = {S1["kimlik"], S2["kimlik"]} | {e[1] for e in etk if e[1]}
        for gid in sorted(izle):
            print("   kontroller", gid, [(tk, d.get(gid)) for tk, d in kontroller])
        kap_kayit =sum(1 for k in rafk for x in k["gozler"] if x["durum"] == "kapali")
        olc = [k for k in kay if k["tur"] == "olcum"]
        alan = sum(o["veri"].get("alan", 0) for o in olc)
        balan = sum(o["veri"].get("b:b1:alan", 0) for o in olc)
        denetle("kişi rafın önündeyken göz 'kapali' (raf JSON'u ve raf kaydı)", kapali > 0 and kap_kayit > 0,
                f"{kapali} karede, {kap_kayit} kayıt gözünde")
        uz = [e for e in etk if e[0] == "uzandi"]
        al = [e for e in etk if e[0] == "aldi"]
        denetle("iki uzanma etkileşimi", len(uz) >= 2, str(uz))
        denetle(f"uzanma -> göz yüz sayısı düştü -> 'aldi' ({S1['kimlik']}, {S2['kimlik']})",
                {e[1] for e in al} >= {S1["kimlik"], S2["kimlik"]}, str(al))
        denetle("ölçümde alan ve b:b1:alan sayıldı", alan >= 2 and balan >= 2, f"alan {alan}, b:b1:alan {balan}")
        tp = [o for o in ol.values() if o["kural"] == "toplu_alma"]
        denetle("toplu_alma göz sayımıyla açıldı (2 uzanmada alınan ürün >= 2)", tp and "ürün aldı" in (tp[0]["aciklama"] or ""),
                str([(o["deger"], o["aciklama"], o["bitti"]) for o in tp]))
        RAPOR["birlikte"] = {"kayit": say, "etkilesim": etk, "olaylar": [(o["kural"], o.get("goz"), o["deger"], o["bitti"])
                                                                        for o in ol.values()],
                             "kapali_kare": kapali, "alan": alan, "gizlilik": gzr, "hedef": [S1["kimlik"], S2["kimlik"]]}
    finally:
        z.temizle()


# =================================================================================================== hata yolları
def _sabit_video(z: Zincir, im: np.ndarray, sure: float, fps: float = 2.0) -> Path:
    yol = z.gecici / f"sabit_{int(sure)}.mp4"
    rng = np.random.default_rng(3)
    video_yaz(yol, (senaryo.gurultu(im, rng) for _ in range(int(sure * fps))), fps, (im.shape[1], im.shape[0]))
    return yol


def _kos(z: Zincir, kod: str) -> dict:
    """Zinciri sonuna kadar çalıştırır; çöken olursa yakalanır. Dönüş: son çıkışlar ve durum özetleri."""
    st = ({}, {}, {}, {})
    out = {"cokme": None, "kisi_hata": 0, "urun_hata": 0, "analiz_goruntu": 0, "urun_durum": set(), "analiz_durum": set(), "n": 0}
    try:
        while True:
            r = adim(z, f"{kod}#k1", st)
            if r["v"]["Image"] is None:
                if r["v"]["Bitti"] or str(r["v"]["Durum"]).startswith(("hata", "bitti")):
                    break
                continue
            out["n"] += 1
            out["kisi_hata"] += "hata" in json.loads(r["k"]["Kisiler"])
            out["urun_hata"] += "hata" in json.loads(r["u"]["Raf"])
            out["analiz_goruntu"] += r["a"]["Image"] is not None and bool(r["a"]["Image"].any())
            out["urun_durum"].add(str(r["u"]["Durum"])[:70])
            out["analiz_durum"].add(str(r["a"]["Durum"]).split("·")[-1].strip()[:70])
    except Exception as e:  # blok kodu hatayı yakalar; buraya düşmemeli
        out["cokme"] = f"{type(e).__name__}: {e}"
    return out


def b_hata() -> None:
    bolum("e. hata yolları (çökme yok, sahte 'bir şey yok' yok, hata değeri kuralı)")
    im = cv2.imread(str(GORSELLER / f"{RAF_FOTO}.jpg"))
    # 1) eksik raf modeli
    z = Zincir("raf_bir_")
    try:
        h = raf_hazirla(z, "h1")
        bolge = [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": h["poly"], "gozler": h["gozler"]}]
        (z.motor / "modeller" / "urun.onnx").unlink()
        rm = motor(z, "raf_modeller")
        rm._PAYLASILAN.clear()  # hazırlıkta açılmış oturumlar unutulsun (yeni Studio süreci gibi)
        z.kamera("h1", str(_sabit_video(z, im, 30)), bolge)
        r = _kos(z, "h1")
        kay = z.kayitlar()
        rafk = [k for k in kay if k["tur"] == "raf"]
        denetle("urun.onnx yokken zincir çökmez, Raf Ürün hata değeri verir, kişi analizi sürer",
                r["cokme"] is None and r["urun_hata"] > 0 and r["kisi_hata"] == 0 and r["analiz_goruntu"] > 0,
                f"{r['n']} kare, ürün hata {r['urun_hata']}, {sorted(r['urun_durum'])[:2]}, {sorted(r['analiz_durum'])[:2]}")
        nb = [k for k in kay if k["tur"] == "nabiz"]
        denetle("urun.onnx yokken nabız kaydı raf_hata taşır, 'hata' kaydı yazılmaz (iş durmaz)",
                nb and all("urun.onnx" in (k.get("raf_hata") or "") for k in nb) and not any(k["tur"] == "hata" for k in kay),
                str(nb[:1]))
        denetle("urun.onnx yokken sahte boş göz yok (raf kaydı/olay 'bos' içermez)",
                not any(g["durum"] in ("bos", "az") for k in rafk for g in k["gozler"])
                and not any(k["tur"] == "olay" and k["kural"] in ("bos_raf", "az_stok") for k in kay), f"{len(rafk)} raf kaydı")
        RAPOR.setdefault("hata", {})["urun_model_yok"] = {k: (sorted(v) if isinstance(v, set) else v) for k, v in r.items()}
    finally:
        z.temizle()
    # 2) eksik kişi modeli
    z = Zincir("raf_bir_")
    try:
        (z.motor / "modeller" / "kisi.onnx").unlink()
        z.kamera("h2", str(_sabit_video(z, im, 10)), [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": senaryo.FOTOLAR[RAF_FOTO]["poly"]}])
        motoru_yukle(z)
        g = Gizlilik({})
        g.tak()
        r = _kos(z, "h2")
        kay = z.kayitlar()
        denetle("kisi.onnx yokken: Kişiler hata, Analiz siyah kare, Kayitci'ye kare yok, 'hata' kaydı var, ölçüm yok",
                r["cokme"] is None and r["kisi_hata"] == r["n"] and r["analiz_goruntu"] == 0 and g.kare == 0
                and any(k["tur"] == "hata" for k in kay) and not any(k["tur"] == "olcum" for k in kay),
                f"{r['n']} kare, hata kaydı {sum(k['tur'] == 'hata' for k in kay)}, Kayitci karesi {g.kare}")
    finally:
        z.temizle()
    # 3) bozuk katalog görseli
    z = Zincir("raf_bir_")
    try:
        h = raf_hazirla(z, "h3")
        ilk = z.veri / "urunler" / "gorsel" / h["urunler"][0]["gorseller"][0]
        ilk.write_bytes(b"bozuk jpeg degil")
        (z.veri / "urunler" / "gomme-onbellek.npz").unlink(missing_ok=True)
        motor(z, "raf_modeller")._PAYLASILAN.clear()
        bolge = [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": h["poly"], "gozler": h["gozler"]}]
        z.kamera("h3", str(_sabit_video(z, im, 30)), bolge, {"yanlis_urun": {"acik": True}})
        cv2.imwrite(str(z.veri / "ayar" / "_referans_h3.jpg"), im)
        r = _kos(z, "h3")
        kay = z.kayitlar()
        rafk = [k for k in kay if k["tur"] == "raf"]
        denetle("bozuk katalog görseliyle raf analizi sürer, yanlış uyarı yok",
                r["cokme"] is None and r["urun_hata"] == 0 and rafk and not any(k["tur"] == "olay" for k in kay),
                f"{len(rafk)} raf kaydı, {sorted(r['urun_durum'])[:2]}")
    finally:
        z.temizle()
    # 4) bölgesiz kamera, 5) gözsüz raf bölgesi
    for ad, bolgeler in (("bölgesiz", []), ("gözsüz raf", [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": senaryo.FOTOLAR[RAF_FOTO]["poly"]}])):
        z = Zincir("raf_bir_")
        try:
            z.kamera("h4", str(_sabit_video(z, im, 40)), bolgeler)
            r = _kos(z, "h4")
            kay = z.kayitlar()
            denetle(f"{ad} kamera: çökme yok, Raf 'göz tanımlı değil' (boş liste doğru), ölçüm ve bitti yazıldı",
                    r["cokme"] is None and r["urun_hata"] == 0 and any("göz tanımlı değil" in d for d in r["urun_durum"])
                    and any(k["tur"] == "olcum" for k in kay) and any(k["tur"] == "bitti" for k in kay)
                    and not any(k["tur"] in ("olay", "raf") for k in kay),
                    f"{sorted(r['urun_durum'])[:2]}")
        finally:
            z.temizle()
    # 6) akış ortasında çözünürlük değişimi (bloklara kare doğrudan verilir)
    z = Zincir("raf_bir_")
    try:
        h = raf_hazirla(z, "h5")
        bolge = [{"kimlik": "b1", "ad": "Raf", "tur": "raf", "poly": h["poly"], "gozler": h["gozler"]}]
        z.kamera("h5", "yok.mp4", bolge)
        cv2.imwrite(str(z.veri / "ayar" / "_referans_h5.jpg"), im)
        st = ({}, {}, {}, {})
        rng = np.random.default_rng(5)
        kucuk = cv2.resize(im, (960, 540))
        sonuc, cokme = [], None
        try:
            for i in range(80):
                fr = senaryo.gurultu(im if i < 40 else kucuk, rng)
                t = i * 0.5
                k = z._cagir(z.K, st[1], Image=fr, Kamera="h5#k1", Zaman=t)
                u = z._cagir(z.U, st[2], Image=fr, Kamera="h5#k1", Zaman=t)
                a = z._cagir(z.A, st[3], Image=fr, Kisiler=k["Kisiler"], Raf=u["Raf"], Kamera="h5#k1", Zaman=t, Bitti=False)
                sonuc.append((fr.shape[1], "hata" in json.loads(k["Kisiler"]), "hata" in json.loads(u["Raf"]),
                              a["Image"] is not None and a["Image"].shape[:2] == fr.shape[:2], u["Durum"][:60]))
            z._cagir(z.A, st[3], Image=None, Kisiler="[]", Raf="[]", Kamera="h5#k1", Zaman=40.0, Bitti=True)
        except Exception as e:
            cokme = f"{type(e).__name__}: {e}"
        kay = z.kayitlar()
        sonra = [s for s in sonuc if s[0] == 960]
        rafk = [k for k in kay if k["tur"] == "raf"]
        denetle("çözünürlük 1280->960 değişince çökme yok, Analiz yeni boyutta görüntü verir",
                cokme is None and sonra and all(s[3] for s in sonra), f"{cokme}, sonra {len(sonra)} kare")
        denetle("çözünürlük değişiminden sonra sahte boş/az göz yok",
                not any(g["durum"] in ("bos", "az") for k in rafk for g in k["gozler"])
                and not any(k["tur"] == "olay" and k["kural"] in ("bos_raf", "az_stok") for k in kay),
                f"Raf durumları: {sorted({s[4] for s in sonra})[:3]}, ürün hata {sum(s[2] for s in sonra)}")
    finally:
        z.temizle()


# =================================================================================================== hız
def _bellek_mb() -> float:
    """Sürecin çalışma kümesi (Windows, ctypes)."""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

    p = PMC()
    p.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    psapi = ctypes.WinDLL("psapi")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb)
    _bellek_mb.ws = round(p.WorkingSetSize / 2 ** 20, 1)  # çalışma kümesi (fiziksel); özel kullanım (commit) döner
    return round(p.PrivateUsage / 2 ** 20, 1)


def _cekirdek_sinirla(n: int) -> None:
    """Süreci ilk n çekirdekle sınırlar (4/2 çekirdekli PC benzetimi: onnxruntime + OpenCV + Python birlikte)."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    k32.SetProcessAffinityMask(k32.GetCurrentProcess(), (1 << n) - 1)
    cv2.setNumThreads(n)


def _hiz_karesi(kisi_n: int, bolge_n: int, rng) -> tuple:
    """raf_43 fotoğrafı (1280x720) + teras.mp4'ten kırpılmış oturan kişi, rafın önünde gezinen kişi_n kopya."""
    im = cv2.imread(str(GORSELLER / "raf_43.jpg"))
    cap = cv2.VideoCapture(str(video_klasoru() / "teras.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 24)
    ok, fr = cap.read()
    cap.release()
    kisi = cv2.resize(cv2.resize(fr, (1280, 720))[190:340, 230:330], (160, 240))
    poly = senaryo.FOTOLAR["raf_43"]["poly"]
    x0, y0, x1, y1 = poly[0][0], poly[0][1], poly[2][0], poly[2][1]
    bolgeler = []
    for b in range(bolge_n):
        bx0 = x0 + (x1 - x0) * b / bolge_n
        bx1 = x0 + (x1 - x0) * (b + 1) / bolge_n
        gozler = []
        for r in range(4):
            for c in range(5):
                gozler.append({"kimlik": f"g{b}_{r}_{c}", "urun": None, "adet": 1, "etiket": None, "fiyat": None,
                               "kutu": [round(bx0 + (bx1 - bx0) * c / 5, 4), round(y0 + (y1 - y0) * r / 4, 4),
                                        round(bx0 + (bx1 - bx0) * (c + 1) / 5, 4), round(y0 + (y1 - y0) * (r + 1) / 4, 4)]})
        bolgeler.append({"kimlik": f"b{b + 1}", "ad": f"Raf {b + 1}", "tur": "raf",
                         "poly": [[bx0, y0], [bx1, y0], [bx1, y1], [bx0, y1]], "gozler": gozler})

    def kare(i):
        k = im.copy()
        for j in range(kisi_n):
            x = int((40 + (j % 5) * 240 + i * 12) % 1180)
            y = 380 if kisi_n <= 5 else 80 + (j // 5) * 330
            w = min(160, 1280 - x)
            k[y:y + 240, x:x + w] = kisi[:, :w]
        return senaryo.gurultu(k, rng)

    return im, bolgeler, kare


def hiz_tek(kisi_n: int, bolge_n: int, cekirdek: int, kademe: str = "") -> dict:
    """Bir ölçüm (alt süreçte): çekirdek sınırı + RAF_IS_PARCACIGI; her kare analiz (kisi_fps 25), video 3 kare/sn, 60 sn.
    kademe: "" (olağan) ya da ayar adları (ör. "raf_araligi_sn=20")."""
    if cekirdek:
        _cekirdek_sinirla(cekirdek)
        os.environ["RAF_IS_PARCACIGI"] = str(cekirdek)
    rng = np.random.default_rng(1)
    z = Zincir("raf_hiz_")
    try:
        im, bolgeler, kare = _hiz_karesi(kisi_n, bolge_n, rng)
        yol = z.gecici / "hiz.mp4"
        video_yaz(yol, (kare(i) for i in range(180)), 3.0, (1280, 720))
        cv2.imwrite(str(z.veri / "ayar" / "_referans_hiz.jpg"), im)
        ek = {"kisi_fps": 25, "raf_araligi_sn": 10}
        for a in filter(None, kademe.split(",")):
            k, v = a.split("=")
            ek[k] = float(v)
        z.kamera("hiz", str(yol), bolgeler, {"ilgi": {"acik": True}, "uzanma": {"acik": True}}, **ek)
        sureler, urun_ms, kisi_say = [], [], []
        st = ({}, {}, {}, {})
        bas = son = time.perf_counter()
        while True:
            r = adim(z, "hiz#k1", st)
            if r["v"]["Image"] is None:
                if r["v"]["Bitti"] or str(r["v"]["Durum"]).startswith(("hata", "bitti")):
                    break
                continue
            simdi = time.perf_counter()
            sureler.append(simdi - son)
            son = simdi
            d = r["u"]["Durum"]
            if "kontrol" in d:
                urun_ms.append(float(d.split("kontrol")[1].split("ms")[0]))
            try:
                kisi_say.append(int(r["k"]["Durum"].split(" ")[1]))
            except (IndexError, ValueError):
                pass
        s = np.array(sureler)
        kararli = s[10:]
        return {"kisi": kisi_n, "bolge": bolge_n, "goz": 20 * bolge_n, "cekirdek": cekirdek or "hepsi", "kademe": kademe,
                "gorulen_kisi": int(np.median(kisi_say[10:])) if kisi_say else 0,
                "ilk_kare_sn": round(float(s[0]), 2), "ilk10_kare_sn": round(float(s[:10].sum()), 2),
                "kararli_ort_kare_sn": round(len(kararli) / float(kararli.sum()), 2),
                "kararli_medyan_ms": round(1000 * float(np.median(kararli)), 1),
                "kararli_p95_ms": round(1000 * float(np.percentile(kararli, 95)), 1),
                "en_uzun_ms": round(1000 * float(kararli.max()), 1),
                "raf_kontrol_ms": [round(x) for x in urun_ms[:3]] + (["...", round(float(np.median(urun_ms[3:])))] if len(urun_ms) > 3 else []),
                "toplam_sn": round(time.perf_counter() - bas, 1)}
    finally:
        z.temizle()


def b_hiz() -> None:
    bolum("5. birleşik yük (çekirdek sınırı ile, alt süreçlerde)")
    import subprocess

    if video_klasoru() is None:
        print("  atlandı: RAF_DENEME_VIDEOLARI yok")
        return
    kademeler = [k for k in os.environ.get("RAF_HIZ_KADEME", "").split(";") if k] or [""]
    satirlar = []
    for kademe in kademeler:
        for cek in (4, 2):
            for kisi_n, bolge_n in ((5, 1), (10, 3)):
                p = subprocess.run([sys.executable, __file__, "hiz_tek", str(kisi_n), str(bolge_n), str(cek), kademe],
                                   capture_output=True, text=True, encoding="utf-8", env=os.environ)
                sat = [s for s in p.stdout.splitlines() if s.startswith("{")]
                if not sat:
                    print(p.stdout[-2000:], p.stderr[-2000:])
                    denetle(f"hız ölçümü {kisi_n} kişi/{bolge_n} bölge/{cek} çekirdek", False)
                    continue
                r = json.loads(sat[-1])
                satirlar.append(r)
                print("  ", json.dumps(r, ensure_ascii=False), flush=True)
    RAPOR["hiz"] = satirlar
    ilk = [r for r in satirlar if r["cekirdek"] == 4 and r["kisi"] == 5]
    if ilk:
        denetle("4 çekirdek, 5 kişi + 1 bölge/20 göz: kararlı durumda >= 3 analiz/sn", ilk[-1]["kararli_ort_kare_sn"] >= 3.0,
                f"{ilk[-1]['kararli_ort_kare_sn']} kare/sn")


# =================================================================================================== bellek
def b_bellek() -> None:
    bolum("6. bellek ve dosya birikimi (en az 15 dk video zamanı, döngülü birleşik video)")
    kaynak = CIKTI / "birlikte_video.mp4"
    ayar_k = CIKTI / "birlikte_ayar.json"
    if not kaynak.is_file() or not ayar_k.is_file():
        print("  atlandı: önce 'birlikte' bölümü çalışmalı (video ve ayar çıktıya kopyalanır)")
        return
    z = Zincir("raf_bel_")
    try:
        a = json.loads(ayar_k.read_text(encoding="utf-8"))
        cap = cv2.VideoCapture(str(kaynak))
        fps, n, boyut = cap.get(5), int(cap.get(7)), (int(cap.get(3)), int(cap.get(4)))
        cap.release()
        tur = int(np.ceil(15.5 * 60 * fps / max(1, n)))

        def dongu():  # kareler bellekte tutulmaz (ölçümü bozmasın)
            for _ in range(tur):
                c = cv2.VideoCapture(str(kaynak))
                while True:
                    ok, fr = c.read()
                    if not ok:
                        break
                    yield fr
                c.release()

        yol = z.gecici / "dongu.mp4"
        sayi = video_yaz(yol, dongu(), fps, boyut)
        toplam_sn = sayi / fps
        for d in ("urunler",):
            import shutil

            shutil.copytree(CIKTI / "birlikte_urunler", z.veri / d)
        cv2.imwrite(str(z.veri / "ayar" / "_referans_bel.jpg"), cv2.imread(str(CIKTI / "birlikte_referans.jpg")))
        z.kamera("bel", str(yol), a["bolgeler"], a["ozellikler"], raf_araligi_sn=10)
        motor_dosya = sum(1 for _ in z.motor.rglob("*"))
        st = ({}, {}, {}, {})
        olcumler, bas = [], time.perf_counter()
        sonraki = 0.0
        while True:
            r = adim(z, "bel#k1", st)
            if r["v"]["Image"] is None:
                if r["v"]["Bitti"] or str(r["v"]["Durum"]).startswith(("hata", "bitti")):
                    break
                continue
            tt = float(r["v"]["Zaman"])
            if tt >= sonraki:
                gc.collect()
                kuyruk = list((z.veri / "kuyruk").glob("*"))
                cikti = list((z.veri / "cikti" / "bel").glob("*"))
                olcumler.append({"t_video": round(tt), "bellek_mb": _bellek_mb(), "calisma_mb": _bellek_mb.ws, "kuyruk": len(kuyruk),
                                 "kuyruk_tmp": sum(1 for p in kuyruk if p.suffix == ".tmp"),
                                 "cikti": len(cikti), "cikti_mb": round(sum(p.stat().st_size for p in cikti) / 2 ** 20, 1),
                                 "acik_klip": len(st[3]["durum"]["kayitci"].yazicilar)
                                 if (st[3].get("durum") or {}).get("kayitci") else 0,
                                 "duvar_sn": round(time.perf_counter() - bas)})
                print("  ", olcumler[-1], flush=True)
                sonraki += 60.0
        kay = z.kayitlar()
        cikti = list((z.veri / "cikti" / "bel").glob("*"))
        tmp = [p.name for p in (z.veri / "kuyruk").glob("*.tmp")] + [p.name for p in cikti if p.suffix == ".tmp"]
        ilk, orta, son = olcumler[1], olcumler[len(olcumler) // 2], olcumler[-1]
        denetle(f"{toplam_sn / 60:.1f} dk video koşuldu", toplam_sn >= 15 * 60)
        denetle("bellek ilk dakikadan sonra 100 MB'tan fazla büyümedi", son["bellek_mb"] - ilk["bellek_mb"] <= 100,
                f"{ilk['bellek_mb']} -> {orta['bellek_mb']} -> {son['bellek_mb']} MB")
        denetle("geride .tmp kalmadı, motor klasörüne dosya eklenmedi",
                not tmp and sum(1 for _ in z.motor.rglob("*") if "__pycache__" not in str(_)) <= motor_dosya, str(tmp[:3]))
        RAPOR["bellek"] = {"video_dk": round(toplam_sn / 60, 1), "olcumler": olcumler,
                           "kayit_turleri": {t: sum(1 for k in kay if k["tur"] == t) for t in {k["tur"] for k in kay}},
                           "cikti_dosya": len(cikti), "klip": sum(1 for p in cikti if p.name.endswith(".ham.mp4"))}
    finally:
        z.temizle()


BOLUMLER = {"katalog": b_katalog, "gorev": b_gorev, "raf": b_raf, "musteri": b_musteri, "birlikte": b_birlikte,
            "hata": b_hata, "hiz": b_hiz, "bellek": b_bellek}


def main() -> int:
    if sys.argv[1:2] == ["hiz_tek"]:  # b_hiz'in alt süreci
        a = sys.argv[2:] + [""] * 4
        print(json.dumps(hiz_tek(int(a[0]), int(a[1]), int(a[2]), a[3]), ensure_ascii=False), flush=True)
        return 0
    secilen = sys.argv[1:] or ["katalog", "gorev", "raf", "musteri", "birlikte", "hata"]
    print("Python", sys.version.split()[0], sys.executable)
    print("numpy", np.__version__, "OpenCV", cv2.__version__)
    for ad in secilen:
        BOLUMLER[ad]()
    kalan = [(b, a) for b, a, ok in SONUC if not ok]
    RAPOR["python"] = [sys.version.split()[0], np.__version__, cv2.__version__, onnx_bilgisi()]
    RAPOR["denetim"] = {"gecen": len(SONUC) - len(kalan), "toplam": len(SONUC), "kalan": kalan}
    ad = "rapor_" + "_".join(secilen) + ".json"
    (CIKTI / ad).write_text(json.dumps(RAPOR, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n{len(SONUC) - len(kalan)}/{len(SONUC)} denetim geçti" + (f" · kalanlar: {kalan}" if kalan else ""))
    print("çıktı:", CIKTI)
    return 1 if kalan else 0


if __name__ == "__main__":
    sys.exit(main())
