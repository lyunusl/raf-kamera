"""Özellik kataloğu: panelde ve AugeLab Studio'daki motorda aynıdır (motor/panel sözleşmesi, bölüm 1).

Her kayıt (KURALLAR):
  kod, ad, kategori (KATEGORILER), aciklama
  durum        "hazir" | "sinirli" | "deneysel": özelliğin sınanmış durumu. sinama.SINAMA'dan gelir (sınama yapılmamışsa
               "deneysel"); panelde rozet olarak görünür.
  varsayilan   kamera ayarında `ozellikler` içinde yoksa açık mı
  olay         uyarı (olay kaydı) üretir mi        gorev   personel görevi açar mı
  bolge_turleri  çalışması için gereken bölge türleri (biri yeterli); boş liste: bölge gerekmez
  ayarlar      {ad: {"ad": Türkçe etiket, "varsayilan": sayı, "birim": "sn" | "kişi" | "derece" | "oran" | "" ,
                     "en_az": sayı, "en_cok": sayı, "adim": sayı}}   (panel ayar formunu bundan çizer)
  modeller     çalışması için gereken model dosyalarının düz adları (MODEL_DOSYALARI içinden)
  duzey, onem, taban   olay üreten özelliklerde risk puanı için (onem × olasılık; olasılık tabandan başlar, sürdükçe artar)

Kamera ayarında: "ozellikler": {"kasa_kuyrugu": {"acik": true, "sure_sn": 45}, ...}. `ozellik_ayari()` birleştirir.
"""
from __future__ import annotations

import os
import time

from . import community_model

KATEGORILER = {
    "raf": "Raf",
    "musteri": "Müşteri",
    "operasyon": "Operasyon",
    "birlikte": "Birlikte",
}

# bölge türleri (kamera ayarında çizilir)
BOLGE_TURLERI = {
    "raf": "Raf",
    "koridor": "Koridor",
    "kasa": "Kasa",
    "dolap": "Soğutucu dolap",
    "giris": "Giriş",
}

# özelliklerin sınanmış durumu (panelde rozet olarak görünür)
DURUMLAR = {
    "hazir": "Hazır",
    "sinirli": "Sınırlı",
    "deneysel": "Deneysel",
}

HASSASIYET_ADLARI = {"dusuk": "Düşük (az yanlış uyarı)", "orta": "Orta", "yuksek": "Yüksek (erken uyarı)"}
VARSAYILAN_HASSASIYET = "orta"

KISI, ISKELET, OZELLIK = "kisi.onnx", "iskelet.onnx", "ozellik.onnx"
# Raf/ürün modelleri: adların asıl yeri raf_modeller.py (URUN, GOMME, ETIKET_BUL, ETIKET_OKU). Burada düz metin olarak
# yinelenir: katalog panelde de yüklenir ve raf_modeller'i içe aktarmak panele OpenCV yükletirdi. Eşitliği
# egitim/dene_motor_birlesik.py denetler. Okuyucunun karakter listesi (raf_modeller.ETIKET_HARF, etiket-oku.txt) model
# değildir: şifrelenmez, MODEL_DOSYALARI'na girmez, modeller klasöründe düz dosya olarak durur.
URUN, GOMME, ETIKET_BUL, ETIKET_OKU = "urun.onnx", "gomme.onnx", "etiket-bul.onnx", "etiket-oku.onnx"
# Model dosyalarının düz adları. Korumalı pakette her birinin yanında <ad>.isgm girdisi bulunur.
# İndirme bilgisi (boyut, SHA-256, Drive kimliği) panel tarafında studio_kurulum.MODELLER tablosundadır.
MODEL_DOSYALARI: list[str] = [KISI, ISKELET, OZELLIK, URUN, GOMME, ETIKET_BUL, ETIKET_OKU]
MODEL_KLASORU = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modeller")


def _a(ad, varsayilan, birim="", en_az=0, en_cok=None, adim=None) -> dict:
    return {"ad": ad, "varsayilan": varsayilan, "birim": birim, "en_az": en_az, "en_cok": en_cok,
            "adim": adim if adim is not None else (1 if isinstance(varsayilan, int) else 0.05)}


