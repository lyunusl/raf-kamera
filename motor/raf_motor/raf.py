"""Raf gözlerinin (slot) durumu: dolu | az | bos | yanlis | kapali | bilinmiyor.

Kullanım (Raf Ürün bloğu, her karede):

    iz = RafIzleyici(ayar, modeller, katalog=UrunKatalogu(...), referans=referans_oku(veri, kod))
    s = iz.guncelle(kare, t, kisiler, tetik=[("b1", "g1")], zaman="2026-11-15T10:00:00")

`guncelle` her karede çağrılabilir; ağır iş yalnızca kontrol zamanı geldiğinde yapılır (bkz. `kontrol_gerekli`).
Dönüş (her zaman aynı anahtarlar):

    {"kontrol": bool,                  # bu çağrıda raf kontrol edildi mi
     "kayit": dict | None,             # kuyruk kaydı `raf` içeriği (tur/kosu/kamera/kamera_ad/zaman blok ekler):
                                       #   {"doluluk", "uyum", "referans": "kayitli"|"gecici", "gozler": [...]}
                                       #   durum değişince ya da en geç KAYIT_ARALIGI_SN'de bir verilir
     "gecisler": [ {"bolge", "goz", "once", "sonra", "t", "doluluk", "adet", "urun", "gorulen", "benzerlik"} ],
                                       # kesinleşmiş durum değişimleri (kapali hiçbir zaman geçiş değildir)
     "adet_degisimleri": [ {"bolge", "goz", "once", "sonra", "t", "tetik": bool} ],
                                       # kararlı yüz sayısı değişti (alma/geri koyma doğrulaması için)
     "etiket_gecisleri": [ {"bolge", "goz", "once", "sonra", "t", "metin", "fiyat", "beklenen"} ],
                                       # kesinleşmiş etiket durumu (uygun|farkli|yok|okunamadi) değişimi
     "sure_ms": float}

Karar (her göz, her kontrolde; ayrıntı `_gozlem` ve `_karar`):
- Göz kutusu bir kişi kutusuyla KAPALI_ORANI'ndan çok örtüşüyorsa ya da bir bilek noktası gözün içindeyse: `kapali`
  (o kareden karar verilmez, önceki kesin durum korunur).
- Pozlama: kare, referans karenin kanal ortalama/sapmasına çekilir (kişiler dışında kalan piksellerden).
- Yalnızca görünümü değişen gözler yeniden incelenir (24x24 gri imza farkı >= degisim_esik); dedektör yalnızca değişen
  gözü olan bölgenin kırpıntısında, gömme yalnızca değişen gözlerde çalışır.
- Doluluk: `doluluk_hesapla` (dedektör kapsaması ve yüz sayısı referansa oranla; doku ve referansa gömme benzerliği
  düzeltme olarak). `bos` < bos_esik <= `az` < az_esik <= `dolu`.
- `yanlis` (göz referanstan belirgin farklıysa: s_ref < yanlis_ref_ust): katalog güvenle başka bir ürün görüyor ya da
  göz dolu ama ne beklenen ürüne ne referansa benziyor (ikisi de < yanlis_bek_esik; `gorulen` o zaman null olabilir).
  Ürün tanımsız gözde yalnızca `referans_yanlis` açıksa (varsayılan kapalı).
- Kalıcılık: yeni durum `sure` saniye (ve en az iki kontrol) sürmeden kesinleşmez. Sürelerin varsayılanı aşağıda;
  kamera ayarındaki `ozellikler.<kod>.sure_sn` üstüne yazar.
"""
from __future__ import annotations

import datetime as dt
import os
import time

import cv2
import numpy as np

from .raf_modeller import kirp

DURUMLAR = ("dolu", "az", "bos", "yanlis", "kapali", "bilinmiyor")
KAYIT_ARALIGI_SN = 60.0

VARSAYILAN = {
    "raf_araligi_sn": 10.0,     # periyodik kontrol aralığı (kamera ayarında `raf_araligi_sn`)
    "bos_esik": 0.15,           # doluluk bunun altındaysa boş
    "az_esik": 0.55,            # doluluk bunun altındaysa az
    "kapali_orani": 0.12,       # göz alanının bu kadarı bir kişi kutusunun altındaysa göz kapalı
    "dolu_sure_sn": 20.0,       # boş/az/yanlış -> dolu geçişinin kalıcılık süresi
    "bos_sure_sn": 20.0,        # bos_raf.sure_sn (katalog varsayılanı 20)
    "az_sure_sn": 60.0,         # az_stok.sure_sn
    "yanlis_sure_sn": 60.0,     # yanlis_urun.sure_sn
    "ref_ayni": 0.92,           # göz gömmesi referansa bu kadar benziyorsa dedektör ne derse desin en az 0.9 dolu
    "yanlis_ref_ust": 0.80,     # göz referansa bundan çok benziyorsa yanlış denmez (referans = doğru dolu raf)
    "yanlis_bek_esik": 0.45,   # beklenen ürüne ve referansa benzerlik bunun altındaysa (göz doluyken) yanlış
    "yanlis_pay": 0.05,       # görülen ürün beklenene göre en az bu kadar daha benzer olmalı
    "referans_yanlis": False,   # ürünü tanımsız gözde "referansa hiç benzemiyor" -> yanlış (deneysel, kapalı)
    "referans_yanlis_esik": 0.45,
    "degisim_esik": 6.0,        # göz imzası (pozlaması düzeltilmiş 24x24 gri) bu ortalama farkın altındaysa değişmemiş
    "gecici_kare": 3,           # referans dosyası yoksa ilk bu kadar kontrolün en dolusu geçici referans olur
    "etiket_araligi_sn": 900.0,  # etiketler bu aralıkla yeniden okunur (değişim ve koşu başı dışında)
    "etiket_her_kontrol": 4,    # bir kontrolde en çok bu kadar etiket okunur
    "etiket_teyit": 2,          # etiket durumu (yok/farkli/okunamadi) bu kadar ardışık okumada aynı çıkmadan kesinleşmez
    "etiket_yok_sure_sn": 300.0,    # etiket_yok.sure_sn: "yok" ilk okumadan bu kadar sonra da sürüyorsa kesinleşir
    "fiyat_farkli_sure_sn": 300.0,  # fiyat_farkli.sure_sn
    "fiyat_tolerans": 0.01,     # fiyat_farkli.fark_tl: okunan ile beklenen arasındaki bu kadar fark "aynı"
    "teyit_sn": 2.0,            # tetikli (uzanma sonrası) kontrolün ikinci bakışı
    "artis_orani": 0.25,        # geri koyma sayılan artış: referans yüz sayısının en az bu oranı (boş göze konan her zaman)
    "dokunma_pencere_sn": 15.0, # sayı değişimi, göze son dokunuştan (örtme, değme, uzanma) bu kadar içinde olmalı
    "sayim_teyit": 2,          # yüz sayısı düşüşü bu kadar ardışık açık gözlemde aynı olmalı (artış bir fazlasını ister)
    "eslesme_yuz": 3,           # ürün eşlemesi için göz başına en çok bu kadar yüz kırpıntısı
    "ref_bos_kenar": 0.6,     # referansta ürün bulunmayan göz, dokusu bölgedeki dolu gözlerin bu oranından azsa "referansta boş"
    "ref_bos_doyma": 45.0,      # ... ve ortalama renk doygunluğu bundan azsa (gri/beyaz raf; düz renkli koli boş sayılmaz)
    "ref_bos_fark": 0.85,       # referansta boş gözde boş görünüme gömme benzerliği bunun altına düştükçe "bir şey var"
}
_OZELLIK_AYAR = {("bos_raf", "sure_sn"): "bos_sure_sn", ("az_stok", "sure_sn"): "az_sure_sn",
                 ("yanlis_urun", "sure_sn"): "yanlis_sure_sn", ("az_stok", "doluluk_esik"): "az_esik",
                 ("yanlis_urun", "benzerlik_esik"): "yanlis_bek_esik", ("fiyat_farkli", "fark_tl"): "fiyat_tolerans",
                 ("etiket_yok", "sure_sn"): "etiket_yok_sure_sn", ("fiyat_farkli", "sure_sn"): "fiyat_farkli_sure_sn"}


def referans_yolu(veri: str, kod: str) -> str:
    return os.path.join(veri, "ayar", f"_referans_{kod}.jpg")


def referans_oku(veri: str, kod: str) -> np.ndarray | None:
    """Sözleşme bölüm 7: `<VERI>/ayar/_referans_<kod>.jpg` (yoksa None: motor geçici referans kullanır)."""
    yol = referans_yolu(veri, kod)
    try:
        v = np.fromfile(yol, np.uint8)
    except OSError:
        return None
    return cv2.imdecode(v, cv2.IMREAD_COLOR) if v.size else None


