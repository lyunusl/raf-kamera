"""Kişi analizi (Raf Kişi bloğu): tespit, takip, yukarıdan aşağı iskelet, baş kutusu ve gövde özellikleri.

Yalnızca numpy, OpenCV ve onnxruntime (işlemci) kullanır. Modeller (düz adlar, katalog.MODEL_DOSYALARI):
  kisi.onnx     YOLO (yalnızca "person" sınıfı kullanılır), giriş boyutu serbest (letterbox, 32'nin katı)
  iskelet.onnx  YOLO pose (17 nokta, standart sıra), kişi kutusu kırpılıp 256x384 tuvale konur
  ozellik.onnx  PaddleClas PULC kişi özelliği (26 çıkış, sigmoid uygulanmış)

Yüz modeli yoktur. Baş kutusu iskeletin yüz noktalarından, bulunamazsa kişi kutusunun üst kısmından çıkarılır.
Yaş grubu ve cinsiyet yalnızca gövde görüntüsünden ve iz boyunca oylanarak tahmin edilir; kişi bazında hiçbir kayda
yazılmaz (Raf Analiz yalnızca toplu sayıları kuyruğa bırakır).
"""
from __future__ import annotations

import math
import os

import cv2
import numpy as np

KP = 0.4                 # iskelet noktası güven eşiği
YUKSEK, DUSUK = 0.45, 0.12   # ByteTrack: yüksek güvenli tespitler önce, düşükler ikinci turda eşlenir
YENI_IZ = 0.5            # yeni iz yalnızca bu güvenin üstündeki tespitle açılır
ONAY_SAYI = 2            # iz bu kadar kez eşlenince "izleniyor" olur (tek karelik yanlış tespit sayılmaz)
OMUR_SN = 2.0            # görülmeyen iz bu kadar süre "kayip" olarak tutulur (tahmini konumla), sonra silinir

# PULC çıkış indeksleri. Kaynak: PaddleClas ppcls/data/postprocess/attr_rec.py ve PULC belgesi (cinsiyet 22 =
# kadın olasılığı). Yaş sırası belgelerde çelişkili; modeller notundaki gözlem (19 = 60 üstü, 21 = 18 altı) ve bu
# depodaki ölçüm (egitim/dene_musteri_demografi.py) için YAS_SIRASI tek yerden değiştirilebilir.
OZ_KADIN = 22
OZ_YAS = (19, 20, 21)
YAS_SIRASI = ("yasli", "yetiskin", "genc")   # OZ_YAS indekslerinin anlamı
OZ_ORT = np.array([0.485, 0.456, 0.406], np.float32)
OZ_SAP = np.array([0.229, 0.224, 0.225], np.float32)


def secenekler(is_parcacigi: int | None = None):
    import onnxruntime as ort

    s = ort.SessionOptions()
    s.log_severity_level = 3
    s.add_session_config_entry("session.intra_op.allow_spinning", "0")  # birden fazla model işlemciyi birbirinden çalmasın
    if is_parcacigi:
        s.intra_op_num_threads = int(is_parcacigi)
    return s


def oturum(yol: str, veri: str | None, is_parcacigi: int | None = None):
    from .model_oturumu import oturum_ac

    return oturum_ac(yol, veri, secenekler(is_parcacigi), ["CPUExecutionProvider"], cpu_yedek=True)