def _sure(v, en_az=1, en_cok=3600, ad="Kaç saniye sürünce uyarı verilsin"):
    # en az 1 sn: kısa örnek videolarda (10 sn) uyarının görülebilmesi için; mağazada varsayılanlar kullanılır
    return _a(ad, v, "sn", en_az, en_cok, 1)


KURALLAR: list[dict] = [
    # ------------------------------------------------------------------ raf (raf/ürün tarafı yazar; burada yalnızca tanım)
    {"kod": "bos_raf", "ad": "Boş raf", "kategori": "raf", "olay": True, "gorev": True, "varsayilan": True,
     "bolge_turleri": ["raf"], "duzey": "yuksek", "onem": 3, "taban": 3, "modeller": [URUN, GOMME],
     "aciklama": "Bir göz boş kaldı.", "ayarlar": {"sure_sn": _sure(20)}},
    {"kod": "az_stok", "ad": "Azalan stok", "kategori": "raf", "olay": True, "gorev": True, "varsayilan": True,
     "bolge_turleri": ["raf"], "duzey": "orta", "onem": 2, "taban": 3, "modeller": [URUN, GOMME],
     "aciklama": "Gözdeki ürün beklenenin altına düştü.",
     "ayarlar": {"doluluk_esik": _a("Doluluk bunun altına düşünce", 0.55, "oran", 0.1, 0.9, 0.05), "sure_sn": _sure(60)}},
    {"kod": "yanlis_urun", "ad": "Yanlış ürün (planogram)", "kategori": "raf", "olay": True, "gorev": True, "varsayilan": False,
     "bolge_turleri": ["raf"], "duzey": "orta", "onem": 2, "taban": 3, "modeller": [URUN, GOMME],
     "aciklama": "Gözde planogramdaki üründen farklı bir ürün görülüyor.",
     "ayarlar": {"benzerlik_esik": _a("Beklenen ürüne benzerlik en az", 0.45, "oran", 0.2, 0.95, 0.05), "sure_sn": _sure(60)}},
    {"kod": "etiket_yok", "ad": "Fiyat etiketi yok", "kategori": "raf", "olay": True, "gorev": True, "varsayilan": False,
     "bolge_turleri": ["raf"], "duzey": "dusuk", "onem": 2, "taban": 2, "modeller": [ETIKET_BUL, ETIKET_OKU],
     "aciklama": "Gözün fiyat etiketi görünmüyor.", "ayarlar": {"sure_sn": _sure(300, 30)}},
    {"kod": "fiyat_farkli", "ad": "Fiyat farklı", "kategori": "raf", "olay": True, "gorev": True, "varsayilan": False,
     "bolge_turleri": ["raf"], "duzey": "orta", "onem": 3, "taban": 3, "modeller": [ETIKET_BUL, ETIKET_OKU],
     "aciklama": "Etiketten okunan fiyat katalogdaki fiyattan farklı.",
     "ayarlar": {"fark_tl": _a("En az fark", 0.05, "TL", 0.0, 100.0, 0.05), "sure_sn": _sure(300, 30)}},
    # ------------------------------------------------------------------ müşteri
    {"kod": "yogunluk", "ad": "Yoğunluk haritası", "kategori": "musteri", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": [], "modeller": [KISI],
     "aciklama": "Kişilerin ayak noktasına göre kare başına kişi-saniye ve duran kişi-saniye haritası (32x18).",
     "ayarlar": {"durma_sn": _a("Kaç saniye yavaş kalan duruyor sayılsın (harita)", 2.0, "sn", 0.5, 30, 0.5)}},
    {"kod": "bekleme", "ad": "Bekleme süresi", "kategori": "musteri", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": ["koridor", "raf"], "modeller": [KISI],
     "aciklama": "Koridorda ya da rafın önünde yavaşlayıp en az belirli süre kalan kişiler ve kaldıkları süre.",
     "ayarlar": {"esik_sn": _a("En az kaç saniye kalan durdu sayılsın", 5.0, "sn", 1, 120, 1),
                 "hiz_esik": _a("Yavaş sayılan hız (boy/sn)", 0.3, "boy/sn", 0.05, 1.5, 0.05),
                 "raf_yakin": _a("Rafa yakınlık (kişi boyu oranı)", 0.35, "oran", 0.0, 1.5, 0.05)}},
    {"kod": "ilgi", "ad": "Raf ilgisi (gövde yönü)", "kategori": "musteri", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": ["raf"], "modeller": [KISI, ISKELET],
     "aciklama": "Rafın önünde duran kişinin gövdesinin rafa dönük olduğu süre. Bakış (göz) yönü değildir.",
     "ayarlar": {"aci": _a("Rafa dönük sayılan en büyük açı", 60, "derece", 20, 90, 5)}},
    {"kod": "uzanma", "ad": "Uzanma", "kategori": "musteri", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": ["raf"], "modeller": [KISI, ISKELET],
     "aciklama": "Bilek noktası raf bölgesine (göz tanımlıysa göz kutusuna) uzanan kol.",
     "ayarlar": {"en_az_kare": _a("Kaç analiz karesi sürerse uzanma sayılsın", 2, "kare", 1, 10, 1),
                 "kol_aci": _a("Kolun gövdeden en az açısı", 35, "derece", 10, 90, 5)}},
    {"kod": "alma", "ad": "Ürün alma", "kategori": "musteri", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": ["raf"], "modeller": [KISI, ISKELET],
     "aciklama": "Uzanmadan sonra gözdeki ürün azaldı (raf analizinin göz değişimiyle doğrulanır).", "ayarlar": {}},
    {"kod": "geri_koyma", "ad": "Geri koyma", "kategori": "musteri", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": ["raf"], "modeller": [KISI, ISKELET],
     "aciklama": "Uzanmadan sonra gözdeki ürün arttı (raf analizinin göz değişimiyle doğrulanır).", "ayarlar": {}},
    {"kod": "demografi", "ad": "Yaş grubu ve cinsiyet dağılımı", "kategori": "musteri", "olay": False, "gorev": False,
     "varsayilan": False, "bolge_turleri": [], "modeller": [KISI, OZELLIK],
     "aciklama": "Gövde görüntüsünden (yüz kullanılmaz) tahmin; yalnızca toplu sayı. Tavandan bakan kamerada güvenilmez.",
     "ayarlar": {"guven": _a("Cinsiyet için en az olasılık", 0.75, "oran", 0.5, 0.99, 0.05),
                 "yas_guven": _a("Yaş grubu için en az olasılık", 0.6, "oran", 0.34, 0.99, 0.05),
                 "en_az_ornek": _a("Kişi başına en az örnek", 3, "", 1, 15, 1),
                 "en_az_boy": _a("Kişinin en az boyu", 140, "piksel", 60, 600, 10)}},
    {"kod": "giris_sayim", "ad": "Giriş-çıkış sayımı", "kategori": "musteri", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": ["giris"], "modeller": [KISI],
     "aciklama": "Ayak noktası giriş çizgisini içeri ya da dışarı geçen kişiler.", "ayarlar": {}},
    # ------------------------------------------------------------------ operasyon
    {"kod": "kasa_kuyrugu", "ad": "Kasa kuyruğu", "kategori": "operasyon", "olay": True, "gorev": True, "varsayilan": True,
     "bolge_turleri": ["kasa"], "duzey": "yuksek", "onem": 3, "taban": 3, "modeller": [KISI],
     "aciklama": "Kasa bölgesinde bekleyen kişi sayısı eşiği aştı.",
     "ayarlar": {"esik": _a("Kaç kişide uyarı (bölgede ayrıca verilebilir)", 4, "kişi", 1, 30, 1),
                 "sure_sn": _sure(30, 0),
                 "en_az_sn": _a("Bölgede en az kaç saniye kalan bekliyor sayılsın", 3.0, "sn", 0, 60, 1)}},
    {"kod": "toplu_alma", "ad": "Toplu ürün alma", "kategori": "operasyon", "olay": True, "gorev": False, "varsayilan": False,
     "bolge_turleri": ["raf"], "duzey": "orta", "onem": 2, "taban": 3, "modeller": [KISI, ISKELET],
     "aciklama": "Bir kişi kısa sürede aynı rafa çok kez uzandı.",
     "ayarlar": {"uzanma_sayi": _a("En az uzanma sayısı", 4, "", 2, 30, 1),
                 "pencere_sn": _a("Kaç saniye içinde", 60, "sn", 10, 600, 10)}},
    {"kod": "dolap_acik", "ad": "Açık dolap kapağı", "kategori": "operasyon", "olay": True, "gorev": True, "varsayilan": True,
     "bolge_turleri": ["dolap"], "duzey": "orta", "onem": 3, "taban": 3, "modeller": [KISI],
     "aciklama": "Dolap bölgesinin görüntüsü kapalı hâlinden farklı ve önünde kimse yok.",
     "ayarlar": {"sure_sn": _sure(60), "fark_esik": _a("Kapalı görüntüden fark eşiği", 0.25, "oran", 0.05, 0.9, 0.05)}},
    {"kod": "dokulme", "ad": "Dökülme", "kategori": "operasyon", "olay": True, "gorev": True, "varsayilan": False,
     "bolge_turleri": ["koridor"], "duzey": "yuksek", "onem": 4, "taban": 2, "modeller": [KISI],
     "aciklama": "Koridor zemininde yeni, durağan, düz (az desenli) ya da parlak bir leke.",
     "ayarlar": {"sure_sn": _sure(60), "en_az_alan": _a("En az alan (koridorun oranı)", 0.004, "oran", 0.001, 0.2, 0.001),
                 "en_cok_alan": _a("En çok alan (koridorun oranı)", 0.08, "oran", 0.01, 0.5, 0.01),
                 "kisi_sn": _a("Kişi ayrıldıktan kaç saniye sonra bakılsın", 15.0, "sn", 1, 120, 1)}},
    {"kod": "tikali_koridor", "ad": "Tıkalı koridor", "kategori": "operasyon", "olay": True, "gorev": True, "varsayilan": True,
     "bolge_turleri": ["koridor"], "duzey": "orta", "onem": 3, "taban": 3, "modeller": [KISI],
     "aciklama": "Koridorda kişi olmayan, yerinden kıpırdamayan bir engel (koli, palet, araba).",
     "ayarlar": {"sure_sn": _sure(120), "alan_orani": _a("Koridorun en az ne kadarını kaplasın", 0.08, "oran", 0.01, 0.8, 0.01)}},
    # ------------------------------------------------------------------ birlikte (panel hesaplar)
    {"kod": "kayip_satis", "ad": "Kayıp satış puanı", "kategori": "birlikte", "olay": False, "gorev": False, "varsayilan": True,
     "bolge_turleri": ["raf"], "modeller": [], "aciklama": "Boş göz süresi × o gözün alma hızı (panel hesaplar).", "ayarlar": {}},
    {"kod": "doldurma_suresi", "ad": "Raf doldurma tepki süresi", "kategori": "birlikte", "olay": False, "gorev": False,
     "varsayilan": True, "bolge_turleri": ["raf"], "modeller": [],
     "aciklama": "Göz boşaldığı andan yeniden dolana kadar geçen süre (panel hesaplar).", "ayarlar": {}},
    {"kod": "tukenme_deseni", "ad": "Saate göre tükenme", "kategori": "birlikte", "olay": False, "gorev": False,
     "varsayilan": True, "bolge_turleri": ["raf"], "modeller": [],
     "aciklama": "Göz ve ürün başına saat dilimlerinde boş kalma süresi (panel hesaplar).", "ayarlar": {}},
]