def ayarlari_coz(ayar: dict) -> dict:
    """Kamera ayarından raf ayarları: VARSAYILAN + `raf_araligi_sn` + `ozellikler.<kod>.<ayar>` (katalogdaki ayar adları:
    sure_sn, az_stok.doluluk_esik, yanlis_urun.benzerlik_esik, fiyat_farkli.fark_tl) + `ozellikler.raf_ayar` (ince ayar)."""
    a = dict(VARSAYILAN)
    if ayar.get("raf_araligi_sn"):
        a["raf_araligi_sn"] = float(ayar["raf_araligi_sn"])
    oz = ayar.get("ozellikler") or {}
    for (kod, alan), anahtar in _OZELLIK_AYAR.items():
        s = (oz.get(kod) or {}).get(alan) if isinstance(oz.get(kod), dict) else None
        if isinstance(s, (int, float)) and not isinstance(s, bool) and s >= 0:
            a[anahtar] = float(s)
    for k, v in ((oz.get("raf_ayar") or {}) if isinstance(oz.get("raf_ayar"), dict) else {}).items():
        if k in a:
            a[k] = type(a[k])(v)
    return a


def gozleri_al(ayar: dict) -> list[dict]:
    """Raf bölgelerindeki gözler: [{"bolge", "bolge_ad", "goz", "kutu", "urun", "adet", "etiket", "fiyat"}]."""
    out = []
    for b in ayar.get("bolgeler") or []:
        if b.get("tur") != "raf":
            continue
        for g in b.get("gozler") or []:
            try:
                k = [float(v) for v in g["kutu"][:4]]
            except (KeyError, TypeError, ValueError):
                continue
            if k[2] - k[0] <= 0 or k[3] - k[1] <= 0:
                continue
            et = g.get("etiket")
            out.append({"bolge": str(b.get("kimlik") or ""), "bolge_ad": str(b.get("ad") or ""),
                        "goz": str(g.get("kimlik") or ""), "kutu": k, "urun": g.get("urun") or None,
                        "adet": max(1, int(g.get("adet") or 1)),
                        "etiket": [float(v) for v in et[:4]] if isinstance(et, (list, tuple)) and len(et) >= 4 else None,
                        "fiyat": g.get("fiyat")})
    return out


# --- saf yardımcılar (birim sınamaları bunları doğrudan çağırır) ---------------------------------------------------------
def kapsama(kutular: np.ndarray, goz: list[float]) -> tuple[float, int]:
    """Merkezi göz içinde kalan kutuların göz genişliğindeki yatay kapsaması (0-1) ve sayısı. Koordinatlar aynı birimde."""
    x1, y1, x2, y2 = goz
    if not len(kutular) or x2 <= x1:
        return 0.0, 0
    cx = (kutular[:, 0] + kutular[:, 2]) / 2
    cy = (kutular[:, 1] + kutular[:, 3]) / 2
    ic = (cx >= x1) & (cx <= x2) & (cy >= y1) & (cy <= y2)
    if not ic.any():
        return 0.0, 0
    araliklar = sorted((max(x1, a), min(x2, b)) for a, b in kutular[ic][:, [0, 2]])
    top, bas, son = 0.0, None, None
    for a, b in araliklar:
        if bas is None:
            bas, son = a, b
        elif a <= son:
            son = max(son, b)
        else:
            top += son - bas
            bas, son = a, b
    top += son - bas
    return float(min(1.0, top / (x2 - x1))), int(ic.sum())


def doluluk_hesapla(kap: float | None, adet: int | None, ref_kap: float, ref_adet: int, d_kenar: float | None,
                    s_ref: float | None, ref_ayni: float = 0.92) -> float | None:
    """Gözün doluluğu (0-1).

    Dedektör bu gözde referansta ürün bulduysa (ref_kap >= 0.2): 0.65 x (kapsama / referans kapsaması) +
    0.35 x (görülen yüz / referans yüz). Dedektör kalan yüzleri kaçırmış olabilir: sonuç < 0.3 iken doku ve görünüm
    hâlâ ürün diyorsa (doku >= 0.5, s_ref >= 0.5) 0.3'e çıkar (az).
    Bulamadıysa (koyu şişe, eğik açı, elle çizilmiş göz): mutlak kapsama ile referansa benzerlikten
    ((s_ref - 0.45) / 0.4) büyük olanı; ikisi de yoksa doku.
    Ortak düzeltmeler: görünüm referansla neredeyse aynıysa (s_ref >= ref_ayni, kenar oranı >= 0.75) en az 0.9.
    Dedektör dokudan 0.3'ten fazla "dolu" diyorsa ve kenar oranı 0.5'in altına düşüp görünüm referansa benzemiyorsa
    (s_ref < 0.6) ya da kenar oranı 0.3'ün altındaysa doluluk dokuya
    ((oran - 0.2) / 0.6) eşitlenir: dedektör düz arka paneli de "kutu" sanabiliyor (gerçek fotoğraf denemelerinde görüldü).
    Hiç kanıt yoksa None."""
    doku = None if d_kenar is None else float(np.clip((d_kenar - 0.2) / 0.6, 0, 1))
    if kap is not None and ref_kap >= 0.2:
        det = min(1.0, kap / max(ref_kap, 0.3))
        dol = 0.65 * det + 0.35 * min(1.0, adet / ref_adet) if (adet is not None and ref_adet >= 1) else det
        if dol < 0.3 and doku is not None and doku >= 0.5 and s_ref is not None and s_ref >= 0.5:
            dol = 0.3
    else:
        kanit = []
        if kap is not None:
            kanit.append(min(1.0, kap))
        if s_ref is not None:
            kanit.append(float(np.clip((s_ref - 0.45) / 0.4, 0, 1)))
        if kanit:
            dol = max(kanit)
        elif doku is not None:
            dol = doku
        else:
            return None
    if s_ref is not None and s_ref >= ref_ayni and d_kenar is not None and d_kenar >= 0.75:
        dol = max(dol, 0.9)
    elif doku is not None and dol - doku > 0.3 and ((d_kenar < 0.5 and (s_ref is None or s_ref < 0.6)) or d_kenar < 0.3):
        dol = doku
    return float(np.clip(dol, 0, 1))


def kapali_mi(goz: list[float], kisiler: list, oran: float) -> bool:
    """Göz kutusu (piksel) bir kişi kutusunca `oran`dan fazla örtülüyor mu ya da bir bilek içinde mi."""
    x1, y1, x2, y2 = goz
    alan = max(1e-6, (x2 - x1) * (y2 - y1))
    for k in kisiler:
        b = k.get("b")
        if b is not None:
            ix = max(0.0, min(x2, b[2]) - max(x1, b[0]))
            iy = max(0.0, min(y2, b[3]) - max(y1, b[1]))
            if ix * iy / alan > oran:
                return True
        for p in k.get("eller") or ():
            if x1 <= p[0] <= x2 and y1 <= p[1] <= y2:
                return True
    return False


def ortulu_mu(goz: list[float], kisiler: list, pay: float = 0.05) -> bool:
    """Göz kutusuna (piksel) herhangi bir kişi kutusu (her yanda `pay` kadar genişletilmiş) değiyor mu. Yüz sayımı yalnızca
    tamamen açık gözde güvenilirdir (kısmen örtülen gözde sayı oynar ve sahte alma/geri koyma üretir)."""
    x1, y1, x2, y2 = goz
    for k in kisiler:
        b = k.get("b")
        if b is None:
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        if min(x2, b[2] + pay * w) > max(x1, b[0] - pay * w) and min(y2, b[3] + pay * h) > max(y1, b[1] - pay * h):
            return True
    return False


def kisileri_coz(kisiler, W: int, H: int) -> list[dict]:
    """Raf Kişi çıktısındaki kişileri piksel kutu + bilek noktalarına çevirir. Kutu 0-1 ise ölçeklenir.
    Kabul edilen biçim: {"b": [x1,y1,x2,y2], "k": [[x,y,güven] x17] (isteğe bağlı, standart sıra; 9-10 bilekler)}."""
    out = []
    for k in kisiler or []:
        if not isinstance(k, dict) or k.get("b") is None:
            continue
        try:
            b = [float(v) for v in k["b"][:4]]
        except (TypeError, ValueError):
            continue
        olcek = max(b) <= 1.5
        if olcek:
            b = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
        eller = []
        nok = k.get("k")
        if isinstance(nok, list) and len(nok) >= 11:
            for i in (9, 10):
                try:
                    x, y, c = (float(v) for v in nok[i][:3])
                except (TypeError, ValueError, IndexError):
                    continue
                if c >= 0.4:
                    eller.append((x * W, y * H) if olcek else (x, y))
        out.append({"b": b, "eller": eller})
    return out


