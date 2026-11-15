"""Ürün kataloğu gömmeleri ve eşleme.

Katalog (`<VERI>/urunler/urunler.json`, görseller `<VERI>/urunler/gorsel/`) paneli yazar. Motor her görselin gömmesini
ve renk özetini hesaplar, `<VERI>/urunler/gomme-onbellek.npz` içinde dosya içeriğinin SHA-1 özetine göre saklar: yalnızca
yeni ya da değişmiş görseller yeniden hesaplanır. Önbellek gömme modelinin kimliğini de tutar; model değişirse baştan
kurulur. Panel bu dosyaya dokunmaz.

Eşleme puanı = (1 - RENK_AGIRLIK) x gömme kosinüsü + RENK_AGIRLIK x HSV renk histogramı kosinüsü (ürün başına,
görsellerinin en yükseği). Aynı markanın çeşitleri (aynı ambalaj, farklı renk/tat) gömmede çok yakın; renk bunları
belirgin ayırıyor (egitim/dene_urun.py: 102 sorguda doğru 47 -> 71). Ürün yalnızca puan >= ESIK ve ikinciye göre
pay >= PAY ise verilir; yoksa `urun` None döner (asla tahmin edilmez).
İkinci aşama (SIFT anahtar nokta doğrulaması) yazılıdır ama varsayılan KAPALI: test verisinde doğruları da boşa
çevirdiği için yardımcı olmadı (teslim notu). `UrunKatalogu(..., ikinci_asama=True)` ile açılır.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import threading

import cv2
import numpy as np

from .raf_modeller import GOMME

ESIK = 0.65          # bu puanın altında ürün verilmez
PAY = 0.05           # en iyi ürün ikinciden en az bu kadar yüksek puanlı olmalı
RENK_AGIRLIK = 0.3   # puandaki renk payı
YAKIN = 0.08         # (ikinci aşama açıksa) en iyi iki aday bu kadar yakınsa SIFT denenir
SIFT_EN_AZ = 12      # ikinci aşamada kazanan için en az RANSAC inlier sayısı
SIFT_KAT = 1.6       # kazananın inlier sayısı ikincinin en az bu katı olmalı
SIFT_BOY = 256       # SIFT için kırpıntının uzun kenarı


def renk_ozeti(c: np.ndarray) -> np.ndarray:
    """HSV ton x doygunluk (18 x 8) histogramı, L2 normalize."""
    h = cv2.calcHist([cv2.cvtColor(c, cv2.COLOR_BGR2HSV)], [0, 1], None, [18, 8], [0, 180, 0, 256]).ravel()
    return (h / max(1e-6, float(np.linalg.norm(h)))).astype(np.float32)


def _ozet(yol: str) -> str:
    h = hashlib.sha1()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def _imread(yol: str):
    veri = np.fromfile(yol, np.uint8)  # Türkçe karakterli yollar için
    return cv2.imdecode(veri, cv2.IMREAD_COLOR) if veri.size else None


class UrunKatalogu:
    """`veri`: panelin veri klasörü. `modeller`: raf_modeller.Modeller. `ikinci_asama`: benzer çeşitler için SIFT."""

    def __init__(self, veri: str, modeller, ikinci_asama: bool = False):
        self.veri, self.m, self.ikinci_asama = veri, modeller, ikinci_asama
        self.klasor = os.path.join(veri, "urunler")
        self.urunler: dict[str, dict] = {}
        self.kimlikler: list[str] = []
        self.G = np.zeros((0, 0), np.float32)   # [M, D] görsel gömmeleri
        self.GR = np.zeros((0, 144), np.float32)  # [M, 144] görsel renk özetleri
        self.sahip = np.zeros(0, int)          # [M] görselin ürün sırası (kimlikler içinde)
        self.yollar: list[str] = []
        self._degisim = None
        self._sift: dict[int, tuple] = {}
        self._kilit = threading.Lock()
        self.son_yukleme: dict = {}

    # -- yükleme -------------------------------------------------------------------------------------------------------
    def _json_yolu(self) -> str:
        return os.path.join(self.klasor, "urunler.json")

    def degisti_mi(self) -> bool:
        try:
            return os.path.getmtime(self._json_yolu()) != self._degisim
        except OSError:
            return self._degisim is not None

    def yukle(self, zorla: bool = False) -> dict:
        """Kataloğu okur ve gömmeleri hazırlar. Dönüş: {"urun", "gorsel", "hesaplanan", "onbellek", "eksik"}.
        urunler.json değişmediyse (mtime) hiçbir şey yapmaz; her karede çağrılabilir."""
        with self._kilit:
            if not zorla and not self.degisti_mi() and self.son_yukleme:
                return self.son_yukleme
            try:
                with open(self._json_yolu(), encoding="utf-8") as f:
                    liste = json.load(f)
                degisim = os.path.getmtime(self._json_yolu())
            except (OSError, ValueError):
                liste, degisim = [], None
            urunler, yollar, sahip, kimlikler = {}, [], [], []
            eksik = 0
            for u in liste if isinstance(liste, list) else []:
                k = str(u.get("kimlik") or "")
                if not k:
                    continue
                urunler[k] = {"ad": u.get("ad") or k, "fiyat": u.get("fiyat")}
                for g in u.get("gorseller") or []:
                    yol = os.path.join(self.klasor, "gorsel", os.path.basename(str(g)))
                    if os.path.isfile(yol):
                        if k not in kimlikler:
                            kimlikler.append(k)
                        yollar.append(yol)
                        sahip.append(kimlikler.index(k))
                    else:
                        eksik += 1
            G, GR, gecerli, hesaplanan, onbellekten = self._gommeler(yollar)
            self.urunler, self.kimlikler = urunler, kimlikler
            self.yollar = [y for y, ok in zip(yollar, gecerli) if ok]
            self.G, self.GR = G, GR
            self.sahip = np.array([s for s, ok in zip(sahip, gecerli) if ok], int)
            self._degisim = degisim
            self._sift.clear()
            self.son_yukleme = {"urun": len(urunler), "gorsel": len(self.yollar), "hesaplanan": hesaplanan,
                                "onbellek": onbellekten, "eksik": eksik + sum(1 for ok in gecerli if not ok)}
            return self.son_yukleme

    def _model_kimligi(self) -> str:
        yol = os.path.join(self.m.klasor, GOMME)
        for y in (yol, yol + ".isgm"):
            try:
                return f"{GOMME}:{os.path.getsize(y)}"
            except OSError:
                continue
        return GOMME

    def _gommeler(self, yollar: list[str]):
        onb_yol = os.path.join(self.klasor, "gomme-onbellek.npz")
        model = self._model_kimligi()
        eski: dict[str, tuple] = {}
        try:
            with np.load(onb_yol, allow_pickle=False) as z:
                if str(z["model"]) == model:
                    eski = {str(o): (v, r) for o, v, r in zip(z["ozet"], z["v"], z["r"])}
        except (OSError, KeyError, ValueError):
            pass
        ozetler = [_ozet(y) for y in yollar]
        yeni_i = [i for i, o in enumerate(dict.fromkeys(ozetler)) if o not in eski]
        tekil = list(dict.fromkeys(ozetler))
        yeni: dict[str, tuple] = {}
        if yeni_i:
            ilk_yol = {o: yollar[ozetler.index(o)] for o in tekil}
            kirp, adlar = [], []
            for i in yeni_i:
                o = tekil[i]
                im = _imread(ilk_yol[o])
                if im is not None and min(im.shape[:2]) >= 8:
                    kirp.append(im)
                    adlar.append(o)
            if kirp:
                v = self.m.gomme(kirp)
                for o, vv, c in zip(adlar, v, kirp):
                    yeni[o] = (vv, renk_ozeti(c))
        tum = {**eski, **yeni}
        D = next((v.shape[0] for v, _ in tum.values()), 0)
        gecerli = [o in tum for o in ozetler]
        G = np.stack([tum[o][0] for o in ozetler if o in tum]) if any(gecerli) else np.zeros((0, D), np.float32)
        GR = np.stack([tum[o][1] for o in ozetler if o in tum]) if any(gecerli) else np.zeros((0, 144), np.float32)
        if yeni or set(eski) - set(ozetler):
            sakla = {o: tum[o] for o in tekil if o in tum}
            os.makedirs(self.klasor, exist_ok=True)
            tmp = onb_yol + ".tmp"
            buf = io.BytesIO()
            np.savez(buf, model=np.array(model), ozet=np.array(list(sakla), dtype="U40"),
                     v=np.stack([a for a, _ in sakla.values()]) if sakla else np.zeros((0, D), np.float32),
                     r=np.stack([b for _, b in sakla.values()]) if sakla else np.zeros((0, 144), np.float32))
            with open(tmp, "wb") as f:
                f.write(buf.getvalue())
            os.replace(tmp, onb_yol)
        return G.astype(np.float32), GR.astype(np.float32), gecerli, len(yeni), len(ozetler) - len(
            [o for o in ozetler if o in yeni])

    # -- eşleme --------------------------------------------------------------------------------------------------------
    def urun_benzerlikleri(self, v: np.ndarray, renkler: np.ndarray | None = None) -> np.ndarray:
        """[N, D] gömmeler (+ [N, 144] renk özetleri) -> [N, P] her ürüne en yüksek puan (P = len(kimlikler)).
        Renk verilmezse yalnız gömme kosinüsü."""
        P = len(self.kimlikler)
        if not len(v) or not P or not self.G.size:
            return np.zeros((len(v), P), np.float32)
        s = v @ self.G.T
        if renkler is not None:
            s = (1 - RENK_AGIRLIK) * s + RENK_AGIRLIK * (renkler @ self.GR.T)
        out = np.full((len(v), P), -1.0, np.float32)
        sahip = self.sahip
        if len(sahip) and np.all(sahip[:-1] <= sahip[1:]) and sahip[0] >= 0:
            # görseller ürün sırasıyla dizili (yukle böyle kurar): ürün başına en yüksek tek seferde
            urun, bas = np.unique(sahip, return_index=True)
            out[:, urun] = np.maximum.reduceat(s, bas, axis=1)
            return out
        for p in range(P):
            m = sahip == p
            if m.any():
                out[:, p] = s[:, m].max(1)
        return out

    def eslestir(self, v: np.ndarray, kirpinti: np.ndarray | None = None, beklenen: str | None = None) -> dict:
        """Tek kırpıntının gömmesi (+ kırpıntının kendisi: renk ve ikinci aşama için) ->
        {"urun": kimlik | None, "benzerlik", "aday", "ikinci", "ikinci_benzerlik", "beklenen_benzerlik", "asama"}.
        `benzerlik`: en iyi adayın puanı (urun None olsa da). `aday`: en iyi aday (yalnız bilgi; ürün iddiası değil)."""
        renk = renk_ozeti(kirpinti)[None] if kirpinti is not None and kirpinti.size else None
        s = self.urun_benzerlikleri(v[None], renk)[0] if len(self.kimlikler) else np.zeros(0)
        bek = float(s[self.kimlikler.index(beklenen)]) if beklenen in self.kimlikler else None
        if not len(s):
            return {"urun": None, "benzerlik": 0.0, "aday": None, "ikinci": None, "ikinci_benzerlik": 0.0,
                    "beklenen_benzerlik": bek, "asama": "yok"}
        sira = np.argsort(-s)
        b1 = float(s[sira[0]])
        b2 = float(s[sira[1]]) if len(sira) > 1 else -1.0
        k1 = self.kimlikler[sira[0]]
        k2 = self.kimlikler[sira[1]] if len(sira) > 1 else None
        sonuc = {"urun": None, "benzerlik": round(b1, 4), "aday": k1, "ikinci": k2, "ikinci_benzerlik": round(b2, 4),
                 "beklenen_benzerlik": None if bek is None else round(bek, 4), "asama": "gomme"}
        if b1 < ESIK:
            return sonuc
        if k2 is None or b1 - b2 >= YAKIN:
            sonuc["urun"] = k1
            return sonuc
        if self.ikinci_asama and kirpinti is not None:
            i1, i2 = self._sift_inlier(kirpinti, k1), self._sift_inlier(kirpinti, k2)
            sonuc.update(asama="sift", inlier=[i1, i2])
            if i1 >= SIFT_EN_AZ and i1 >= SIFT_KAT * max(i2, 1):
                sonuc["urun"] = k1
            elif i2 >= SIFT_EN_AZ and i2 >= SIFT_KAT * max(i1, 1):
                sonuc["urun"] = k2
                sonuc["benzerlik"] = round(b2, 4)
            return sonuc
        if b1 - b2 >= PAY:
            sonuc["urun"] = k1
        return sonuc

    # -- ikinci aşama: SIFT ---------------------------------------------------------------------------------------------
    def _sift_oz(self, im: np.ndarray):
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        r = SIFT_BOY / max(g.shape)
        g = cv2.resize(g, (max(8, int(g.shape[1] * r)), max(8, int(g.shape[0] * r))), interpolation=cv2.INTER_AREA)
        sift = cv2.SIFT_create(nfeatures=500)
        return sift.detectAndCompute(g, None)

    def _sift_inlier(self, kirpinti: np.ndarray, kimlik: str) -> int:
        kq, dq = self._sift_oz(kirpinti)
        if dq is None or len(kq) < 8:
            return 0
        en = 0
        p = self.kimlikler.index(kimlik)
        for i in np.where(self.sahip == p)[0]:
            if i not in self._sift:
                im = _imread(self.yollar[i])
                self._sift[i] = self._sift_oz(im) if im is not None else ([], None)
            kr, dr = self._sift[i]
            if dr is None or len(kr) < 8:
                continue
            esl = cv2.BFMatcher(cv2.NORM_L2).knnMatch(dq, dr, k=2)
            iyi = [e[0] for e in esl if len(e) == 2 and e[0].distance < 0.75 * e[1].distance]
            if len(iyi) < 8:
                continue
            a = np.float32([kq[e.queryIdx].pt for e in iyi])
            b = np.float32([kr[e.trainIdx].pt for e in iyi])
            _, mask = cv2.findHomography(a, b, cv2.RANSAC, 5.0)
            if mask is not None:
                en = max(en, int(mask.sum()))
        return en

    def ad(self, kimlik: str | None) -> str | None:
        return None if kimlik is None else (self.urunler.get(kimlik) or {}).get("ad", kimlik)

    def fiyat(self, kimlik: str | None):
        return None if kimlik is None else (self.urunler.get(kimlik) or {}).get("fiyat")
