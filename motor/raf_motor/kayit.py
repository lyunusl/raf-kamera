"""Görüntüyü işaretler, yüzleri gizler, olay kliplerini yazar ve olayları panelin okuyacağı kuyruk klasörüne bırakır.

Kuyruk: <veri>/kuyruk/*.json  ·  klipler ve kareler: <veri>/cikti/<kamera>/
Panel kapalıyken de çalışır; panel açılınca kuyruktaki dosyaları sırayla içeri alır.

Gizlilik kuralı: diske yazılan HER kare (son kare, olay karesi, klip) önce yuzleri_gizle() ile işlenmelidir. Yüz modeli
yoktur; kişi analizinin verdiği baş kutuları pikselleştirilir. Kayitci kareleri olduğu gibi yazar: gizlemeyi çağıran yapar
(raf_motor.blok.analiz).
"""
from __future__ import annotations

import json
import os
import time
from collections import deque

import cv2
import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # Studio'da Pillow yoksa yazılar OpenCV ile, Türkçe harfler sadeleştirilerek çizilir
    Image = None

RENK_KUTU = (180, 150, 20)     # BGR: tespit kutusu (camgöbeği)
RENK_OLAY = (60, 120, 20)      # üst şerit (koyu yeşil)
BOLGE_RENKLERI = {             # bölge türü → BGR
    "raf": (150, 200, 40),
    "koridor": (200, 170, 90),
    "kasa": (40, 170, 240),
    "dolap": (230, 140, 60),
    "giris": (90, 200, 90),
}
RENK_UYARI = (40, 40, 220)     # uyarısı süren bölge ve üst şerit (kırmızı)
RENK_BOLGE = (170, 170, 170)
_SADE = str.maketrans("çğıöşüÇĞİÖŞÜ–·", "cgiosuCGIOSU-.")
_FONT: dict = {}

KLIP_EN_COK_SN = 15.0     # klip en çok bu kadar sürer (olay sürse de)
KLIP_ONCE_SN = 1.5        # olaydan önceki bu kadar süre klibe girer
KLIP_SONRA_SN = 1.5       # olay kapandıktan sonra bu kadar daha yazılır
SUREN_BILDIRIM_SN = 10.0  # süren olayın süresi ve risk puanı bu aralıkla panele yenilenir
SON_KARE_SN = 1.0         # kameranın son işaretli karesi bu aralıkla yazılır (Genel Bakış'taki karo)
PIKSEL = 10               # yüz gizleme: baş kutusu en çok bu kadar piksel bloğuna indirilir


def _font(boyut: int):
    if boyut not in _FONT:
        for ad in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
            try:
                _FONT[boyut] = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", ad), boyut)
                break
            except OSError:
                continue
        else:
            _FONT[boyut] = ImageFont.load_default()
    return _FONT[boyut]


def kuyruga_birak(veri: str, kod: str, kayit: dict) -> None:
    """Panelin okuduğu kuyruğa tek kayıt bırakır (kameranın yazıcısı kurulmadan önce de kullanılabilir)."""
    klasor = os.path.join(veri, "kuyruk")
    os.makedirs(klasor, exist_ok=True)
    ad = f"{time.time_ns():020d}_{kod}_h"
    gecici = os.path.join(klasor, ad + ".tmp")
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(kayit, f, ensure_ascii=False)
    os.replace(gecici, os.path.join(klasor, ad + ".json"))