class Pozlama:
    """Karenin kanal ortalama/sapmasını referansınkine eşler (otomatik pozlama, ışık değişimi)."""

    def __init__(self, referans: np.ndarray | None):
        self.ref = self._istatistik(referans, None) if referans is not None else None

    @staticmethod
    def _istatistik(kare: np.ndarray, maske: np.ndarray | None):
        k = cv2.resize(kare, (160, max(1, int(160 * kare.shape[0] / kare.shape[1]))), interpolation=cv2.INTER_AREA)
        p = k.reshape(-1, 3).astype(np.float32)
        if maske is not None:
            m = cv2.resize(maske, (k.shape[1], k.shape[0]), interpolation=cv2.INTER_NEAREST).reshape(-1) > 0
            if m.sum() > 200:
                p = p[m]
        return p.mean(0), np.maximum(p.std(0), 1.0)

    def referans_ayarla(self, referans: np.ndarray) -> None:
        self.ref = self._istatistik(referans, None)

    def duzelt(self, kare: np.ndarray, kisiler: list[dict]) -> tuple[np.ndarray, float]:
        """Dönüş: (düzeltilmiş kare, kazanç (1 = değişiklik yok))."""
        if self.ref is None:
            return kare, 1.0
        H, W = kare.shape[:2]
        maske = np.ones((H, W), np.uint8)
        for k in kisiler:
            x1, y1, x2, y2 = (int(v) for v in k["b"])
            maske[max(0, y1):max(0, y2), max(0, x1):max(0, x2)] = 0
        m, s = self._istatistik(kare, maske)
        rm, rs = self.ref
        kaz = np.clip(rs / s, 0.4, 2.5)
        if np.all(np.abs(kaz - 1) < 0.03) and np.all(np.abs(m - rm) < 3):
            return kare, 1.0
        lut = np.stack([np.clip((np.arange(256) - m[c]) * kaz[c] + rm[c], 0, 255) for c in range(3)], 1).astype(np.uint8)
        out = np.empty_like(kare)
        for c in range(3):
            out[:, :, c] = cv2.LUT(kare[:, :, c], lut[:, c])
        return out, float(kaz.mean())


