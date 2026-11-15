"""Raf/ürün tarafının modelleri: dosya adları, ön işleme ve çözücüler TEK yerde.

Model değiştirmek (ör. lisans kararı sonrası başka bir ürün dedektörü ya da gömme modeli) yalnızca bu dosyayı ilgilendirir:
dosya adı sabitleri, giriş boyu ve `_urun_coz` / `gomme` / `metin_*` içindeki ön işleme. Diğer modüller (raf, urun,
etiket, gorev) yalnızca `Modeller` sınıfının yöntemlerini çağırır.

Modeller `model_oturumu.oturum_ac` ile açılır: klasörde model paketi varsa o, yoksa düz .onnx kullanılır.
Bloklar oturumları zaten açtıysa (`blok.modelleri_ac()` sözlüğü) `Modeller(oturumlar=...)` ile onlar kullanılır.
"""
from __future__ import annotations

import os
import threading

import cv2
import numpy as np

# --- Dosya adları (katalog.MODEL_DOSYALARI'na girecek düz adlar) -------------------------------------------------------
URUN = "urun.onnx"            # tek sınıflı ürün yüzü dedektörü (YOLO çıktısı [1, 5, N])
GOMME = "gomme.onnx"          # ürün görünümü gömmesi ([N,3,224,224] -> [N,D], L2 normalize)
ETIKET_BUL = "etiket-bul.onnx"  # metin bölgesi bulucu (PP-OCR DB)
ETIKET_OKU = "etiket-oku.onnx"  # metin satırı okuyucu (PP-OCR CTC)
ETIKET_HARF = "etiket-oku.txt"  # okuyucunun karakter listesi (düz metin, şifrelenmez)
MODEL_DOSYALARI = [URUN, GOMME, ETIKET_BUL, ETIKET_OKU]

# --- Ürün dedektörü ------------------------------------------------------------------------------------------------
URUN_BOY = 640          # giriş kenarı (model sabit 640x640)
URUN_ESIK = 0.25        # kutu skoru eşiği
URUN_IOU = 0.45         # NMS örtüşme eşiği
URUN_EN_COK = 1000      # rafta 150-250 ürün olabilir
PARCA_ORANI = 1.7       # bölge kırpıntısının uzun/kısa kenar oranı bunu aşarsa parçalara bölünür
PARCA_EN_COK = 3        # bir bölge en çok bu kadar parçada taranır (süre sınırı)

# --- Gömme --------------------------------------------------------------------------------------------------------
GOMME_BOY = 224
_ORT = np.array([0.485, 0.456, 0.406], np.float32)
_SAP = np.array([0.229, 0.224, 0.225], np.float32)
GOMME_YIGIN = 32

KLASOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modeller")


def harfleri_oku(yol: str) -> list[str]:
    """CTC sözlüğü: indeks 0 = boş (blank), 1..n = dosyadaki karakterler, n+1 = boşluk."""
    with open(yol, encoding="utf-8") as f:
        harfler = [s.rstrip("\n") for s in f]
    harfler = [h for h in harfler if h != ""]
    return ["<blank>"] + harfler + [" "]


def _secenek(thread: int | None):
    import onnxruntime as ort

    s = ort.SessionOptions()
    s.log_severity_level = 3
    s.add_session_config_entry("session.intra_op.allow_spinning", "0")
    if thread:
        s.intra_op_num_threads = int(thread)
    return s


