"""Operasyon uyarıları (Raf Analiz içinde): kasa kuyruğu, toplu ürün alma, tıkalı koridor, dökülme, açık dolap kapağı.

Kişiye dayananlar müşteri analizinin sonucunu kullanır. Görüntüye dayananlar (koridor ve dolap) saniyede en çok bir kez,
bölgenin küçültülmüş gri görüntüsü üzerinde çalışır; kişi kutuları (kayıp izler dahil) her zaman maskelenir:
  - Koridor: uzun dönemli referans (koşu başında kişisiz örneklerin medyanı, çok yavaş güncellenir) + kısa dönemli ortalama.
    Kısa dönemli görüntünün referanstan farklı ve kendi içinde durağan olduğu pikseller "durağan değişim"dir.
    tıkalı koridor: durağan değişim koridorun alan_orani'ndan fazlasını kaplıyor.
    dökülme: durağan değişimin içinde küçük (en_az_alan..en_cok_alan), düz (az desenli) ya da referanstan parlak bir leke.
    Işık değişimi için kazanç düzeltmesi yapılır. Dökülmede son 15 sn içinde bir kişinin kapladığı pikseller sayılmaz (kişinin
    oynattığı sandalye, oturan kişinin çevresi). Zayıf yöntemdir: gölge, taşınıp bırakılan masa/sandalye da durağan değişimdir.
  - Dolap: kapalı referans `<VERI>/ayar/_referans_<kod>.jpg` (raf referans karesi; o anda kapakların kapalı olduğu
    varsayılır) varsa ondan, yoksa koşunun başında önünde kimse yokken alınan örneklerden öğrenilir. Önünde kimse yokken
    görüntü referanstan fark_esik oranından fazla farklıysa açık sayılır.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import cv2
import numpy as np

from . import katalog, olcu
from .olay import Olaylar

ORNEK_ARALIGI = 0.5      # sn: görüntüye dayalı denetimler en çok bu sıklıkla (1 sn'de yeni leke ~5 sn'de görülüyordu)
OGRENME_ORNEK = 8        # referans için gereken kişisiz örnek sayısı
EN_GENIS = 200           # bölge kırpıntısı en çok bu genişliğe küçültülür
FARK = 22.0              # gri düzey farkı: bunun üstü "değişmiş"
KISI_YAKIN_SN = 15.0     # dökülme: son bu kadar saniyede bir kişinin kapladığı pikseller leke sayılmaz (oynatılan sandalye,
                         # oturan kişinin çevresi). Tıkalı koridorda uygulanmaz (geçen kişiler engeli sürekli örterdi).
UZUN_ALFA = 1 / 1800.0   # uzun dönemli referansın örnek başına güncelleme oranı (yarım saatte bir yenilenir)
KISA_ALFA = 0.5          # kısa dönemli ortalama: yeni durağan değişim ~3 örnekte (1,5 sn) yerleşir


class _Kirpinti:
    """Bölgenin sınır kutusu, küçültme oranı ve maske."""

    def __init__(self, poly: np.ndarray, W: int, H: int):
        x1, y1 = np.floor(poly.min(0)).astype(int)
        x2, y2 = np.ceil(poly.max(0)).astype(int)
        self.x1, self.y1 = max(0, x1), max(0, y1)
        self.x2, self.y2 = min(W, max(x2, self.x1 + 2)), min(H, max(y2, self.y1 + 2))
        self.o = min(1.0, EN_GENIS / max(1, self.x2 - self.x1))
        self.w, self.h = max(2, int(round((self.x2 - self.x1) * self.o))), max(2, int(round((self.y2 - self.y1) * self.o)))
        m = np.zeros((self.h, self.w), np.uint8)
        cv2.fillPoly(m, [np.round((poly - [self.x1, self.y1]) * self.o).astype(np.int32)], 1)
        self.maske = m.astype(bool)
        self.alan = max(1, int(self.maske.sum()))

    def gri(self, fr: np.ndarray) -> np.ndarray:
        """Küçültülmüş renkli kırpıntı (float32, H×W×3). Farklar kanalların en büyüğüyle ölçülür: zeminle aynı parlaklıkta
        ama farklı renkte bir koli de görülsün."""
        k = fr[self.y1:self.y2, self.x1:self.x2]
        return cv2.GaussianBlur(cv2.resize(k, (self.w, self.h), interpolation=cv2.INTER_AREA), (3, 3), 0).astype(np.float32)

    def kisi_maskesi(self, kutular, pay: float = 0.1) -> np.ndarray:
        m = np.zeros((self.h, self.w), bool)
        for b in kutular:
            x1, y1, x2, y2 = (float(v) for v in b[:4])
            w, h = x2 - x1, y2 - y1
            a1 = int(max(0, (x1 - pay * w - self.x1) * self.o))
            b1 = int(max(0, (y1 - pay * h - self.y1) * self.o))
            a2 = int(min(self.w, (x2 + pay * w - self.x1) * self.o + 1))
            b2 = int(min(self.h, (y2 + pay * h - self.y1) * self.o + 1))
            if a2 > a1 and b2 > b1:
                m[b1:b2, a1:a2] = True
        return m


def _kazanc(cur: np.ndarray, ref: np.ndarray, m: np.ndarray) -> float:
    if m.sum() < 20:
        return 1.0
    r = np.median(ref[m]) + 1.0
    return float(np.clip((np.median(cur[m]) + 1.0) / r, 0.5, 2.0))


def _fark(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.abs(a - b).max(2)


def _ref_kisileri(yol: str, W: int, H: int) -> list[list[float]]:
    """Referans karesinin yanındaki kişi kutuları (motorun temiz_kare.json'u, 0-1) -> piksel. Dosya yoksa boş."""
    try:
        with open(yol, encoding="utf-8") as f:
            veri = json.load(f)
        return [[float(b[0]) * W, float(b[1]) * H, float(b[2]) * W, float(b[3]) * H] for b in veri.get("kisiler") or []]
    except (OSError, ValueError, TypeError, IndexError, AttributeError):
        return []


class Koridor:
    """`referans`: kameranın kayıtlı referans karesi (koridor boşken; yoksa koşu başında öğrenilir). `ref_kisiler`: o
    karedeki kişi kutuları (piksel); altları "bilinmiyor" sayılır ve kişisiz görüldükleri ilk iki örnekte öğrenilir."""

    def __init__(self, bolge: dict, W: int, H: int, referans: np.ndarray | None = None, ref_kisiler=(),
                 kisi_yakin_sn: float = KISI_YAKIN_SN):
        self.b = bolge
        self.k = _Kirpinti(bolge["poly"], W, H)
        self.ornekler: list[tuple[np.ndarray, np.ndarray]] = []
        self.uzun = None
        self.kisa = None
        self.onceki = None
        self.durgun = np.zeros((self.k.h, self.k.w), bool)
        self.durgun_leke = self.durgun
        self.kisi_ani = np.full((self.k.h, self.k.w), -1e9, np.float32)
        self.kisi_yakin_sn = float(kisi_yakin_sn)
        self.bilinmeyen = np.zeros((self.k.h, self.k.w), bool)
        self.serbest_n = np.zeros((self.k.h, self.k.w), np.int16)
        self.kaynak = "gecici"
        if referans is not None and referans.shape[:2] == (H, W):
            self.uzun = self.k.gri(referans)
            self.kisa = self.uzun.copy()
            self.bilinmeyen = self.k.kisi_maskesi(ref_kisiler, 0.15) & self.k.maske
            self.kaynak = "kayitli"

    def _bilinmeyeni_ogren(self, g: np.ndarray, kisi: np.ndarray) -> None:
        """Referans karesinde kişinin altında kalan pikseller: iki örnek üst üste kişisiz görülünce referansa girer."""
        if not self.bilinmeyen.any():
            return
        serbest = self.bilinmeyen & ~kisi
        self.serbest_n = np.where(serbest, self.serbest_n + 1, 0).astype(np.int16)
        ogren = self.bilinmeyen & (self.serbest_n >= 2)
        if ogren.any():
            self.uzun[ogren] = g[ogren]
            self.kisa[ogren] = g[ogren]
            self.bilinmeyen &= ~ogren

    def ornek(self, fr: np.ndarray, kutular, t: float = 0.0) -> None:
        g = self.k.gri(fr)
        kisi = self.k.kisi_maskesi(kutular)
        self.kisi_ani[kisi] = t
        if self.uzun is None:
            self.ornekler.append((g, kisi))
            serbest = np.stack([~m for _, m in self.ornekler]).sum(0)
            if len(self.ornekler) >= OGRENME_ORNEK and (serbest[self.k.maske] >= 3).mean() > 0.97 or len(self.ornekler) >= 60:
                yig = np.stack([np.where(m[..., None], np.nan, x) for x, m in self.ornekler])
                with np.errstate(all="ignore"):
                    med = np.nanmedian(yig, 0)
                self.uzun = np.where(np.isnan(med), g, med).astype(np.float32)
                self.kisa = self.uzun.copy()
                self.ornekler = []
            return
        m = self.k.maske & ~kisi & ~self.bilinmeyen
        g = g / _kazanc(g, self.uzun, m)
        self._bilinmeyeni_ogren(g, kisi)
        self.kisa = np.where(kisi[..., None], self.kisa, (1 - KISA_ALFA) * self.kisa + KISA_ALFA * g)
        durgun_kisa = _fark(g, self.kisa) < FARK
        degisik = _fark(self.kisa, self.uzun) > FARK
        d = degisik & durgun_kisa & self.k.maske & ~kisi & ~self.bilinmeyen
        d = cv2.morphologyEx(d.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
        self.durgun = d
        self.durgun_leke = d & (t - self.kisi_ani > self.kisi_yakin_sn)
        self.uzun = np.where((kisi | d)[..., None], self.uzun, (1 - UZUN_ALFA) * self.uzun + UZUN_ALFA * g)
        self.son_gri = g

    def hazir(self) -> bool:
        return self.uzun is not None

    def tikali(self) -> tuple[float, tuple[float, float] | None]:
        """Durağan değişimin bölge alanına oranı ve ağırlık merkezi (kare pikseli)."""
        oran = float(self.durgun.sum()) / self.k.alan
        if not self.durgun.any():
            return oran, None
        ys, xs = np.nonzero(self.durgun)
        return oran, (self.k.x1 + xs.mean() / self.k.o, self.k.y1 + ys.mean() / self.k.o)

    def lekeler(self, en_az: float, en_cok: float) -> list[dict]:
        """Durağan değişim içinde düz ya da parlak, küçük lekeler."""
        if not self.durgun_leke.any():
            return []
        # yakın parçalar birleştirilerek etiketlenir: bırakılan bir koli/palet birkaç küçük parça hâlinde görünüp "leke"
        # sayılmasın (birleşince en_cok_alan'ı aşar); dökülme tek parça kalır
        birlesik = cv2.morphologyEx(self.durgun_leke.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        n, et, ist, mer = cv2.connectedComponentsWithStats(birlesik, 8)
        gri = cv2.cvtColor(self.son_gri, cv2.COLOR_BGR2GRAY)
        gri_ref = cv2.cvtColor(self.uzun, cv2.COLOR_BGR2GRAY)
        lap = np.abs(cv2.Laplacian(gri, cv2.CV_32F))
        lap_ref = np.abs(cv2.Laplacian(gri_ref, cv2.CV_32F))
        out = []
        for i in range(1, n):
            alan = ist[i, cv2.CC_STAT_AREA] / self.k.alan
            if not en_az <= alan <= en_cok:
                continue
            m = et == i
            duz = lap[m].mean() <= max(4.0, 0.8 * lap_ref[m].mean())
            parlak = (gri[m].mean() - gri_ref[m].mean()) > 25
            if duz or parlak:
                out.append({"alan": float(alan), "xy": (self.k.x1 + mer[i][0] / self.k.o, self.k.y1 + mer[i][1] / self.k.o),
                            "neden": "parlak" if parlak else "düz"})
        return out


class Dolap:
    def __init__(self, bolge: dict, W: int, H: int, referans: np.ndarray | None):
        self.b = bolge
        self.k = _Kirpinti(bolge["poly"], W, H)
        self.ref = self.k.gri(referans) if referans is not None and referans.shape[:2] == (H, W) else None
        self.kaynak = "kayitli" if self.ref is not None else "gecici"
        self.ornekler: list[np.ndarray] = []
        self.fark = 0.0

    def ornek(self, fr: np.ndarray, kutular) -> bool | None:
        """Önünde kimse yokken açık mı (True/False); kişi varsa ya da referans öğrenilmediyse None."""
        if any(olcu.kutu_bolge_ortusur(self.b["poly"], b, 0.15) for b in kutular):
            return None
        g = self.k.gri(fr)
        if self.ref is None:
            self.ornekler.append(g)
            if len(self.ornekler) >= OGRENME_ORNEK:
                self.ref = np.median(np.stack(self.ornekler), 0).astype(np.float32)
                self.ornekler = []
            return None
        m = self.k.maske
        g = g / _kazanc(g, self.ref, m)
        self.fark = float((_fark(g, self.ref)[m] > FARK).mean())
        return self.fark


class Operasyon:
    def __init__(self, bolgeler: list[dict], ayar: dict, W: int, H: int, bas_zaman: dt.datetime, referans_yolu: str | None = None):
        self.W, self.H = W, H
        self.oz = {k: katalog.ozellik_ayari(ayar, k) for k in ("kasa_kuyrugu", "toplu_alma", "tikali_koridor", "dokulme", "dolap_acik")}
        self.bolgeler = {b["kimlik"]: b for b in bolgeler}
        self.yon = {k: Olaylar(k, v, bas_zaman, W, H, bosluk={"kasa_kuyrugu": 10.0}.get(k, 5.0))
                    for k, v in self.oz.items() if v is not None}
        ref, ref_kisiler = None, []
        if referans_yolu and os.path.isfile(referans_yolu):
            ref = cv2.imread(referans_yolu, cv2.IMREAD_COLOR)
            ref_kisiler = _ref_kisileri(os.path.splitext(referans_yolu)[0] + ".json", W, H)
        yakin = (self.oz["dokulme"] or {}).get("kisi_sn", KISI_YAKIN_SN)
        self.koridorlar = [Koridor(b, W, H, ref, ref_kisiler, yakin) for b in bolgeler
                           if b["tur"] == "koridor" and b.get("poly") is not None] \
            if (self.oz["tikali_koridor"] or self.oz["dokulme"]) else []
        self.dolaplar = [Dolap(b, W, H, ref) for b in bolgeler if b["tur"] == "dolap" and b.get("poly") is not None] \
            if self.oz["dolap_acik"] else []
        self.son_ornek = -1e9
        self.aktif_son: dict = {}   # görüntüye dayalı özelliklerin son örnekteki durumu (örnek arasında aynen sürer)

    @staticmethod
    def _orta(b: dict) -> tuple[float, float]:
        p = b["poly"] if b.get("poly") is not None else b["cizgi"]
        return float(p[:, 0].mean()), float(p[:, 1].mean())

    def adim(self, t: float, fr: np.ndarray, kisiler: list[dict], musteri: dict) -> dict:
        """Dönüş: {"baslayan", "suren", "biten", "vurgu": [{"b": kutu, "etiket": ad}]}"""
        aktif: dict[str, dict] = {k: {} for k in self.yon}
        if "kasa_kuyrugu" in self.yon:
            for bid, n in musteri.get("kuyruk", {}).items():
                b = self.bolgeler[bid]
                esik = int(b.get("esik") or self.oz["kasa_kuyrugu"]["esik"])
                if n >= esik:
                    aktif["kasa_kuyrugu"][bid] = {"bolge": b, "deger": n, "beklenen": esik, "xy": self._orta(b),
                                                  "aciklama": f"{b['ad']}: {n} kişi bekliyor (eşik {esik})."}
        if "toplu_alma" in self.yon:
            o = self.oz["toplu_alma"]
            # Gözü tanımlı rafta sayı raf tarafının doğruladığı alınan ürün adedidir (göz yüz sayısı düşüşü; bir uzanmada
            # birden çok ürün alınabilir). Gözü olmayan rafta göz sayımı yoktur: uzanma sayısı kullanılır.
            sayimli = {bid for bid, b in self.bolgeler.items() if b.get("tur") == "raf" and b.get("gozler")}
            sayilar: dict = {}
            for iz, gecmis in musteri.get("uzanma_gecmis", {}).items():
                for tt, bid in gecmis:
                    if bid not in sayimli and t - tt <= o["pencere_sn"]:
                        sayilar[(iz, bid)] = sayilar.get((iz, bid), 0) + 1
            for iz, gecmis in (musteri.get("alma_gecmis") or {}).items():
                for tt, bid, adet in gecmis:
                    if bid in sayimli and t - tt <= o["pencere_sn"]:
                        sayilar[(iz, bid)] = sayilar.get((iz, bid), 0) + adet
            for (iz, bid), n in sayilar.items():
                if n >= o["uzanma_sayi"] and bid in self.bolgeler:
                    b = self.bolgeler[bid]
                    ne = "ürün aldı" if bid in sayimli else "kez uzandı"
                    aktif["toplu_alma"][(iz, bid)] = {"bolge": b, "deger": n, "xy": self._orta(b),
                                                      "aciklama": f"{b['ad']}: bir kişi {int(o['pencere_sn'])} sn içinde {n} {ne}."}
        kutular = [k["b"] for k in kisiler]
        if t - self.son_ornek >= ORNEK_ARALIGI and (self.koridorlar or self.dolaplar):
            self.son_ornek = t
            yeni: dict = {}
            for kr in self.koridorlar:
                kr.ornek(fr, kutular, t)
                if not kr.hazir():
                    continue
                bid = kr.b["kimlik"]
                if self.oz["tikali_koridor"]:
                    oran, xy = kr.tikali()
                    if oran >= self.oz["tikali_koridor"]["alan_orani"] and xy is not None:
                        yeni[("tikali_koridor", bid)] = {"bolge": kr.b, "deger": round(oran, 3), "xy": xy,
                                                         "aciklama": f"{kr.b['ad']}: koridorun %{round(100 * oran)} kadarında durağan engel."}
                if self.oz["dokulme"]:
                    for i, l in enumerate(kr.lekeler(self.oz["dokulme"]["en_az_alan"], self.oz["dokulme"]["en_cok_alan"])[:3]):
                        yeni[("dokulme", (bid, i))] = {"bolge": kr.b, "deger": round(l["alan"], 4), "xy": l["xy"],
                                                       "aciklama": f"{kr.b['ad']}: zeminde {l['neden']} yeni bir leke."}
            for d in self.dolaplar:
                fark = d.ornek(fr, kutular)
                bid = d.b["kimlik"]
                if fark is None:  # önünde kişi var ya da referans öğreniliyor: önceki durum sürer
                    if ("dolap_acik", bid) in self.aktif_son:
                        yeni[("dolap_acik", bid)] = self.aktif_son[("dolap_acik", bid)]
                elif fark >= self.oz["dolap_acik"]["fark_esik"]:
                    yeni[("dolap_acik", bid)] = {"bolge": d.b, "deger": round(fark, 3), "xy": self._orta(d.b),
                                                 "aciklama": f"{d.b['ad']}: kapak açık görünüyor (kapalı hâlinden %{round(100 * fark)} farklı)."}
            self.aktif_son = yeni
        for (kod, anahtar), v in self.aktif_son.items():
            if kod in aktif:
                aktif[kod][anahtar] = v
        out = {"baslayan": [], "suren": [], "biten": [], "vurgu": []}
        for kod, y in self.yon.items():
            b, s, e = y.guncelle(t, aktif[kod])
            out["baslayan"] += b
            out["suren"] += s
            out["biten"] += e
            for a in y.acik():
                if a["bilgi"].get("bolge"):
                    out["vurgu"].append({"bolge": a["bilgi"]["bolge"]["kimlik"], "etiket": katalog.KURAL[kod]["ad"]})
        return out

    def dolap_referansi(self) -> dict:
        return {d.b["kimlik"]: d.kaynak for d in self.dolaplar}

    def bitir(self) -> list[dict]:
        out = []
        for y in self.yon.values():
            out += y.bitir()
        return out