def imza(kirpinti: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(kirpinti, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (24, 24), interpolation=cv2.INTER_AREA).astype(np.float32)


def doyma(kirpinti: np.ndarray) -> float:
    """Ortalama renk doygunluğu (HSV S, 0-255): boş raf arkalığı ve rafın kendisi gri/beyazdır."""
    return float(cv2.cvtColor(kirpinti, cv2.COLOR_BGR2HSV)[:, :, 1].mean())


def kenar(kirpinti: np.ndarray) -> float:
    g = cv2.cvtColor(kirpinti, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.resize(g, (96, max(8, int(96 * g.shape[0] / max(1, g.shape[1])))), interpolation=cv2.INTER_AREA)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    return float(np.sqrt(gx * gx + gy * gy).mean())


class Kalicilik:
    """Bir gözün kesin durumu ve aday durumun ne zamandır görüldüğü (saf mantık, model yok)."""

    def __init__(self):
        self.durum = "bilinmiyor"
        self.aday: str | None = None
        self.aday_t = 0.0
        self.aday_n = 0

    def gozle(self, gozlem: str, t: float, sure: float, en_az: int = 2) -> tuple[str, str] | None:
        """`gozlem`: bu kontrolün kararı. "kapali" ve "bilinmiyor" kesin durumu değiştirmez (aday da sıfırlanmaz).
        Dönüş: kesinleşen geçiş (eski, yeni) ya da None. bilinmiyor -> dolu hemen kesinleşir."""
        if gozlem in ("kapali", "bilinmiyor"):
            return None
        if gozlem == self.durum:
            self.aday, self.aday_n = None, 0
            return None
        if self.durum == "bilinmiyor" and gozlem == "dolu":
            self.durum, self.aday, self.aday_n = "dolu", None, 0
            return ("bilinmiyor", "dolu")
        if gozlem != self.aday:
            self.aday, self.aday_t, self.aday_n = gozlem, t, 1
        else:
            self.aday_n += 1
        if self.aday_n >= en_az and t - self.aday_t >= sure:
            eski = self.durum
            self.durum, self.aday, self.aday_n = gozlem, None, 0
            return (eski, gozlem)
        return None


class _Goz:
    def __init__(self, g: dict):
        self.__dict__.update(g)
        self.k = Kalicilik()
        self.kapali = False
        self.ref_kirp = None      # referans kırpıntısı (pozlaması referans karesinde)
        self.ref_v = None         # referans gömmesi
        self.ref_kap, self.ref_adet, self.ref_kenar = 0.0, 0, 0.0
        self.ref_bos = False      # referans karesinde de boş (bkz. RafIzleyici._ref_boslari_isaretle)
        self.imza = None          # son açık gözlemin imzası
        self.son = None           # son açık gözlem (sözlük)
        self.adet_kararli = None
        self.adet_gecmis: list[int] = []
        self.dokunma_t = -1e9     # bir kişinin gözü son örttüğü / değdiği / uzandığı an
        self.etiket_durum = "bakilmadi"
        self.etiket_aday, self.etiket_n, self.etiket_aday_t = None, 0, 0.0
        self.etiket_fiyat = None
        self.etiket_metin = ""
        self.etiket_son_t = None
        self.etiket_iste = True


class RafIzleyici:
    """Bir kameranın raf gözlerini izler. `modeller`: raf_modeller.Modeller; `katalog`: urun.UrunKatalogu ya da None;
    `referans`: kayıtlı referans karesi (BGR) ya da None (geçici referans); `etiketci`: etiket.EtiketOkuyucu ya da None."""

    def __init__(self, ayar: dict, modeller, katalog=None, referans: np.ndarray | None = None, etiketci=None):
        self.ayar = ayar
        self.a = ayarlari_coz(ayar)
        self.m = modeller
        self.katalog = katalog
        self.etiketci = etiketci
        self.gozler = [_Goz(g) for g in gozleri_al(ayar)]
        self.referans_turu = "kayitli" if referans is not None else "gecici"
        self._ref_kare = referans
        self._ref_hazir = False
        self.poz = Pozlama(None)
        self.son_kontrol: float | None = None
        self.son_kayit_t: float | None = None
        self._degisti = True
        self._tetik: dict[tuple[str, str], list[float]] = {}
        self._gecici_n = 0
        self._gecici: dict[int, tuple] = {}
        self._bolge_kutu: dict[str, list[float]] = {}
        for b in ayar.get("bolgeler") or []:
            if b.get("tur") == "raf":
                self._bolge_kutu[str(b.get("kimlik") or "")] = self._bolge_cerceve(b)
        self.son_sure_ms = 0.0

    @staticmethod
    def _bolge_cerceve(b: dict) -> list[float]:
        xs, ys = [], []
        for p in b.get("poly") or []:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
        for g in b.get("gozler") or []:
            try:
                xs += [float(g["kutu"][0]), float(g["kutu"][2])]
                ys += [float(g["kutu"][1]), float(g["kutu"][3])]
            except (KeyError, TypeError, ValueError, IndexError):
                pass
        if not xs:
            return [0.0, 0.0, 1.0, 1.0]
        return [max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys))]

    # -- dış arayüz ----------------------------------------------------------------------------------------------------
    def tetikle(self, bolge: str, goz: str | None, t: float) -> None:
        """Kişi tarafı: bir uzanma bitti. Göz (None ise bölgenin tüm gözleri) açık olunca hemen ve teyit_sn sonra bakılır."""
        for g in self.gozler:
            if g.bolge == bolge and (goz is None or g.goz == goz):
                self._tetik[(g.bolge, g.goz)] = [t, t + self.a["teyit_sn"]]
                g.dokunma_t = t  # uzanılan göz: sonraki sayı değişimi alma / geri koyma adayıdır

    def kontrol_gerekli(self, t: float) -> bool:
        if self.son_kontrol is None or t - self.son_kontrol >= self.a["raf_araligi_sn"] or t < self.son_kontrol:
            return True
        if not self._ref_hazir:
            return t - self.son_kontrol >= 1.0
        return any(v and v[0] <= t for v in self._tetik.values())

    def guncelle(self, kare: np.ndarray, t: float, kisiler=(), tetik=(), zaman: str | None = None) -> dict:
        """Bkz. modül açıklaması. `kisiler`: Raf Kişi'nin kişi listesi (piksel ya da 0-1 kutular). `tetik`: [(bolge, goz)]
        uzanması yeni biten gözler. `zaman`: kaydın ISO zamanı (verilmezse şimdiki yerel saat)."""
        for b, g in tetik or ():
            self.tetikle(b, g, t)
        sonuc = {"kontrol": False, "kayit": None, "gecisler": [], "adet_degisimleri": [], "etiket_gecisleri": [],
                 "sure_ms": 0.0}
        if not self.gozler or kare is None:
            return sonuc
        if not self.kontrol_gerekli(t):
            return sonuc
        bas = time.perf_counter()
        H, W = kare.shape[:2]
        kisiler_px = kisileri_coz(kisiler, W, H)
        tam = self.son_kontrol is None or t - self.son_kontrol >= self.a["raf_araligi_sn"] or t < self.son_kontrol
        self.son_kontrol = t if tam or self.son_kontrol is None else self.son_kontrol
        self._referans_hazirla(kare, kisiler_px)
        duz, _ = self.poz.duzelt(kare, kisiler_px)
        bakilacak = set()
        if tam or not self._ref_hazir:
            bakilacak = {id(g) for g in self.gozler}
        for g in self.gozler:
            v = self._tetik.get((g.bolge, g.goz))
            if v and v[0] <= t:
                bakilacak.add(id(g))
        gozlemler = self._gozlemle(duz, kisiler_px, [g for g in self.gozler if id(g) in bakilacak], t)
        sonuc["kontrol"] = True
        if not self._ref_hazir:
            self._gecici_topla(duz, gozlemler)
            if not self._ref_hazir:
                sonuc["sure_ms"] = round((time.perf_counter() - bas) * 1000, 1)
                self.son_sure_ms = sonuc["sure_ms"]
                return sonuc
            for g, gz in gozlemler:  # referans bu kontrolde hazır oldu: aynı gözlemler referansla yeniden karara girer
                if gz["durum"] != "kapali" and "kenar" in gz:
                    self._karar(g, gz)
        for g, gz in gozlemler:
            onceki_kapali = g.kapali
            g.kapali = gz["durum"] == "kapali"
            if g.kapali != onceki_kapali:
                self._degisti = True
            if not g.kapali:
                g.son = gz
                self._sayim(g, gz, t, sonuc)
            else:
                g.dokunma_t = t
            # bir kişi göze değerken (kısmen örtülü) durum kararı da verilmez: sepet, kol, bacak gözün bir kısmını kapatıp
            # sahte "az/boş" ya da "dolu" gösterebilir; kişi ayrılınca göz yeniden bakılır
            gec = g.k.gozle("kapali" if gz.get("ortulu") else gz["durum"], t, self._sure(gz["durum"]))
            if gec:
                self._degisti = True
                g.etiket_iste = True
                sonuc["gecisler"].append({"bolge": g.bolge, "goz": g.goz, "once": gec[0], "sonra": gec[1], "t": t,
                                          "doluluk": gz.get("doluluk"), "adet": gz.get("adet"), "urun": g.urun,
                                          "gorulen": gz.get("gorulen"), "benzerlik": gz.get("benzerlik")})
            v = self._tetik.get((g.bolge, g.goz))
            if v and v[0] <= t and not g.kapali:
                v.pop(0)
                if not v:
                    self._tetik.pop((g.bolge, g.goz), None)
        if tam:
            self._etiketler(kare, t, sonuc)
        if self.referans_turu == "gecici":
            self._gecici_iyilestir(duz)
        if self._degisti or self.son_kayit_t is None or t - self.son_kayit_t >= KAYIT_ARALIGI_SN or t < self.son_kayit_t:
            sonuc["kayit"] = self.kayit(zaman)
            self.son_kayit_t = t
            self._degisti = False
        sonuc["sure_ms"] = round((time.perf_counter() - bas) * 1000, 1)
        self.son_sure_ms = sonuc["sure_ms"]
        return sonuc

    def kayit(self, zaman: str | None = None) -> dict:
        """Sözleşme 4.3 `raf` kaydının içeriği (tur, kosu, kamera, kamera_ad blok tarafından eklenir)."""
        gozler, dol, uy_pay, uy_payda = [], [], 0, 0
        katalog_var = self.katalog is not None and len(getattr(self.katalog, "kimlikler", [])) > 0
        for g in self.gozler:
            s = g.son or {}
            durum = "kapali" if g.kapali else g.k.durum
            if g.k.durum != "bilinmiyor" and s.get("doluluk") is not None:
                dol.append(float(s["doluluk"]))
            if g.urun and katalog_var and g.k.durum != "bilinmiyor":
                uy_payda += 1
                # sözleşme 4.3 (panelin "şimdi" tanımıyla aynı): ürün taşıyan ve başka ürün görülmeyen göz uyumludur;
                # tanıma kesinleşmedi diye (gorulen boş) göz uyumsuz sayılmaz (örnek kliplerde uyum %2 çıkıyordu)
                if g.k.durum in ("dolu", "az") and s.get("gorulen") in (None, g.urun):
                    uy_pay += 1
            gozler.append({"bolge": g.bolge, "goz": g.goz, "durum": durum,
                           "doluluk": None if s.get("doluluk") is None else round(float(s["doluluk"]), 2),
                           "adet": s.get("adet"), "urun": g.urun, "gorulen": s.get("gorulen"),
                           "benzerlik": None if s.get("benzerlik") is None else round(float(s["benzerlik"]), 3),
                           "etiket": g.etiket_durum if g.etiket else "bakilmadi", "fiyat": g.etiket_fiyat})
        return {"zaman": zaman or dt.datetime.now().replace(microsecond=0).isoformat(),
                "doluluk": round(float(np.mean(dol)), 3) if dol else None,
                "uyum": round(uy_pay / uy_payda, 3) if uy_payda else None,
                "referans": self.referans_turu, "gozler": gozler}

    # -- referans ------------------------------------------------------------------------------------------------------
    def _referans_hazirla(self, kare: np.ndarray, kisiler_px: list[dict]) -> None:
        if self._ref_hazir or self._ref_kare is None:
            return
        ref = self._ref_kare
        if ref.shape[:2] != kare.shape[:2]:
            ref = cv2.resize(ref, (kare.shape[1], kare.shape[0]), interpolation=cv2.INTER_AREA)
        self._ref_kare = ref
        self.poz.referans_ayarla(ref)
        gz = self._gozlemle(ref, [], self.gozler, None, referans=True)
        self._referans_kur(ref, gz)

    def _referans_kur(self, ref: np.ndarray, gozlemler) -> None:
        kirpintilar, sahip = [], []
        for g, gz in gozlemler:
            c = kirp(ref, g.kutu)
            g.ref_kirp = None if c is None else c.copy()
            g.ref_kap, g.ref_adet, g.ref_kenar = gz.get("kap", 0.0), gz.get("adet", 0), gz.get("kenar", 0.0)
            if c is not None:
                kirpintilar.append(c)
                sahip.append(g)
        if kirpintilar and self.m is not None and self.m.var_mi("gomme.onnx"):
            for g, v in zip(sahip, self.m.gomme(kirpintilar)):
                g.ref_v = v
        self._ref_hazir = True
        self._degisti = True
        self._ref_boslari_isaretle()

    def _ref_boslari_isaretle(self) -> None:
        """Referans karesinde zaten boş olan gözler: dedektör ürün bulmadı (ref_kap < 0.2) ve dokusu bölgedeki dolu
        gözlerin ortancasının yarısından az. Böyle bir göz kendi referansına benzedikçe "dolu" sayılırdı; bunun yerine
        bölgedeki dolu gözlerle karşılaştırılır (raf boşken kaydedilen referans ya da baştan boş göz)."""
        bolge_kenar: dict[str, list[float]] = {}
        for g in self.gozler:
            if g.ref_kirp is not None and g.ref_kap >= 0.2 and g.ref_kenar:
                bolge_kenar.setdefault(g.bolge, []).append(g.ref_kenar)
        self._bolge_kenar = {b: float(np.median(v)) for b, v in bolge_kenar.items() if len(v) >= 2}
        for g in self.gozler:
            ort = self._bolge_kenar.get(g.bolge)
            g.ref_bos = bool(ort and g.ref_kirp is not None and g.ref_kap < 0.2
                             and g.ref_kenar < self.a["ref_bos_kenar"] * ort
                             and doyma(g.ref_kirp) < self.a["ref_bos_doyma"])  # boş raf gri/beyaz; düz renkli koli değil

    def _gecici_topla(self, duz: np.ndarray, gozlemler) -> None:
        """Referans dosyası yok: ilk `gecici_kare` kontrolde her gözün en dolu (en çok kapsama + kenar) görünümü."""
        for g, gz in gozlemler:
            if gz["durum"] == "kapali":
                continue
            c = kirp(duz, g.kutu)
            if c is None:
                continue
            puan = gz.get("kap", 0.0) + 0.01 * gz.get("kenar", 0.0)
            onceki = self._gecici.get(id(g))
            if onceki is None or puan > onceki[0]:
                self._gecici[id(g)] = (puan, c.copy(), gz)
        self._gecici_n += 1
        if self._gecici_n >= int(self.a["gecici_kare"]) and len(self._gecici) == len(self.gozler):
            self._gecici_bitir(duz)
        elif self._gecici_n >= 4 * int(self.a["gecici_kare"]):
            self._gecici_bitir(duz)  # bazı gözler hep kapalıydı: onlar ilk açık görüldüğünde tamamlanır

    def _gecici_bitir(self, duz: np.ndarray) -> None:
        self.poz.referans_ayarla(duz)
        kirpintilar, sahip = [], []
        for g in self.gozler:
            e = self._gecici.get(id(g))
            if e is None:
                continue
            _, c, gz = e
            g.ref_kirp = c
            g.ref_kap, g.ref_adet, g.ref_kenar = gz.get("kap", 0.0), gz.get("adet", 0), gz.get("kenar", 0.0)
            kirpintilar.append(c)
            sahip.append(g)
        if kirpintilar and self.m is not None and self.m.var_mi("gomme.onnx"):
            for g, v in zip(sahip, self.m.gomme(kirpintilar)):
                g.ref_v = v
        self._ref_hazir = True
        self._degisti = True
        self._ref_boslari_isaretle()

    def _gecici_iyilestir(self, duz: np.ndarray) -> None:
        """Geçici referansta: gözün kesin durumu dolu ve kapsaması referanstakinden büyükse referans güncellenir
        (koşu boş bir gözle başladıysa referans sonradan dolu görünüme kavuşur)."""
        for g in self.gozler:
            s = g.son
            if s is None or g.kapali:
                continue
            if g.ref_kirp is None or (g.k.durum == "dolu" and s.get("kap", 0) > g.ref_kap + 0.1):
                c = kirp(duz, g.kutu)
                if c is None:
                    continue
                g.ref_kirp = c.copy()
                g.ref_kap, g.ref_adet, g.ref_kenar = s.get("kap", 0.0), s.get("adet", 0), s.get("kenar", 0.0)
                g.ref_v = s.get("_v")
                g.ref_bos = False

    # -- gözlem ve karar -----------------------------------------------------------------------------------------------
    def _sure(self, durum: str) -> float:
        return {"dolu": self.a["dolu_sure_sn"], "bos": self.a["bos_sure_sn"], "az": self.a["az_sure_sn"],
                "yanlis": self.a["yanlis_sure_sn"]}.get(durum, 0.0)

    def _gozlemle(self, kare: np.ndarray, kisiler_px: list[dict], gozler: list[_Goz], t, referans: bool = False):
        """Her göz için gözlem sözlüğü: {"durum", "doluluk", "adet", "kap", "kenar", "gorulen", "benzerlik", ...}."""
        H, W = kare.shape[:2]
        out = []
        bolgeler: dict[str, list[_Goz]] = {}
        acik = []
        for g in gozler:
            px = [g.kutu[0] * W, g.kutu[1] * H, g.kutu[2] * W, g.kutu[3] * H]
            if not referans and kapali_mi(px, kisiler_px, self.a["kapali_orani"]):
                out.append((g, {"durum": "kapali"}))
                continue
            acik.append(g)
            bolgeler.setdefault(g.bolge, []).append(g)
        # değişmeyen gözler: önceki gözlem aynen kullanılır. Dedektör yalnızca değişen gözü olan bölgede, gömme
        # yalnızca değişen gözlerde çalışır (periyodik kontrolün olağan hâli birkaç ms).
        degisen_bolge, degisen = set(), set()
        imzalar = {}
        for g in acik:
            c = kirp(kare, g.kutu)
            imzalar[id(g)] = None if c is None else imza(c)
            if referans or g.son is None or g.imza is None or imzalar[id(g)] is None or \
                    float(np.abs(imzalar[id(g)] - g.imza).mean()) >= self.a["degisim_esik"] or \
                    (g.bolge, g.goz) in self._tetik:
                degisen_bolge.add(g.bolge)
                degisen.add(id(g))
        kutular_bolge = {}
        if self.m is not None and self.m.var_mi("urun.onnx"):
            for b in degisen_bolge:
                x1, y1, x2, y2 = self._bolge_kutu.get(b, [0, 0, 1, 1])
                X1, Y1 = int(max(0, (x1 - 0.01) * W)), int(max(0, (y1 - 0.01) * H))
                X2, Y2 = int(min(W, (x2 + 0.01) * W)), int(min(H, (y2 + 0.01) * H))
                if X2 - X1 < 16 or Y2 - Y1 < 16:
                    kutular_bolge[b] = np.zeros((0, 4), np.float32)
                    continue
                k, _ = self.m.urun_bul(kare[Y1:Y2, X1:X2])
                if len(k):
                    k = k + np.array([X1, Y1, X1, Y1], np.float32)
                kutular_bolge[b] = k
        gomulecek, gom_sahip = [], []
        bekleyen = []
        for g in acik:
            if id(g) not in degisen:
                gz = dict(g.son)
                gz["degismedi"] = True
                gz["ortulu"] = ortulu_mu([g.kutu[0] * W, g.kutu[1] * H, g.kutu[2] * W, g.kutu[3] * H], kisiler_px)
                out.append((g, gz))
                continue
            c = kirp(kare, g.kutu)
            if c is None:
                out.append((g, {"durum": "bilinmiyor"}))
                continue
            px = [g.kutu[0] * W, g.kutu[1] * H, g.kutu[2] * W, g.kutu[3] * H]
            kutular = kutular_bolge.get(g.bolge)
            if kutular is not None:
                kap, adet = kapsama(kutular, px)
            else:
                kap, adet = None, None
            gz = {"kap": kap if kap is not None else 0.0, "adet": adet, "kenar": kenar(c), "_imza": imzalar[id(g)]}
            if kutular is not None and adet:
                cx = (kutular[:, 0] + kutular[:, 2]) / 2
                cy = (kutular[:, 1] + kutular[:, 3]) / 2
                ic = kutular[(cx >= px[0]) & (cx <= px[2]) & (cy >= px[1]) & (cy <= px[3])]
                ic = ic[np.argsort(-(ic[:, 2] - ic[:, 0]) * (ic[:, 3] - ic[:, 1]))][: int(self.a["eslesme_yuz"])]
                yuzler = [kare[int(b[1]):int(b[3]), int(b[0]):int(b[2])] for b in ic]
                yuzler = [y for y in yuzler if y.size and min(y.shape[:2]) >= 8]
            else:
                yuzler = []
            if not yuzler and g.adet <= 2 and min(c.shape[:2]) >= 8:
                # Dedektör ürün bulmadı (düz kutu, koli): bir-iki yüzlük dar gözde gözün kendisi ürün kırpıntısı sayılır
                yuzler = [c]
            gz["_yuzler"] = yuzler
            gz["ortulu"] = ortulu_mu(px, kisiler_px)
            gomulecek.append(c)
            gom_sahip.append((g, "goz"))
            for y in yuzler:
                gomulecek.append(y)
                gom_sahip.append((g, "yuz"))
            bekleyen.append((g, gz))
        vler = self.m.gomme(gomulecek) if gomulecek and self.m is not None and self.m.var_mi("gomme.onnx") else None
        yuz_v: dict[int, list] = {}
        for i, (g, tur) in enumerate(gom_sahip):
            if vler is None:
                break
            if tur == "goz":
                for gg, gz in bekleyen:
                    if gg is g:
                        gz["_v"] = vler[i]
            else:
                yuz_v.setdefault(id(g), []).append(vler[i])
        for g, gz in bekleyen:
            if referans:
                gz["durum"] = "dolu"
                out.append((g, gz))
                continue
            self._eslesme(g, gz, yuz_v.get(id(g), []))
            self._karar(g, gz)
            g.imza = gz.get("_imza")
            out.append((g, gz))
        return out

    def _eslesme(self, g: _Goz, gz: dict, vler: list) -> None:
        gz["gorulen"], gz["benzerlik"], gz["beklenen_benzerlik"] = None, None, None
        kat = self.katalog
        if kat is None or not len(getattr(kat, "kimlikler", [])) or not vler:
            return
        oy: dict[str, float] = {}
        en_iyi, bek = 0.0, None
        for v, y in zip(vler, gz.get("_yuzler") or []):
            e = kat.eslestir(v, y, g.urun)
            en_iyi = max(en_iyi, e["benzerlik"])
            if e.get("beklenen_benzerlik") is not None:
                bek = e["beklenen_benzerlik"] if bek is None else max(bek, e["beklenen_benzerlik"])
            if e["urun"] is not None:
                oy[e["urun"]] = oy.get(e["urun"], 0.0) + e["benzerlik"]
        if oy:
            k = max(oy, key=oy.get)
            gz["gorulen"] = k
            from .urun import renk_ozeti

            sk = kat.urun_benzerlikleri(np.stack(vler), np.stack([renk_ozeti(y) for y in gz["_yuzler"]]))[
                :, kat.kimlikler.index(k)]
            gz["benzerlik"] = float(sk.max())
        else:
            gz["benzerlik"] = float(en_iyi) if en_iyi else None
        gz["beklenen_benzerlik"] = bek

    def _karar(self, g: _Goz, gz: dict) -> None:
        a = self.a
        if g.ref_kirp is None and self._ref_hazir:
            gz.update(durum="bilinmiyor", doluluk=None)
            return
        s_ref = None
        if gz.get("_v") is not None and g.ref_v is not None:
            s_ref = float(np.dot(gz["_v"], g.ref_v))
        gz["s_ref"] = s_ref
        if g.ref_bos:
            # Referansta da boş göz: kendi referansına benzerlik "dolu" demek değildir. Bölgedeki dolu gözlerin dokusuna
            # ve dedektörün mutlak kapsamasına göre karar verilir (gömme benzerliği kullanılmaz).
            ort = getattr(self, "_bolge_kenar", {}).get(g.bolge)
            d_kenar = min(1.5, gz["kenar"] / max(ort, 1e-3)) if ort else None
            dol = doluluk_hesapla(gz["kap"] if gz.get("adet") is not None else None, gz.get("adet"), 0.0, 0,
                                  d_kenar, None, a["ref_ayni"])
            if s_ref is not None:  # boş görünümden uzaklaştıkça dolu: dedektörün görmediği düz kutu/koli de sayılır
                dol = max(dol or 0.0, float(np.clip((a["ref_bos_fark"] - s_ref) / 0.3, 0, 1)))
            s_ref = None
        else:
            d_kenar = min(1.5, gz["kenar"] / max(g.ref_kenar, 1e-3)) if g.ref_kenar else None
            dol = doluluk_hesapla(gz["kap"] if gz.get("adet") is not None else None, gz.get("adet"), g.ref_kap,
                                  g.ref_adet, d_kenar, s_ref, a["ref_ayni"])
        if dol is None:
            gz.update(durum="bilinmiyor", doluluk=None)
            return
        gz["doluluk"] = round(float(dol), 3)
        if dol < a["bos_esik"]:
            durum = "bos"
        elif dol < a["az_esik"]:
            durum = "az"
        else:
            durum = "dolu"
        degisti = s_ref is None or s_ref < a["yanlis_ref_ust"]
        if durum != "bos" and degisti:
            # referans karesi "doğru dolu raf" kabul edilir: görünümü referansla aynı kalan göz yanlış sayılmaz
            # (katalog görseli ile göz arasındaki kurulum uyuşmazlığı yanlış alarm üretmesin)
            gor, bek = gz.get("gorulen"), gz.get("beklenen_benzerlik")
            if g.urun and gor and gor != g.urun and (bek is None or (gz.get("benzerlik") or 0) - bek >= a["yanlis_pay"]):
                durum = "yanlis"
            elif g.urun and bek is not None and bek < a["yanlis_bek_esik"] and \
                    ((s_ref is not None and s_ref < a["yanlis_bek_esik"]) or g.ref_bos) and dol >= a["az_esik"]:
                # gözde ürün var ama ne beklenen ürüne ne referansa benziyor (referansta boş gözde: beklenen ürüne
                # benzemiyor): katalogda olmayan / tanınmayan ürün
                durum = "yanlis"
            elif not g.urun and a["referans_yanlis"] and s_ref is not None and s_ref < a["referans_yanlis_esik"] \
                    and dol >= a["az_esik"]:
                durum = "yanlis"
        gz["durum"] = durum

    def _sayim(self, g: _Goz, gz: dict, t: float, sonuc: dict) -> None:
        """Kararlı yüz sayısı: son `sayim_teyit` açık gözlem aynı sayıyı verince kesinleşir."""
        adet = gz.get("adet")
        if gz.get("ortulu"):
            g.dokunma_t = t  # bir kişi göze değiyor: sayı güvenilmez (kısmen örtülü raf), sayıma girmez
            return
        if adet is None and not gz.get("degismedi"):
            return
        if gz.get("degismedi") and adet is None:
            return
        teyit = int(self.a["sayim_teyit"])
        g.adet_gecmis = (g.adet_gecmis + [adet])[-(teyit + 1):]
        yeni = g.adet_gecmis[-1]
        # Artış (geri koyma) bir gözlem daha ister: dedektörün +1 oynaması sahte "geri koydu" üretmesin. Azalış (alma)
        # sayim_teyit gözlemle kesinleşir.
        gerek = teyit + 1 if (g.adet_kararli is not None and yeni > g.adet_kararli) else teyit
        son = g.adet_gecmis[-gerek:]
        if len(son) < gerek or len(set(son)) != 1:
            return
        if g.adet_kararli is None:
            g.adet_kararli = yeni
            return
        if yeni != g.adet_kararli:
            # Yalnızca son dokunma_pencere_sn içinde bir kişinin örttüğü / değdiği / uzandığı gözdeki değişim alma ya da
            # geri koyma adayıdır; kimsenin değmediği gözde sayının oynaması dedektör gürültüsüdür (sessizce yeni sayı olur).
            # Artış (geri koyma) ayrıca belirgin olmalı: boş göze konan ürün ya da referans yüz sayısının en az çeyreği.
            # Çok yüzlü gözde +1 dedektör oynamasından ayırt edilemiyor (örnek videolarda 5->6, 7->8 sahte artışlar).
            belirgin = yeni < g.adet_kararli or g.adet_kararli == 0 or \
                yeni - g.adet_kararli >= max(1.0, self.a["artis_orani"] * max(g.ref_adet, 1))
            if t - g.dokunma_t <= self.a["dokunma_pencere_sn"] and belirgin:
                sonuc["adet_degisimleri"].append({"bolge": g.bolge, "goz": g.goz, "once": g.adet_kararli, "sonra": yeni,
                                                  "t": t, "tetik": (g.bolge, g.goz) in self._tetik})
                self._degisti = True
            g.adet_kararli = yeni

    # -- etiketler -----------------------------------------------------------------------------------------------------
    def _etiketler(self, kare: np.ndarray, t: float, sonuc: dict) -> None:
        if self.etiketci is None:
            return
        adaylar = []
        for g in self.gozler:
            if g.etiket is None or g.kapali:
                continue
            H, W = kare.shape[:2]
            px = [g.etiket[0] * W, g.etiket[1] * H, g.etiket[2] * W, g.etiket[3] * H]
            # okuma zamanı: koşu başı / göz durumu değişti (etiket_iste), etiket_araligi_sn doldu, ya da kesinleşmemiş
            # bir etiket adayı var (60 sn'de bir yeniden bakılır)
            if g.etiket_iste or g.etiket_son_t is None or t - g.etiket_son_t >= self.a["etiket_araligi_sn"] \
                    or (g.etiket_aday is not None and t - g.etiket_son_t >= 60.0):
                adaylar.append((0 if g.etiket_iste else 1, g.etiket_son_t or -1e9, g, px))
        adaylar.sort(key=lambda x: (x[0], x[1]))
        for _, _, g, _ in adaylar[: int(self.a["etiket_her_kontrol"])]:
            beklenen = g.fiyat if g.fiyat is not None else (self.katalog.fiyat(g.urun) if self.katalog else None)
            r = self.etiketci.oku(kare, g.etiket, beklenen, tolerans=self.a["fiyat_tolerans"])
            g.etiket_son_t, g.etiket_iste = t, False
            durum = r["etiket"]
            if durum == g.etiket_durum:
                g.etiket_aday, g.etiket_n = None, 0
                g.etiket_fiyat = r["fiyat"] if r["fiyat"] is not None else g.etiket_fiyat
                continue
            if durum == g.etiket_aday:
                g.etiket_n += 1
            else:
                g.etiket_aday, g.etiket_n, g.etiket_aday_t = durum, 1, t
            # uygun hemen kesinleşir (iyi haber); okunamadi ilk okumada; yok/farkli/okunamadi aksi hâlde en az
            # etiket_teyit okuma ve özelliğin sure_sn kadar süre ister (yanlış uyarıya karşı)
            if durum == "uygun" or (g.etiket_durum == "bakilmadi" and durum == "okunamadi"):
                hazir = True
            else:
                sure = {"yok": self.a["etiket_yok_sure_sn"], "farkli": self.a["fiyat_farkli_sure_sn"]}.get(durum, 0.0)
                hazir = g.etiket_n >= int(self.a["etiket_teyit"]) and t - g.etiket_aday_t >= sure
            if hazir:
                sonuc["etiket_gecisleri"].append({"bolge": g.bolge, "goz": g.goz, "once": g.etiket_durum, "sonra": durum,
                                                  "t": t, "metin": r["metin"], "fiyat": r["fiyat"], "beklenen": beklenen})
                g.etiket_durum, g.etiket_aday, g.etiket_n = durum, None, 0
                g.etiket_fiyat = r["fiyat"]
                g.etiket_metin = r["metin"]
                self._degisti = True