class Modeller:
    """Raf/ürün modellerinin tembel (ilk kullanımda açılan) oturumları ve çözücüleri.

    `klasor`: model klasörü (varsayılan motor/modeller). `oturumlar`: önceden açılmış {dosya adı: oturum}.
    `thread`: onnxruntime intra_op iş parçacığı sayısı (None = varsayılan, tüm çekirdekler)."""

    def __init__(self, klasor: str | None = None, oturumlar: dict | None = None, thread: int | None = None,
                 veri: str | None = None):
        self.klasor = klasor or KLASOR
        self.thread = thread
        self.veri = veri
        self._oturumlar = dict(oturumlar or {})
        self._kilit = threading.Lock()
        self._harfler: list[str] | None = None

    # -- oturumlar ---------------------------------------------------------------------------------------------------
    def oturum(self, ad: str):
        with self._kilit:
            o = self._oturumlar.get(ad)
            if o is None:
                from .model_oturumu import oturum_ac

                yol = os.path.join(self.klasor, ad)
                o = oturum_ac(yol, self.veri, _secenek(self.thread), ["CPUExecutionProvider"], cpu_yedek=True)
                self._oturumlar[ad] = o
            return o

    def var_mi(self, ad: str) -> bool:
        if ad in self._oturumlar:
            return True
        from .katalog import model_var

        return model_var(os.path.join(self.klasor, ad))

    def kapat(self) -> None:
        for o in self._oturumlar.values():
            k = getattr(o, "kapat", None)
            if callable(k):
                k()
        self._oturumlar.clear()

    # -- ürün dedektörü ------------------------------------------------------------------------------------------------
    def urun_bul(self, goruntu: np.ndarray, parca: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """Görüntüdeki ürün yüzleri. Dönüş: (kutular [N,4] x1,y1,x2,y2 görüntü pikseli, skorlar [N]).
        Uzun/ince kırpıntılar (geniş raf) üst üste binen parçalara bölünür; sonuçlar NMS ile birleşir."""
        h, w = goruntu.shape[:2]
        if h < 8 or w < 8:
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
        parcalar = [(0, 0, w, h)]
        oran = max(w, h) / max(1, min(w, h))
        if parca and oran > PARCA_ORANI:
            n = min(PARCA_EN_COK, int(np.ceil(oran / 1.25)))
            if n > 1:
                uzun = w if w >= h else h
                boy = uzun / (n - (n - 1) * 0.12)
                adim = boy * 0.88
                parcalar = []
                for i in range(n):
                    a = int(round(i * adim))
                    b = int(round(min(uzun, a + boy)))
                    parcalar.append((a, 0, b, h) if w >= h else (0, a, w, b))
        tum_k, tum_s = [], []
        for x1, y1, x2, y2 in parcalar:
            k, s = self._urun_tek(goruntu[y1:y2, x1:x2])
            if len(k):
                k[:, [0, 2]] += x1
                k[:, [1, 3]] += y1
                tum_k.append(k)
                tum_s.append(s)
        if not tum_k:
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
        k, s = np.concatenate(tum_k), np.concatenate(tum_s)
        if len(parcalar) > 1:
            k, s = _nms(k, s, URUN_IOU)
        return k, s

    def _urun_tek(self, im: np.ndarray):
        h, w = im.shape[:2]
        r = min(URUN_BOY / h, URUN_BOY / w)
        nh, nw = max(1, round(h * r)), max(1, round(w * r))
        lb = np.full((URUN_BOY, URUN_BOY, 3), 114, np.uint8)
        dy, dx = (URUN_BOY - nh) // 2, (URUN_BOY - nw) // 2
        lb[dy:dy + nh, dx:dx + nw] = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR)
        x = np.ascontiguousarray(lb[:, :, ::-1].transpose(2, 0, 1)[None], np.float32) / 255.0
        o = self.oturum(URUN)
        out = o.run(None, {o.get_inputs()[0].name: x})[0]
        return _urun_coz(out, r, dx, dy, w, h)

    # -- gömme ---------------------------------------------------------------------------------------------------------
    def gomme(self, kirpintilar: list[np.ndarray]) -> np.ndarray:
        """BGR kırpıntılar -> [N, D] L2 normalize gömme. Kırpıntı kendi ortalama rengiyle kareye doldurulur."""
        if not kirpintilar:
            return np.zeros((0, 0), np.float32)
        o = self.oturum(GOMME)
        ad = o.get_inputs()[0].name
        out = []
        for i in range(0, len(kirpintilar), GOMME_YIGIN):
            x = np.stack([gomme_on(c) for c in kirpintilar[i:i + GOMME_YIGIN]])
            out.append(o.run(None, {ad: x})[0])
        v = np.concatenate(out).astype(np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6)

    # -- metin (fiyat etiketi) -----------------------------------------------------------------------------------------
    @property
    def harfler(self) -> list[str]:
        if self._harfler is None:
            self._harfler = harfleri_oku(os.path.join(self.klasor, ETIKET_HARF))
        return self._harfler

    def metin_bul(self, im: np.ndarray, uzun: int = 640, esik: float = 0.3, kutu_esik: float = 0.6,
                  unclip: float = 1.5) -> tuple[list[np.ndarray], float]:
        """Metin satırlarının döndürülmüş kutuları (4x2 nokta, görüntü pikseli) ve olasılık haritasının en yüksek değeri."""
        h, w = im.shape[:2]
        r = uzun / max(h, w)
        nh, nw = max(32, int(round(h * r / 32)) * 32), max(32, int(round(w * r / 32)) * 32)
        x = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR).astype(np.float32) / 255.0
        x = ((x - _ORT) / _SAP).transpose(2, 0, 1)[None].astype(np.float32)  # BGR üzerinde (Paddle düzeni)
        o = self.oturum(ETIKET_BUL)
        p = o.run(None, {o.get_inputs()[0].name: x})[0][0, 0]
        m = (p > esik).astype(np.uint8)
        cs, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        kutular = []
        for c in cs[:500]:
            if len(c) < 4:
                continue
            rect = cv2.minAreaRect(c)
            if min(rect[1]) < 3:
                continue
            x0, y0, bw, bh = cv2.boundingRect(c)
            mk = np.zeros((bh, bw), np.uint8)
            cv2.fillPoly(mk, [c - [x0, y0]], 1)
            if p[y0:y0 + bh, x0:x0 + bw][mk.astype(bool)].mean() < kutu_esik:
                continue
            (cx, cy), (rw, rh), a = rect
            d = rw * rh * unclip / max(1e-6, 2 * (rw + rh))
            rect = ((cx, cy), (rw + 2 * d, rh + 2 * d), a)
            if min(rect[1]) < 5:
                continue
            b = cv2.boxPoints(rect)
            b[:, 0] *= w / nw
            b[:, 1] *= h / nh
            kutular.append(b)
        kutular.sort(key=lambda b: (round(b[:, 1].min() / 10), b[:, 0].min()))
        return kutular, float(p.max()) if p.size else 0.0

    def metin_oku(self, kirpintilar: list[np.ndarray]) -> list[tuple[str, float]]:
        """Satır kırpıntıları -> [(metin, ortalama güven)]. Benzer genişlikteki satırlar toplu okunur."""
        if not kirpintilar:
            return []
        o = self.oturum(ETIKET_OKU)
        ad = o.get_inputs()[0].name
        harf = self.harfler
        hazir = []
        for c in kirpintilar:
            h, w = c.shape[:2]
            nw = min(1600, max(16, int(np.ceil(48 * w / max(1, h)))))
            x = cv2.resize(c, (nw, 48)).astype(np.float32) / 255.0
            hazir.append(((x - 0.5) / 0.5).transpose(2, 0, 1))
        sira = sorted(range(len(hazir)), key=lambda i: hazir[i].shape[2])
        sonuc: list[tuple[str, float]] = [("", 0.0)] * len(hazir)
        for i in range(0, len(sira), 8):
            grup = sira[i:i + 8]
            gm = max(hazir[j].shape[2] for j in grup)
            x = np.zeros((len(grup), 3, 48, gm), np.float32)
            for n, j in enumerate(grup):
                x[n, :, :, :hazir[j].shape[2]] = hazir[j]
            p = o.run(None, {ad: x})[0]
            for n, j in enumerate(grup):
                idx, sk = p[n].argmax(1), p[n].max(1)
                metin, guven, onceki = [], [], -1
                for k, v in zip(idx, sk):
                    if k != 0 and k != onceki and k < len(harf):
                        metin.append(harf[k])
                        guven.append(float(v))
                    onceki = k
                sonuc[j] = ("".join(metin), float(np.mean(guven)) if guven else 0.0)
        return sonuc