def _durumlari_yukle() -> None:
    """Sınanmış durum sinama.SINAMA'dan gelir; orada olmayan özellik "deneysel"dir."""
    try:
        from .sinama import SINAMA
    except Exception:
        SINAMA = {}
    for k in KURALLAR:
        k["durum"] = (SINAMA.get(k["kod"]) or {}).get("durum") or "deneysel"
        k["ciddi"] = k.get("duzey") == "kritik"


_durumlari_yukle()
KURAL = {k["kod"]: k for k in KURALLAR}


def varsayilan_ayarlar(kod: str) -> dict:
    return {a: v["varsayilan"] for a, v in (KURAL[kod].get("ayarlar") or {}).items()}


def ozellik_ayari(ayar: dict, kod: str, eksik: dict | None = None) -> dict | None:
    """Kameranın bu özellik için kullanacağı ayarlar ({"acik": True, ad: değer}) ya da özellik kapalıysa / gereken bölge türü çizilmemişse /
    modeli eksikse None. Ayardaki değerler katalogdaki en az/en çok sınırına kırpılır."""
    k = KURAL.get(kod)
    if k is None:
        return None
    istek = ((ayar or {}).get("ozellikler") or {}).get(kod)
    istek = istek if isinstance(istek, dict) else {}
    if not istek.get("acik", k["varsayilan"]):
        return None
    if k["bolge_turleri"]:
        turler = {b.get("tur") for b in (ayar or {}).get("bolgeler") or [] if isinstance(b, dict)}
        if not turler.intersection(k["bolge_turleri"]):
            return None
    if eksik is not None and kod in eksik:
        return None
    out = {"acik": True, **varsayilan_ayarlar(kod)}  # ayarsız özellikte de boş olmayan (doğru) sözlük
    for a, tanim in (k.get("ayarlar") or {}).items():
        if a in istek:
            try:
                v = type(tanim["varsayilan"])(istek[a])
            except (TypeError, ValueError):
                continue
            if tanim.get("en_az") is not None:
                v = max(type(v)(tanim["en_az"]), v)
            if tanim.get("en_cok") is not None:
                v = min(type(v)(tanim["en_cok"]), v)
            out[a] = v
    return out