# --- olaylar ------------------------------------------------------------------------------------------------------------
_DURUM_KURAL = {"bos": "bos_raf", "az": "az_stok", "yanlis": "yanlis_urun"}
_ETIKET_KURAL = {"yok": "etiket_yok", "farkli": "fiyat_farkli"}
_ACIKLAMA = {"bos_raf": "Göz boş", "az_stok": "Stok azaldı", "yanlis_urun": "Yanlış ürün",
             "etiket_yok": "Fiyat etiketi yok", "fiyat_farkli": "Etiket fiyatı farklı"}


class RafOlaylari:
    """Göz/etiket geçişlerinden raf olaylarını açar ve kapatır. Çıktı Kayitci.kare'nin beklediği üç liste; olay
    sözlüklerine katalogdaki kural alanlarını (kural_ad, kategori, duzey, onem, olasilik, puan, ciddi) `zenginlestir`
    ekler (f(olay) -> olay; blok kancası `analiz_sonucu` bunu katalogla yapar).
    `gozler`: RafIzleyici ya da gozleri_al(ayar) listesi. `acik`: {kural: açık mı} (verilmeyen açık sayılır)."""

    def __init__(self, gozler, acik: dict[str, bool] | None = None, urun_adi=None, zenginlestir=None):
        self.iz = gozler if isinstance(gozler, RafIzleyici) else None
        self._gozler = None if self.iz is not None else [_Goz(g) if isinstance(g, dict) else g for g in gozler]
        self.acik = acik or {}
        self.urun_adi = urun_adi or (lambda k: k)
        self.zenginlestir = zenginlestir
        self.olaylar: dict[tuple[str, str, str], dict] = {}

    def _ac(self, kural: str, g: _Goz, t: float, zaman: str, deger=None, beklenen=None) -> dict | None:
        if not self.acik.get(kural, True):
            return None
        anahtar = (kural, g.bolge, g.goz)
        if anahtar in self.olaylar:
            return None
        o = {"kimlik": os.urandom(8).hex(), "zaman": zaman, "kural": kural, "bolge": g.bolge, "bolge_ad": g.bolge_ad,
             "goz": g.goz, "urun": g.urun, "urun_ad": self.urun_adi(g.urun) if g.urun else None, "gorev": True,
             "deger": deger, "beklenen": beklenen, "x": round((g.kutu[0] + g.kutu[2]) / 2, 4),
             "y": round((g.kutu[1] + g.kutu[3]) / 2, 4), "aciklama": _ACIKLAMA.get(kural, kural), "bitti": False,
             "sure_sn": 0.0, "_t": t}
        self.olaylar[anahtar] = o
        return o

    def _kapat(self, kural: str, g: _Goz, t: float) -> dict | None:
        o = self.olaylar.pop((kural, g.bolge, g.goz), None)
        if o is None:
            return None
        o["bitti"] = True
        o["sure_sn"] = round(max(0.0, t - o["_t"]), 1)
        return o

    def guncelle(self, sonuc: dict, t: float, zaman: str | None = None) -> dict:
        zaman = zaman or dt.datetime.now().replace(microsecond=0).isoformat()
        gozler = {(g.bolge, g.goz): g for g in (self.iz.gozler if self.iz is not None else self._gozler)}
        bas, bit = [], []
        for gc in sonuc.get("gecisler") or []:
            g = gozler.get((gc["bolge"], gc["goz"]))
            if g is None:
                continue
            k_eski, k_yeni = _DURUM_KURAL.get(gc["once"]), _DURUM_KURAL.get(gc["sonra"])
            if k_eski and k_eski != k_yeni:
                o = self._kapat(k_eski, g, t)
                if o:
                    bit.append(o)
            if k_yeni:
                deger = gc.get("doluluk") if k_yeni != "yanlis_urun" else gc.get("benzerlik")
                beklenen = g.urun if k_yeni == "yanlis_urun" else g.adet
                o = self._ac(k_yeni, g, t, zaman, deger, beklenen)
                if o is not None and k_yeni == "yanlis_urun" and gc.get("gorulen"):
                    o["aciklama"] = f"Yanlış ürün: {self.urun_adi(gc['gorulen'])}"
                if o:
                    bas.append(o)
        for gc in sonuc.get("etiket_gecisleri") or []:
            g = gozler.get((gc["bolge"], gc["goz"]))
            if g is None:
                continue
            k_eski, k_yeni = _ETIKET_KURAL.get(gc["once"]), _ETIKET_KURAL.get(gc["sonra"])
            if k_eski and k_eski != k_yeni:
                o = self._kapat(k_eski, g, t)
                if o:
                    bit.append(o)
            if k_yeni:
                o = self._ac(k_yeni, g, t, zaman, gc.get("fiyat"), gc.get("beklenen"))
                if o:
                    bas.append(o)
        suren = []
        for o in self.olaylar.values():
            o["sure_sn"] = round(max(0.0, t - o["_t"]), 1)
            if o not in bas:
                suren.append(o)
        donus = {"baslayan": bas, "biten": bit, "suren": suren}
        return {k: [self._disari(o) for o in v] for k, v in donus.items()}

    def kapat_hepsi(self, t: float) -> list[dict]:
        out = []
        for anahtar in list(self.olaylar):
            o = self.olaylar.pop(anahtar)
            o["bitti"] = True
            o["sure_sn"] = round(max(0.0, t - o["_t"]), 1)
            out.append(self._disari(o))
        return out

    def _disari(self, o: dict) -> dict:
        d = {k: v for k, v in o.items() if not k.startswith("_")}
        return self.zenginlestir(d) if self.zenginlestir else d