_PAYLASILAN: dict = {}


def paylasilan(thread: int | None = None) -> "Modeller":
    """Süreç içinde tek Modeller (Raf Ürün bloğu ve tek seferlik işler aynı oturumları kullanır).
    İş parçacığı sayısı ortam değişkeni RAF_URUN_THREAD ile sınırlanabilir; yoksa kişi modelleriyle aynı RAF_IS_PARCACIGI
    (boş: onnxruntime varsayılanı)."""
    if thread is None:
        try:
            thread = int(os.environ.get("RAF_URUN_THREAD") or os.environ.get("RAF_IS_PARCACIGI") or 0) or None
        except ValueError:
            thread = None
    m = _PAYLASILAN.get(thread)
    if m is None:
        m = _PAYLASILAN[thread] = Modeller(thread=thread)
    return m


def oturumlari_ver(oturumlar: dict) -> None:
    """Blok zaten açtıysa (blok.modelleri_ac) raf/ürün oturumlarını ortak Modeller'e verir: aynı model iki kez açılmaz."""
    m = paylasilan()
    for ad in MODEL_DOSYALARI:
        if ad in (oturumlar or {}):
            m._oturumlar[ad] = oturumlar[ad]


def gomme_on(c: np.ndarray) -> np.ndarray:
    h, w = c.shape[:2]
    m = max(h, w, 1)
    kare = np.empty((m, m, 3), np.uint8)
    kare[:] = c.reshape(-1, 3).mean(0) if c.size else 0
    kare[(m - h) // 2:(m - h) // 2 + h, (m - w) // 2:(m - w) // 2 + w] = c
    r = cv2.resize(kare, (GOMME_BOY, GOMME_BOY), interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(np.float32) / 255.0
    return ((r - _ORT) / _SAP).transpose(2, 0, 1).astype(np.float32)


def _urun_coz(out: np.ndarray, r: float, dx: int, dy: int, w: int, h: int):
    p = out[0].T
    s = p[:, 4:].max(1)
    k = s >= URUN_ESIK
    p, s = p[k], s[k]
    if not len(p):
        return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
    b = np.concatenate([p[:, :2] - p[:, 2:4] / 2, p[:, :2] + p[:, 2:4] / 2], 1)
    b[:, [0, 2]] -= dx
    b[:, [1, 3]] -= dy
    b /= r
    b[:, [0, 2]] = b[:, [0, 2]].clip(0, w)
    b[:, [1, 3]] = b[:, [1, 3]].clip(0, h)
    return _nms(b.astype(np.float32), s.astype(np.float32), URUN_IOU)


def _nms(b: np.ndarray, s: np.ndarray, iou: float):
    xywh = np.c_[b[:, :2], b[:, 2:] - b[:, :2]]
    ii = cv2.dnn.NMSBoxes(xywh.tolist(), s.tolist(), URUN_ESIK, iou, top_k=URUN_EN_COK)
    ii = np.array(ii, int).reshape(-1)
    return b[ii], s[ii]


def kirp(kare: np.ndarray, kutu, pay: float = 0.0) -> np.ndarray | None:
    """0-1 kutudan (x1,y1,x2,y2) piksel kırpıntı. `pay`: kutu boyutuna oranla her yöne genişletme."""
    H, W = kare.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in kutu[:4])
    dx, dy = (x2 - x1) * pay, (y2 - y1) * pay
    a, b = int(max(0, (x1 - dx) * W)), int(max(0, (y1 - dy) * H))
    c, d = int(min(W, np.ceil((x2 + dx) * W))), int(min(H, np.ceil((y2 + dy) * H)))
    if c - a < 4 or d - b < 4:
        return None
    return kare[b:d, a:c]