def model_var(yol: str) -> bool:
    """Model dosyası (kaynak koddan çalışırken düz .onnx) ya da paket girdisi yerinde mi."""
    if community_model.model_mi(yol):
        return os.path.isfile(yol + community_model.UZANTI)
    return os.path.isfile(yol)


def model_kilidi(klasor: str | None = None) -> dict:
    """Model paketinin durumu. Korumalı paket yalnızca AugeLab Studio'nun içinde, etkin lisansla açılır; panel modeli
    hiç açmaz, yalnızca dosyaların yerinde olup olmadığına bakar. Paket yoksa "duz" döner."""
    klasor = klasor or MODEL_KLASORU
    if community_model.isaretli(klasor) or any(community_model.model_mi(os.path.join(klasor, d)) for d in MODEL_DOSYALARI):
        return community_model.durum(klasor, MODEL_DOSYALARI)
    return {"paketli": False, "durum": "duz"}


def eksik_dosyalar(klasor: str | None = None) -> list[str]:
    """MODEL_DOSYALARI içinden klasörde bulunmayanlar."""
    klasor = klasor or MODEL_KLASORU
    return [d for d in MODEL_DOSYALARI if not model_var(os.path.join(klasor, d))]


_EKSIK = {"t": 0.0, "klasor": None, "v": {}}