# =====================================================================================================================
# Blok kancaları (raf_motor.blok bunları adıyla arar: analiz, analiz_sonucu, bitir)
#
# Raf Ürün bloğu kişileri görmez; Raf Analiz görür. İki blok aynı Studio sürecinde aynı modülü kullanır: Analiz'in son
# kişi kutuları ve biten uzanmalar (tetik) modül düzeyindeki _PAYLASIM üzerinden Raf Ürün'ün bir sonraki kontrolüne
# geçer; Raf Ürün'ün kontrol sonuçları (geçişler, sayı değişimleri, kayıt) da aynı yoldan Analiz'e, kaybolmadan
# (kuyruk) geçer. Raf JSON'u yalnızca son göz durumlarını taşır (ekranda gösterim için).
# =====================================================================================================================
RAF_KODLARI = ("bos_raf", "az_stok", "yanlis_urun", "etiket_yok", "fiyat_farkli")
ESLEME_PENCERE_SN = 15.0   # uzanma bittikten sonra bu süre içinde görülen yüz sayısı değişimi o uzanmaya bağlanır
KISI_TAZE_SN = 3.0         # Analiz'den gelen kişi kutuları bu kadar eskiyse kullanılmaz
_PAYLASIM: dict[str, dict] = {}


def _paylasim(kod: str) -> dict:
    return _PAYLASIM.setdefault(kod, {"kisiler": [], "kisi_an": 0.0, "tetik": [], "bekleyen": []})