def yuzleri_gizle(fr: np.ndarray, baslar, pay: float = 0.15) -> np.ndarray:
    """Baş kutularını ([x1, y1, x2, y2], kare pikseli) biraz genişletip pikselleştirir. `fr` yerinde değişir."""
    H, W = fr.shape[:2]
    for b in baslar or []:
        try:
            x1, y1, x2, y2 = (float(v) for v in b[:4])
        except (TypeError, ValueError):
            continue
        dx, dy = (x2 - x1) * pay, (y2 - y1) * pay
        x1, y1 = max(0, int(x1 - dx)), max(0, int(y1 - dy))
        x2, y2 = min(W, int(x2 + dx)), min(H, int(y2 + dy))
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        parca = fr[y1:y2, x1:x2]
        kucuk = cv2.resize(parca, (max(1, min(PIKSEL, x2 - x1)), max(1, min(PIKSEL, y2 - y1))), interpolation=cv2.INTER_AREA)
        fr[y1:y2, x1:x2] = cv2.resize(kucuk, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
    return fr


def ciz(fr: np.ndarray, bolgeler: list[dict], ust: str, alt: str, kutular=(), vurgulu=()) -> np.ndarray:
    """Bölgeleri (çokgen ya da giriş çizgisi), etiketli kutuları ({"b": [x1, y1, x2, y2], "etiket": "...", "renk": (B, G, R)}
    isteğe bağlı) ve üstte o an süren uyarıların adını çizer. `vurgulu`: uyarısı süren bölgelerin kimlikleri (kalın kırmızı).
    `fr` yerinde değişir. Yüzler bundan ÖNCE gizlenmiş olmalıdır."""
    etiketler = []
    for b in bolgeler:
        renk = BOLGE_RENKLERI.get(b.get("tur"), RENK_BOLGE)
        kalin = 2
        if b.get("kimlik") in vurgulu:
            renk, kalin = RENK_UYARI, 4
        if b.get("poly") is not None:
            cv2.polylines(fr, [b["poly"].astype(np.int32)], True, renk, kalin, cv2.LINE_AA)
            x, y = int(b["poly"][:, 0].min()) + 6, int(b["poly"][:, 1].min()) + 6
        elif b.get("cizgi") is not None:
            (x1, y1), (x2, y2) = b["cizgi"].astype(int)
            cv2.line(fr, (x1, y1), (x2, y2), renk, kalin + 1, cv2.LINE_AA)
            if b.get("ic") is not None:
                cv2.circle(fr, (int(b["ic"][0]), int(b["ic"][1])), 5, renk, -1, cv2.LINE_AA)
            x, y = min(x1, x2) + 6, min(y1, y2) + 6
        else:
            continue
        etiketler.append((x, y, b.get("ad", ""), renk, (20, 20, 20), 15))
    for k in kutular:
        x1, y1, x2, y2 = (int(v) for v in k["b"][:4])
        renk = tuple(k.get("renk") or RENK_KUTU)
        cv2.rectangle(fr, (x1, y1), (x2, y2), renk, 2, cv2.LINE_AA)
        if k.get("etiket"):
            etiketler.append((x1, max(2, y1 - 26), str(k["etiket"]), renk, (255, 255, 255), 15))
    if ust:
        etiketler.append((12, 10, ust, RENK_UYARI, (255, 255, 255), 20))
    etiketler.append((12, fr.shape[0] - 34, alt, (20, 14, 12), (240, 230, 225), 15))
    return _yazilar(fr, etiketler)


def _yazilar(fr: np.ndarray, etiketler: list) -> np.ndarray:
    gorulen = set()
    if Image is None:
        for x, y, metin, zemin, yazi, boyut in etiketler:
            if not metin or (x // 8, y // 8, metin) in gorulen:
                continue
            gorulen.add((x // 8, y // 8, metin))
            m = metin.translate(_SADE)
            (w, h), _ = cv2.getTextSize(m, cv2.FONT_HERSHEY_SIMPLEX, boyut / 30, 1)
            cv2.rectangle(fr, (x, y), (x + w + 12, y + h + 12), zemin, -1)
            cv2.putText(fr, m, (x + 6, y + h + 5), cv2.FONT_HERSHEY_SIMPLEX, boyut / 30, yazi, 1, cv2.LINE_AA)
        return fr
    im = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
    cz = ImageDraw.Draw(im)
    for x, y, metin, zemin, yazi, boyut in etiketler:
        if not metin or (x // 8, y // 8, metin) in gorulen:
            continue
        gorulen.add((x // 8, y // 8, metin))
        f = _font(boyut)
        l, t, r, b = cz.textbbox((0, 0), metin, font=f)
        w, h = r - l, b - t
        x = min(max(4, x), max(4, im.size[0] - w - 18))
        cz.rounded_rectangle([x, y, x + w + 14, y + h + 10], radius=6, fill=zemin[::-1])
        cz.text((x + 7, y + 4 - t), metin, font=f, fill=yazi[::-1])
    fr[:] = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    return fr


class Kayitci:
    """Bir kameranın klip ve kuyruk yazıcısı.

    Klipler akışın zamanına göre yazılır: kareler düzensiz aralıkla gelse de (canlı akışta analiz edilen kare daha uzun
    sürer) klip gerçek hızında oynar. Sık gelen kareler atlanır, geç gelen kare aradaki boşluğu doldurur."""

    def __init__(self, veri: str, kod: str, kamera_ad: str, W: int, H: int, hiz: float):
        self.kod, self.kamera_ad, self.W, self.H = kod, kamera_ad, W, H
        self.kosu = ""  # çalıştırmanın numarası (blok yazar): panel kayıtları koşuya göre ayırır
        self.hiz = 8.0
        self.hiz_ayarla(hiz)
        self.cikti = os.path.join(veri, "cikti", kod)
        self.kuyruk = os.path.join(veri, "kuyruk")
        os.makedirs(self.cikti, exist_ok=True)
        os.makedirs(self.kuyruk, exist_ok=True)
        self.tampon: deque = deque()  # olaydan önceki son KLIP_ONCE_SN saniye: (zaman, JPEG)
        self.yazicilar: dict[str, dict] = {}
        self.sayac = 0
        self.son_kare_ani = 0.0

    def hiz_ayarla(self, hiz: float) -> None:
        """Klibin saniyedeki kare sayısı. Yalnızca hiç klip açılmamışken değiştirilir."""
        self.hiz = max(2.0, min(30.0, float(hiz)))

    def _birak(self, kayit: dict) -> None:
        self.sayac += 1
        if self.kosu:
            kayit = {**kayit, "kosu": self.kosu}
        ad = f"{time.time_ns():020d}_{self.kod}_{self.sayac:05d}"
        gecici = os.path.join(self.kuyruk, ad + ".tmp")
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(kayit, f, ensure_ascii=False)
        os.replace(gecici, os.path.join(self.kuyruk, ad + ".json"))

    def _olay_birak(self, o: dict, kare: str | None, klip: str | None) -> None:
        self._birak({"tur": "olay", "kamera": self.kod, "kamera_ad": self.kamera_ad, **o, "kare": kare, "klip": klip})

    def _klibe_yaz(self, y: dict, t: float, kare: np.ndarray) -> None:
        """Kareyi, klibin zamanı akışın zamanına yetişene kadar yazar (en çok bir saniyelik boşluk doldurulur)."""
        if y["sonraki"] is None:
            y["sonraki"] = t
        n = 0
        while t >= y["sonraki"] - 1e-6 and n < self.hiz:
            y["yaz"].write(kare)
            y["n"] += 1
            y["sonraki"] += 1.0 / self.hiz
            n += 1
        if t >= y["sonraki"]:
            y["sonraki"] = t + 1.0 / self.hiz

    def _jpg_yaz(self, kare: np.ndarray, ad: str, kalite: int) -> None:
        ok, jpg = cv2.imencode(".jpg", kare, [cv2.IMWRITE_JPEG_QUALITY, kalite])
        if not ok:
            return
        gecici = os.path.join(self.cikti, ad + ".tmp")
        try:
            with open(gecici, "wb") as f:
                f.write(jpg.tobytes())
            os.replace(gecici, os.path.join(self.cikti, ad + ".jpg"))
        except OSError:  # panel dosyayı o anda okuyor olabilir: bir sonraki karede yeniden denenir
            pass

    def son_kare(self, cizili: np.ndarray, zorla: bool = False, temiz: np.ndarray | None = None,
                 kisiler: list | None = None) -> None:
        """Kameranın son işaretli karesi (Genel Bakış'taki karo): yarım dosya görünmesin diye yer değiştirerek yazılır.
        `temiz`: aynı karenin yüzleri gizlenmiş, hiçbir çizim olmayan tam çözünürlüklü kopyası -> temiz_kare.jpg (panelin
        Raflar ekranı arka planı, planogram düzenleyici ve raf referans karesi; çizimleri panel kendisi yapar).
        `kisiler`: o karedeki kişi kutuları (0-1) -> temiz_kare.json {"kisiler": [[x1, y1, x2, y2], ...]}. Kare referans
        olarak saklanınca motor bu kutuların altını "bilinmiyor" sayar (koridor referansı orayı kişisiz görünce öğrenir)."""
        simdi = time.monotonic()
        if not zorla and simdi - self.son_kare_ani < SON_KARE_SN:
            return
        self.son_kare_ani = simdi
        self._jpg_yaz(cizili, "son_kare", 80)
        if temiz is not None:
            self._jpg_yaz(temiz, "temiz_kare", 90)
            gecici = os.path.join(self.cikti, "temiz_kare.json.tmp")
            try:
                with open(gecici, "w", encoding="utf-8") as f:
                    json.dump({"kisiler": [[round(float(v), 4) for v in b[:4]] for b in (kisiler or [])]}, f)
                os.replace(gecici, os.path.join(self.cikti, "temiz_kare.json"))
            except OSError:
                pass

    def kare(self, t: float, cizili: np.ndarray, sonuc: dict, temiz: np.ndarray | None = None,
             kisiler: list | None = None) -> None:
        """Her işaretli karede çağrılır: başlayan olayların klibini açar, sürenleri yazar, bitenleri kapatır.
        `temiz`: yüzleri gizlenmiş çizimsiz kare (yalnızca temiz_kare.jpg'ye gider); `kisiler`: bkz. son_kare."""
        self.son_kare(cizili, temiz=temiz, kisiler=kisiler)
        for o in sonuc["baslayan"]:
            taban = f"{o['zaman'].replace('-', '').replace(':', '').replace('T', '_')}_{o['kimlik'][:8]}_{o['kural']}"
            cv2.imwrite(os.path.join(self.cikti, taban + ".jpg"), cizili, [cv2.IMWRITE_JPEG_QUALITY, 82])
            y = {"yaz": None, "bas": t, "bitis": None, "olay": None, "ham": os.path.join(self.cikti, taban + ".ham.mp4"), "kare": f"{self.kod}/{taban}.jpg",
                 "n": 0, "sonraki": None, "bildirim": t, "klip": None}
            if sum(1 for x in self.yazicilar.values() if x["yaz"] is not None) < 6:  # aynı anda en çok altı klip
                y["yaz"] = cv2.VideoWriter(y["ham"], cv2.VideoWriter_fourcc(*"mp4v"), self.hiz, (self.W, self.H))
                for tt, jpg in self.tampon:
                    self._klibe_yaz(y, tt, cv2.imdecode(jpg, cv2.IMREAD_COLOR))
            self.yazicilar[o["kimlik"]] = y
            self._olay_birak(o, y["kare"], None)
        if not self.tampon or t - self.tampon[-1][0] >= 1.0 / self.hiz - 1e-6:
            ok, jpg = cv2.imencode(".jpg", cizili, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                self.tampon.append((t, jpg))
        while self.tampon and t - self.tampon[0][0] > KLIP_ONCE_SN:
            self.tampon.popleft()
        for o in sonuc["biten"]:
            y = self.yazicilar.get(o["kimlik"])
            if y is not None:
                y["bitis"], y["olay"] = t, o
            else:
                self._olay_birak(o, None, None)
        suren = {o["kimlik"]: o for o in sonuc.get("suren") or []}
        for kimlik, y in list(self.yazicilar.items()):
            if y["yaz"] is not None:
                if t - y["bas"] <= KLIP_EN_COK_SN - KLIP_ONCE_SN:
                    self._klibe_yaz(y, t, cizili)
                else:  # klip doldu: olay sürse de klip kapatılır ve panele hemen bildirilir
                    self._klibi_kapat(y)
                    if kimlik in suren:
                        y["bildirim"] = t
                        self._olay_birak(suren[kimlik], y["kare"], y["klip"])
                        y["klip"] = None  # bildirildi: kapanış kaydında yinelenmez
            if y["bitis"] is not None:
                if y["yaz"] is None or t - y["bitis"] >= KLIP_SONRA_SN:
                    self._kapat(kimlik)
            elif kimlik in suren and t - y["bildirim"] >= SUREN_BILDIRIM_SN:
                y["bildirim"] = t
                self._olay_birak(suren[kimlik], y["kare"], None)

    def _klibi_kapat(self, y: dict) -> None:
        if y["yaz"] is None:
            return
        y["yaz"].release()
        y["yaz"] = None
        if y["n"] >= 2 and os.path.exists(y["ham"]):
            y["klip"] = f"{self.kod}/{os.path.basename(y['ham'])}"

    def _kapat(self, kimlik: str) -> None:
        y = self.yazicilar.pop(kimlik)
        self._klibi_kapat(y)
        if y["olay"] is not None:
            self._olay_birak(y["olay"], y["kare"], y["klip"])

    def olcum(self, o: dict) -> None:
        if os.path.exists(os.path.join(self.cikti, "son_kare.jpg")):
            o["son_kare"] = f"{self.kod}/son_kare.jpg"
        self._birak({"tur": "olcum", "kamera": self.kod, "kamera_ad": self.kamera_ad, **o})

    def bitir(self, kalan_olaylar: list[dict], bitti_isareti: bool = True) -> None:
        """Akış bitti: açık klipleri kapatır, kapanan olayları ve 'bitti' işaretini kuyruğa bırakır."""
        for o in kalan_olaylar:
            y = self.yazicilar.get(o["kimlik"])
            if y is not None:
                y["olay"] = o
            else:
                self._olay_birak(o, None, None)
        for kimlik in list(self.yazicilar):
            self._kapat(kimlik)  # bitişi bildirilmemiş olayın klibi bırakılır, olay açık kalır
        self.tampon.clear()
        if bitti_isareti:
            self._birak({"tur": "bitti", "kamera": self.kod})