def eksik_modeller(klasor: str | None = None) -> dict[str, str]:
    """Model dosyası yerinde olmadığı için çalışamayacak özellikler: {kod: eksik dosyanın adı}. Beş saniye saklanır."""
    klasor = klasor or MODEL_KLASORU
    simdi = time.monotonic()
    if _EKSIK["klasor"] == klasor and simdi - _EKSIK["t"] < 5.0:
        return _EKSIK["v"]
    eksik = set(eksik_dosyalar(klasor))
    out = {}
    for k in KURALLAR:
        yok = [m for m in k.get("modeller") or [] if m in eksik]
        if yok:
            out[k["kod"]] = yok[0]
    _EKSIK.update(t=simdi, klasor=klasor, v=out)
    return out


def coz(ayar: dict) -> list[dict]:
    """Kamerada çalışacak özellikler: katalog kaydı + "deger" (birleşmiş ayarlar). Kapalı, bölgesi çizilmemiş ya da modeli
    eksik özellik listeye girmez. Panelde değerlendirilen "birlikte" özellikleri de (kendi koşulları sağlanınca) listededir."""
    eksik = eksik_modeller()
    out = []
    for k in KURALLAR:
        deger = ozellik_ayari(ayar, k["kod"], eksik)
        if deger is not None:
            out.append({**k, "deger": deger})
    return out


def olasilik(sure_sn: float, taban: int = 3) -> int:
    """1-5: özelliğin taban olasılığı; olay sürdükçe artar (60 sn ve 300 sn'de birer basamak)."""
    return int(min(5, max(1, int(taban) + (sure_sn >= 60) + (sure_sn >= 300))))


def risk(onem: int, olas: int) -> int:
    """Risk puanı = önem × olasılık (1-25)."""
    return int(onem) * int(olas)