def _ozellikler(ayar: dict) -> dict:
    """{kod: katalog.ozellik_ayari(...) ya da None (kapalı)}."""
    from . import katalog

    out = {}
    for k in RAF_KODLARI:
        try:
            out[k] = katalog.ozellik_ayari(ayar, k)
        except Exception:
            out[k] = None
    return out


def analiz(st: dict, fr: np.ndarray, ayar: dict, t: float | None, veri: str):
    """Raf Ürün kancası: blok.urun her karede çağırır. Kontrol zamanı değilse birkaç mikro saniyede döner.
    Dönüş: (Raf JSON metni {"sira", "gozler": [4.3 göz kayıtları], "doluluk", "uyum", "referans"}, durum metni)."""
    import json

    from .etiket import EtiketOkuyucu
    from .raf_modeller import ETIKET_BUL, ETIKET_OKU, paylasilan
    from .urun import UrunKatalogu

    kod = str(ayar.get("kod") or "")
    pay = _paylasim(kod)
    if t is None:
        t = time.monotonic()
    oz = _ozellikler(ayar)
    ref_yol = referans_yolu(veri, kod)
    try:
        ref_m = os.path.getmtime(ref_yol)
    except OSError:
        ref_m = None
    imza_ayar = (json.dumps([ayar.get("bolgeler"), ayar.get("raf_araligi_sn"), oz, (ayar.get("ozellikler") or {}).get("raf_ayar")],
                            sort_keys=True, default=str), ref_m)
    if st.get("iz") is None or st.get("imza") != imza_ayar:
        m = paylasilan()
        from .raf_modeller import GOMME, URUN

        eksik = [a for a in (URUN, GOMME) if not m.var_mi(a)]
        if eksik and gozleri_al(ayar):
            # Modelsiz göz durumu yalnızca dokuya kalırdı: "boş/dolu" sonucu vermek yerine hata değeri (blok.urun çevirir)
            raise RuntimeError(f"model dosyası yok: {', '.join(eksik)}")
        kat = st.get("katalog") or UrunKatalogu(veri, m)
        kat.yukle()
        etiketci = None
        if (oz["etiket_yok"] or oz["fiyat_farkli"]) and m.var_mi(ETIKET_BUL) and m.var_mi(ETIKET_OKU):
            etiketci = EtiketOkuyucu(m)
        ayar2 = dict(ayar, ozellikler={k: v for k, v in oz.items() if v})
        ince = (ayar.get("ozellikler") or {}).get("raf_ayar")
        if isinstance(ince, dict):  # ince ayar (ayarlari_coz) kapalı özellik süzgecinde kaybolmasın
            ayar2["ozellikler"]["raf_ayar"] = ince
        if st.get("iz") is not None:
            pay["bekleyen"].append({"sifirla": True})  # gözler/referans değişti: açık raf olayları kapanır
        st.update(iz=RafIzleyici(ayar2, m, katalog=kat, referans=referans_oku(veri, kod), etiketci=etiketci),
                  imza=imza_ayar, katalog=kat, sira=st.get("sira", 0), son_kayit=None)
    else:
        st["katalog"].yukle()  # urunler.json değişmediyse bir dosya tarihine bakar
    iz = st["iz"]
    pay["urun_adi"] = st["katalog"].ad  # olay kaydının urun_ad alanı (Raf Analiz kancası kullanır)
    kisiler = pay["kisiler"] if time.monotonic() - pay["kisi_an"] <= KISI_TAZE_SN else []
    tetik, pay["tetik"] = pay["tetik"], []
    s = iz.guncelle(fr, t, kisiler, tetik=tetik)  # tetikler izleyicide saklanır; göz açılınca bakılır
    if s["kontrol"]:
        st["sira"] = st.get("sira", 0) + 1
        pay["bekleyen"].append(s)
        del pay["bekleyen"][:-50]
    if s["kayit"] is not None:
        st["son_kayit"] = s["kayit"]
    k = st.get("son_kayit") or {}
    gozler = k.get("gozler") or []
    say = {d: sum(1 for g in gozler if g["durum"] == d) for d in ("bos", "az", "yanlis", "kapali")}
    durum = (f"ok raf: {len(gozler)} göz, {say['bos']} boş, {say['az']} az, {say['yanlis']} yanlış"
             + (", referans geçici" if iz.referans_turu == "gecici" else "")
             + (f" · kontrol {iz.son_sure_ms:.0f} ms" if s["kontrol"] else ""))
    if not iz.gozler:
        durum = "ok raf: göz tanımlı değil"
    metin = json.dumps({"sira": st.get("sira", 0), "gozler": gozler, "doluluk": k.get("doluluk"), "uyum": k.get("uyum"),
                        "referans": k.get("referans", iz.referans_turu)}, ensure_ascii=False)
    return metin, durum