# --------------------------------------------------------------------------------------------- tespit
class Algilayici:
    """YOLO kişi tespiti. Kare `giris` genişliğine (uzun kenar) küçültülür, yükseklik 32'nin katına tamamlanır."""

    def __init__(self, yol: str, veri: str | None = None, giris: int = 640, is_parcacigi: int | None = None):
        self.oturum = oturum(yol, veri, is_parcacigi)
        self.girdi = self.oturum.get_inputs()[0].name
        self.giris = int(giris)

    def calistir(self, bgr: np.ndarray, en_az: float = DUSUK, iou: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        """Dönüş: (kutular [N,4] x1,y1,x2,y2 görüntü pikseli, güven [N])."""
        H, W = bgr.shape[:2]
        o = self.giris / max(W, H)
        yw, yh = max(32, int(round(W * o))), max(32, int(round(H * o)))
        tw, th = int(math.ceil(yw / 32) * 32), int(math.ceil(yh / 32) * 32)
        tuval = np.full((th, tw, 3), 114, np.uint8)
        dx, dy = (tw - yw) // 2, (th - yh) // 2
        tuval[dy:dy + yh, dx:dx + yw] = cv2.resize(bgr, (yw, yh), interpolation=cv2.INTER_AREA if o < 1 else cv2.INTER_LINEAR)
        x = np.ascontiguousarray(tuval[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        y = self.oturum.run(None, {self.girdi: x})[0][0]  # [84, N]
        p = y[4]
        sec = p >= en_az
        if not sec.any():
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
        c, p = y[:4, sec].T, p[sec]
        kutu = np.stack([(c[:, 0] - c[:, 2] / 2 - dx) / o, (c[:, 1] - c[:, 3] / 2 - dy) / o, c[:, 2] / o, c[:, 3] / o], 1)
        kalan = np.array(cv2.dnn.NMSBoxes(kutu.tolist(), p.tolist(), en_az, iou)).reshape(-1)
        kutu, p = kutu[kalan], p[kalan]
        b = np.stack([kutu[:, 0], kutu[:, 1], kutu[:, 0] + kutu[:, 2], kutu[:, 1] + kutu[:, 3]], 1)
        b[:, [0, 2]] = b[:, [0, 2]].clip(0, W)
        b[:, [1, 3]] = b[:, [1, 3]].clip(0, H)
        iyi = (b[:, 2] - b[:, 0] >= 4) & (b[:, 3] - b[:, 1] >= 8)
        return b[iyi].astype(np.float32), p[iyi].astype(np.float32)


# --------------------------------------------------------------------------------------------- takip
def iou_matris(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)), np.float32)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    k = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return k / (aa[:, None] + ab[None, :] - k + 1e-6)


def _benzerlik(izler: np.ndarray, tespit: np.ndarray, iou_esik: float) -> np.ndarray:
    """İz (tahmini konum) ile tespit arasındaki eşleme puanı: örtüşme; örtüşme azsa (seyrek analizde hızlı yürüyen kişi)
    boya oranla yakınlık ve benzer boy. 0 = eşlenemez."""
    m = iou_matris(izler, tespit)
    puan = np.where(m >= iou_esik, 1.0 + m, 0.0)
    if len(izler) and len(tespit):
        ci = np.stack([(izler[:, 0] + izler[:, 2]) / 2, izler[:, 3]], 1)
        ct = np.stack([(tespit[:, 0] + tespit[:, 2]) / 2, tespit[:, 3]], 1)
        hi = np.maximum(izler[:, 3] - izler[:, 1], 1.0)
        ht = np.maximum(tespit[:, 3] - tespit[:, 1], 1.0)
        uzak = np.hypot(ci[:, None, 0] - ct[None, :, 0], ci[:, None, 1] - ct[None, :, 1]) / np.maximum(hi[:, None], ht[None, :])
        oran = hi[:, None] / ht[None, :]
        yakin = (uzak <= 0.55) & (oran > 0.6) & (oran < 1.65)
        puan = np.where((puan == 0) & yakin, 1.0 - uzak, puan)
    return puan


def _ac_gozlu(puan: np.ndarray) -> list[tuple[int, int]]:
    """En yüksek puandan başlayarak çakışmasız eşleme (greedy)."""
    out, ki, kt = [], set(), set()
    if not puan.size:
        return out
    sira = np.dstack(np.unravel_index(np.argsort(-puan, axis=None), puan.shape))[0]
    for i, j in sira:
        if puan[i, j] <= 0:
            break
        if i in ki or j in kt:
            continue
        out.append((int(i), int(j)))
        ki.add(i)
        kt.add(j)
    return out


class Izci:
    """ByteTrack benzeri takip: yüksek güvenli tespitler bütün izlerle, düşük güvenliler yalnızca etkin izlerle eşlenir.
    Hareket modeli sabit hız (kutunun dört kenarı). Seyrek analizde (2-5 kare/sn) örtüşme azalabildiği için yakınlık
    yedeği vardır."""

    def __init__(self, omur_sn: float = OMUR_SN):
        self.izler: dict[int, dict] = {}
        self.sayac = 0
        self.omur = omur_sn

    def _tahmin(self, z: dict, t: float) -> np.ndarray:
        d = min(max(0.0, t - z["t"]), 1.5)
        return z["b"] + z["v"] * d

    def tahmin(self, t: float) -> list[dict]:
        """Analiz edilmeyen karelerde izlerin tahmini kutuları."""
        return [{"iz": k, "b": self._tahmin(z, t), "p": z["p"], "durum": "izleniyor" if z["eslendi"] else "kayip"}
                for k, z in self.izler.items() if z["onay"]]

    def guncelle(self, t: float, kutular: np.ndarray, guven: np.ndarray) -> list[dict]:
        kimlikler = list(self.izler)
        tahmin = np.array([self._tahmin(self.izler[k], t) for k in kimlikler], np.float32).reshape(-1, 4)
        yuksek = np.flatnonzero(guven >= YUKSEK)
        dusuk = np.flatnonzero(guven < YUKSEK)
        eslesme: dict[int, int] = {}  # tespit -> iz
        for i, j in _ac_gozlu(_benzerlik(tahmin, kutular[yuksek], 0.2)):
            eslesme[int(yuksek[j])] = kimlikler[i]
        kalan = [n for n, k in enumerate(kimlikler) if k not in eslesme.values() and self.izler[k]["eslendi"]]
        if len(kalan) and len(dusuk):
            puan = iou_matris(tahmin[kalan], kutular[dusuk])
            puan = np.where(puan >= 0.3, puan, 0.0)
            for i, j in _ac_gozlu(puan):
                eslesme[int(dusuk[j])] = kimlikler[kalan[i]]
        for z in self.izler.values():
            z["eslendi"] = False
        for j, k in eslesme.items():
            z = self.izler[k]
            b = kutular[j].astype(np.float32)
            d = t - z["t"]
            if d > 1e-3:
                v = (b - z["b"]) / d
                z["v"] = v if z["n"] == 1 else 0.5 * z["v"] + 0.5 * v
            z.update(b=b, t=t, p=float(guven[j]), n=z["n"] + 1, eslendi=True)
            if z["n"] >= ONAY_SAYI:
                z["onay"] = True
        for j in range(len(kutular)):
            if j not in eslesme and guven[j] >= YENI_IZ:
                self.sayac += 1
                self.izler[self.sayac] = {"b": kutular[j].astype(np.float32), "v": np.zeros(4, np.float32), "t": t, "ilk": t,
                                          "p": float(guven[j]), "n": 1, "onay": False, "eslendi": True}
        for k in [k for k, z in self.izler.items() if t - z["t"] > (self.omur if z["onay"] else 0.01)]:
            del self.izler[k]
        out = []
        for k, z in self.izler.items():
            if not z["onay"]:
                continue
            out.append({"iz": k, "b": z["b"] if z["eslendi"] else self._tahmin(z, t), "p": z["p"],
                        "durum": "izleniyor" if z["eslendi"] else "kayip"})
        return out


# --------------------------------------------------------------------------------------------- iskelet
class Iskelet:
    """Yukarıdan aşağı duruş: kişi kutusu %12 payla kırpılıp modele toplu verilir. 17 nokta [x, y, güven] (standart sıra:
    0 burun, 1-2 gözler, 3-4 kulaklar, 5-6 omuzlar, 7-8 dirsekler, 9-10 bilekler, 11-12 kalçalar, 13-16 diz ve ayak bilekleri)."""

    PAY = 0.12
    EN_AZ_BOY = 36

    def __init__(self, yol: str, veri: str | None = None, is_parcacigi: int | None = None):
        self.oturum = oturum(yol, veri, is_parcacigi)
        g = self.oturum.get_inputs()[0]
        self.girdi = g.name
        self.h, self.w = (int(g.shape[2]), int(g.shape[3])) if isinstance(g.shape[2], int) else (384, 256)

    def _hazirla(self, bgr, kutu):
        H, W = bgr.shape[:2]
        x1, y1, x2, y2 = (float(v) for v in kutu)
        bw, bh = x2 - x1, y2 - y1
        if bh < self.EN_AZ_BOY or bw < 8:
            return None
        xa, ya = int(max(0, x1 - self.PAY * bw)), int(max(0, y1 - self.PAY * bh))
        xb, yb = int(min(W, x2 + self.PAY * bw)), int(min(H, y2 + self.PAY * bh))
        k = bgr[ya:yb, xa:xb]
        kh, kw = k.shape[:2]
        if kh < 8 or kw < 8:
            return None
        o = min(self.w / kw, self.h / kh)
        yw, yh = max(1, int(round(kw * o))), max(1, int(round(kh * o)))
        tuval = np.full((self.h, self.w, 3), 114, np.uint8)
        dx, dy = (self.w - yw) // 2, (self.h - yh) // 2
        tuval[dy:dy + yh, dx:dx + yw] = cv2.resize(k, (yw, yh), interpolation=cv2.INTER_LINEAR)
        return tuval[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0, o, dx, dy, xa, ya, yw, yh

    def _coz(self, y, o, dx, dy, xa, ya, yw, yh):
        guven = y[:, 4]
        uygun = np.flatnonzero(guven >= 0.25)
        if not len(uygun):
            return None
        merkez = np.hypot(y[uygun, 0] - self.w / 2, y[uygun, 1] - self.h / 2) / max(self.w, self.h)
        alan = (y[uygun, 2] * y[uygun, 3]) / (yw * yh)
        i = uygun[int(np.argmax(guven[uygun] + 0.5 * np.minimum(alan, 1.0) - merkez))]
        k = y[i, 5:].reshape(17, 3)
        return [[round(float((p[0] - dx) / o + xa), 1), round(float((p[1] - dy) / o + ya), 1), round(float(p[2]), 2)] for p in k]

    def calistir(self, bgr: np.ndarray, kutular: list) -> list:
        """Her kutu için 17 nokta ya da None."""
        hazir = [self._hazirla(bgr, b) for b in kutular]
        dolu = [i for i, h in enumerate(hazir) if h is not None]
        out = [None] * len(kutular)
        if not dolu:
            return out
        cikti = self.oturum.run(None, {self.girdi: np.ascontiguousarray(np.stack([hazir[i][0] for i in dolu]))})[0]
        for i, y in zip(dolu, cikti):
            out[i] = self._coz(y.T, *hazir[i][1:])
        return out


# --------------------------------------------------------------------------------------------- baş kutusu
def _yedek_bas(x1, y1, x2, y2) -> list[float]:
    w, h = x2 - x1, y2 - y1
    alt = y1 + (0.3 * h if h >= 1.5 * w else max(0.3 * h, min(0.5 * w, 0.5 * h)))
    return [round(x1 - 0.05 * w, 1), round(y1 - 0.04 * h, 1), round(x2 + 0.05 * w, 1), round(alt, 1)]


def bas_kutulari(b, k=None) -> list[list[float]]:
    """Yüzü örtecek kutular (ilki asıl baş kutusu). İskeletin yüz noktaları ancak inandırıcıysa kullanılır: en az ikisi
    güvenli, yüzün ortası omuzların üstünde ve kişi kutusunun üst yarısında. Öne eğilen kişide model yüz noktalarını
    başka yere koyabildiği için kutu dik değilse (boy < 1.5 × en) kutunun üst kısmı da her zaman gizlenir.
    Yedek bölge: dik duran kişide üst %30, kareye yakın kutuda üst yarıya kadar."""
    x1, y1, x2, y2 = (float(v) for v in b[:4])
    w, h = x2 - x1, y2 - y1
    yedek = _yedek_bas(x1, y1, x2, y2)
    if k:
        yuz = [k[i] for i in range(5) if k[i][2] >= KP]
        omuz = [k[i] for i in (5, 6) if k[i][2] >= KP]
        if len(yuz) >= 2:
            cx, cy = sum(p[0] for p in yuz) / len(yuz), sum(p[1] for p in yuz) / len(yuz)
            inandirici = cy <= y1 + 0.5 * h and (not omuz or cy < min(p[1] for p in omuz))
            if inandirici:
                r = max(max(math.hypot(p[0] - cx, p[1] - cy) for p in yuz) * 2.1, 0.09 * h, 8.0)
                r = min(r, max(0.27 * h, 12.0)) * 1.15
                kp = [round(cx - r, 1), round(cy - 1.2 * r, 1), round(cx + r, 1), round(cy + 1.2 * r, 1)]
                return [kp] if h >= 1.5 * w else [kp, yedek]
    return [yedek]


def bas_kutusu(b, k=None) -> list[float]:
    """Asıl baş kutusu (bas_kutulari'nın ilki)."""
    return bas_kutulari(b, k)[0]


# --------------------------------------------------------------------------------------------- gövde özellikleri
class Ozellik:
    """PULC kişi özelliği: kutu gerilerek 192x256'ya getirilir (RGB, standart ortalama/sapma). Çıkış sigmoid uygulanmış
    26 olasılıktır; burada yalnızca cinsiyet (22) ve yaş (19-21) kullanılır."""

    def __init__(self, yol: str, veri: str | None = None, is_parcacigi: int | None = None):
        self.oturum = oturum(yol, veri, is_parcacigi)
        self.girdi = self.oturum.get_inputs()[0].name

    @staticmethod
    def kirp(bgr, b) -> np.ndarray | None:
        H, W = bgr.shape[:2]
        x1, y1, x2, y2 = int(max(0, b[0])), int(max(0, b[1])), int(min(W, b[2])), int(min(H, b[3]))
        if x2 - x1 < 12 or y2 - y1 < 24:
            return None
        c = cv2.resize(bgr[y1:y2, x1:x2], (192, 256), interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(np.float32) / 255.0
        return ((c - OZ_ORT) / OZ_SAP).transpose(2, 0, 1)

    def calistir(self, bgr: np.ndarray, kutular: list) -> np.ndarray:
        """[N, 26] olasılık (kırpılamayan kutu için satır NaN)."""
        out = np.full((len(kutular), 26), np.nan, np.float32)
        hazir = [(i, self.kirp(bgr, b)) for i, b in enumerate(kutular)]
        hazir = [(i, x) for i, x in hazir if x is not None]
        if hazir:
            y = self.oturum.run(None, {self.girdi: np.ascontiguousarray(np.stack([x for _, x in hazir]))})[0]
            for (i, _), s in zip(hazir, y):
                out[i] = s
        return out


def dik_mi(b, k, W: int, H: int, en_az_boy: float) -> bool:
    """Özellik modeline uygun kırpıntı mı: yeterince büyük, kareden taşmıyor, dik (boy/en ≥ 1.6) ve iskelet varsa omuzlar
    kalçaların üstünde, gövde düşeye yakın. Yukarıdan bakan kamerada kişiler bu ölçüte çoğunlukla uymaz: oy verilmez."""
    x1, y1, x2, y2 = b[:4]
    w, h = x2 - x1, y2 - y1
    if h < en_az_boy or w < 12 or h / max(w, 1.0) < 1.6:
        return False
    if x1 < 3 or y1 < 3 or x2 > W - 3 or y2 > H - 3:
        return False
    if k:
        om = [k[i] for i in (5, 6) if k[i][2] >= KP]
        ka = [k[i] for i in (11, 12) if k[i][2] >= KP]
        if om and ka:
            ox, oy = sum(p[0] for p in om) / len(om), sum(p[1] for p in om) / len(om)
            kx, ky = sum(p[0] for p in ka) / len(ka), sum(p[1] for p in ka) / len(ka)
            if oy >= ky or math.degrees(math.atan2(abs(ox - kx), ky - oy)) > 30:
                return False
    return True


class Oylama:
    """İz başına özellik olasılıklarının ortalaması. Aynı izden en çok saniyede bir örnek alınır (ardışık kareler aynı
    görüntüdür, oyu şişirmesin) ve en çok EN_COK örnek."""

    EN_COK = 15
    ARALIK = 1.0

    def __init__(self):
        self.iz: dict[int, dict] = {}

    def ister_mi(self, iz: int, t: float) -> bool:
        z = self.iz.get(iz)
        return z is None or (z["n"] < self.EN_COK and t - z["t"] >= self.ARALIK)

    def ekle(self, iz: int, t: float, olas: np.ndarray) -> None:
        if not np.isfinite(olas).all():
            return
        z = self.iz.setdefault(iz, {"n": 0, "t": -1e9, "kadin": 0.0, "yas": np.zeros(3, np.float64)})
        z["n"] += 1
        z["t"] = t
        z["kadin"] += float(olas[OZ_KADIN])
        z["yas"] += olas[list(OZ_YAS)].astype(np.float64)

    def ozet(self, iz: int) -> dict | None:
        z = self.iz.get(iz)
        if not z or not z["n"]:
            return None
        yas = z["yas"] / z["n"]
        return {"n": z["n"], "kadin": round(z["kadin"] / z["n"], 3), "yas": {ad: round(float(v), 3) for ad, v in zip(YAS_SIRASI, yas)}}

    def temizle(self, yasayan: set[int]) -> None:
        for k in [k for k in self.iz if k not in yasayan]:
            del self.iz[k]