def _zaman(baglam: dict, t: float) -> str:
    bas = baglam.get("bas_zaman")
    if isinstance(bas, dt.datetime):
        return (bas + dt.timedelta(seconds=float(t))).replace(microsecond=0).isoformat()
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _zenginlestir(o: dict) -> dict:
    """Katalogdaki kural alanlarını ekler (raf_motor.olay.Olaylar ile aynı alanlar)."""
    from . import katalog

    k = katalog.KURAL.get(o["kural"]) or {}
    olas = katalog.olasilik(o.get("sure_sn") or 0.0, k.get("taban", 3))
    o.update(kural_ad=k.get("ad", o["kural"]), kategori=k.get("kategori", "raf"), duzey=k.get("duzey", "orta"),
             onem=int(k.get("onem", 2)), olasilik=olas, puan=katalog.risk(k.get("onem", 2), olas),
             ciddi=int(bool(k.get("ciddi"))), gorev=bool(k.get("gorev", True)))
    return {a: v for a, v in o.items() if v is not None or a in ("deger", "beklenen")}


def analiz_sonucu(st: dict, t: float, gozler: list, raf_veri: dict, musteri_sonuc: dict, baglam: dict) -> dict:
    """Raf Analiz kancası (kişi analizinin yeni olduğu karelerde). Dönüş: {"baslayan", "suren", "biten" (4.1 olayları),
    "kayitlar" ([4.3 "raf" kayıtları; kamera/kamera_ad blok ekler]), "isaretler" ([{"eylem": "aldi"|"birakti",
    "bolge", "goz", "t", "sure_sn"}])}."""
    kod = str(baglam.get("kod") or "")
    ayar = baglam.get("ayar") or {}
    pay = _paylasim(kod)
    pay["kisiler"] = [k for k in baglam.get("kisiler") or [] if isinstance(k, dict) and k.get("durum") != "kayip"]
    pay["kisi_an"] = time.monotonic()
    st["son_t"] = t
    uz = st.setdefault("uzanmalar", [])
    for u in musteri_sonuc.get("uzanma_biten") or []:
        if u.get("bolge"):
            pay["tetik"].append((u["bolge"], u.get("goz")))
            uz.append({"bolge": u["bolge"], "goz": u.get("goz"), "t": t, "iz": u.get("iz"),
                       "sure_sn": round(max(0.0, float(u.get("son", 0)) - float(u.get("bas", 0))), 1)})
    uz[:] = [u for u in uz if t - u["t"] <= ESLEME_PENCERE_SN and not u.get("kullanildi")]
    oz = _ozellikler(ayar)
    imza_g = repr([(g["bolge"], g["goz"], g["kutu"], g["urun"]) for g in gozleri_al(ayar)])
    out = {"baslayan": [], "suren": [], "biten": [], "kayitlar": [], "isaretler": []}
    if st.get("olaylar") is None or st.get("imza") != imza_g:
        if st.get("olaylar") is not None:
            out["biten"] += st["olaylar"].kapat_hepsi(t)
        def urun_adi(k, pay=pay):
            f = pay.get("urun_adi")
            try:
                return (f(k) if f else None) or k
            except Exception:
                return k

        st["olaylar"] = RafOlaylari(gozleri_al(ayar), acik={k: v is not None for k, v in oz.items()},
                                    urun_adi=urun_adi, zenginlestir=_zenginlestir)
        st["imza"] = imza_g
    ol = st["olaylar"]
    ol.acik = {k: v is not None for k, v in oz.items()}
    bekleyen, pay["bekleyen"] = pay["bekleyen"], []
    zaman = _zaman(baglam, t)
    for s in bekleyen:
        if s.get("sifirla"):
            out["biten"] += ol.kapat_hepsi(t)
            continue
        o = ol.guncelle(s, t, zaman)
        out["baslayan"] += o["baslayan"]
        out["biten"] += o["biten"]
        if s.get("kayit"):
            out["kayitlar"].append({**s["kayit"], "tur": "raf", "zaman": zaman})
        for a in s.get("adet_degisimleri") or []:
            aday = [u for u in uz if u["bolge"] == a["bolge"] and u.get("goz") in (None, a["goz"])
                    and not u.get("kullanildi")]
            if not aday:
                # Bileğin düştüğü göz komşu göz olabilir (iskelet noktası, kol açısı): aynı bölgedeki yakın zamanlı başka
                # bir uzanmaya bağlanır (ESLEME_PENCERE_SN içinde, her uzanma bir kez)
                aday = [u for u in uz if u["bolge"] == a["bolge"] and not u.get("kullanildi")]
            if not aday:
                continue
            u = max(aday, key=lambda x: x["t"])
            u["kullanildi"] = True
            # "iz" ve "adet" yalnızca motor içinde (toplu_alma); blok kayda yazmaz
            out["isaretler"].append({"eylem": "aldi" if a["sonra"] < a["once"] else "birakti", "bolge": a["bolge"],
                                     "goz": a["goz"], "t": t, "sure_sn": u["sure_sn"], "iz": u.get("iz"),
                                     "adet": abs(int(a["once"]) - int(a["sonra"]))})
    acik_kimlik = {o["kimlik"] for o in out["baslayan"]}
    out["suren"] = [o for o in ol.guncelle({}, t, zaman)["suren"] if o["kimlik"] not in acik_kimlik]
    return out


def bitir(st: dict) -> list[dict]:
    """Akış bitti: açık raf olaylarını kapatır (bitti: true)."""
    ol = st.get("olaylar")
    return ol.kapat_hepsi(st.get("son_t") or 0.0) if ol is not None else []
