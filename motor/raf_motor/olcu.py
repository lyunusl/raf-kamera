"""Geometri yardımcıları: bölgeler, ayak noktası, bölgeye yakınlık, gövde yönü, çizgi geçişi, ısı ızgarası.

Koordinatlar burada kare pikselidir; kamera ayarındaki 0-1 değerler bolgeler() ile piksele çevrilir.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

KP = 0.4
YUKARI_ORAN = 0.25   # bilek omuzdan en çok gövde boyunun bu katı aşağıdaysa "kalkmış kol" (bkz. bilek_uzaniyor)
IZGARA = (32, 18)   # ısı haritası (en, boy)


def bolgeler(ayar: dict, W: int, H: int) -> list[dict]:
    """Kamera ayarındaki bölgeler → piksel. Kimliği olmayan (eski) bölgeye sırasına göre "b<n>" verilir.
    Dönüş: [{"kimlik", "ad", "tur", "poly" (N,2) | None, "esik", "cizgi" (2,2) | None, "ic" (2,) | None, "gozler": [...]}]"""
    olcek = np.array([W, H], np.float32)
    out = []
    for i, b in enumerate(ayar.get("bolgeler") or []):
        if not isinstance(b, dict):
            continue
        z = {"kimlik": str(b.get("kimlik") or f"b{i + 1}"), "ad": str(b.get("ad") or ""), "tur": b.get("tur"), "poly": None,
             "esik": b.get("esik"), "cizgi": None, "ic": None, "gozler": []}
        try:
            if b.get("poly") is not None:
                p = np.asarray(b["poly"], np.float32) * olcek
                if p.ndim == 2 and len(p) >= 3:
                    z["poly"] = p
            if b.get("cizgi") is not None:
                c = np.asarray(b["cizgi"], np.float32) * olcek
                if c.shape == (2, 2):
                    z["cizgi"] = c
            if b.get("ic") is not None:
                z["ic"] = np.asarray(b["ic"], np.float32)[:2] * olcek
        except (TypeError, ValueError):
            continue
        for g in b.get("gozler") or []:
            try:
                k = np.asarray(g["kutu"], np.float32).reshape(2, 2) * olcek
                z["gozler"].append({"kimlik": str(g.get("kimlik") or ""), "kutu": k.reshape(-1), "urun": g.get("urun")})
            except (KeyError, TypeError, ValueError):
                continue
        if z["poly"] is None and z["cizgi"] is None:
            continue
        if z["ad"] == "":
            z["ad"] = z["kimlik"]
        out.append(z)
    return out


def ayak(b) -> tuple[float, float]:
    """Kişinin zemindeki noktası: kutunun alt ortası."""
    return (float(b[0]) + float(b[2])) / 2, float(b[3])


def icinde(poly: np.ndarray, p) -> bool:
    return cv2.pointPolygonTest(poly, (float(p[0]), float(p[1])), False) >= 0


def uzaklik(poly: np.ndarray, p) -> float:
    """İşaretli uzaklık (piksel): içeride pozitif."""
    return float(cv2.pointPolygonTest(poly, (float(p[0]), float(p[1])), True))


def en_yakin_nokta(poly: np.ndarray, p) -> tuple[float, float]:
    px, py = float(p[0]), float(p[1])
    en, nok = 1e18, (px, py)
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        u = 0.0 if L < 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        qx, qy = ax + u * dx, ay + u * dy
        d = (qx - px) ** 2 + (qy - py) ** 2
        if d < en:
            en, nok = d, (float(qx), float(qy))
    return nok


def raf_onunde(poly: np.ndarray, b, yakin: float) -> bool:
    """Kişi raf bölgesinin önünde mi: ayak noktası bölgenin içinde ya da bölgeye boyunun `yakin` katı kadar yakın ve kutusu
    bölgeyle yatayda örtüşüyor. Önden bakan kamerada ayak rafın alt kenarının altında kalır; tavandan bakanda rafın yanında."""
    a = ayak(b)
    h = max(1.0, float(b[3]) - float(b[1]))
    d = uzaklik(poly, a)
    if d >= 0:
        return True
    if -d > yakin * h:
        return False
    return float(b[2]) >= float(poly[:, 0].min()) and float(b[0]) <= float(poly[:, 0].max())


def kutu_bolge_ortusur(poly: np.ndarray, b, pay: float = 0.0) -> bool:
    x1, y1, x2, y2 = (float(v) for v in b[:4])
    w, h = x2 - x1, y2 - y1
    x1, y1, x2, y2 = x1 - pay * w, y1 - pay * h, x2 + pay * w, y2 + pay * h
    return not (x2 < poly[:, 0].min() or x1 > poly[:, 0].max() or y2 < poly[:, 1].min() or y1 > poly[:, 1].max())


def _orta(k, sira):
    n = [k[i] for i in sira if k[i][2] >= KP]
    return (sum(p[0] for p in n) / len(n), sum(p[1] for p in n) / len(n)) if n else None


def govde_boyu(k, b) -> float:
    om, ka = _orta(k, (5, 6)), _orta(k, (11, 12))
    if om and ka:
        return max(math.hypot(om[0] - ka[0], om[1] - ka[1]), 0.15 * (float(b[3]) - float(b[1])))
    return 0.3 * (float(b[3]) - float(b[1]))


def govde_yonu(k, b) -> tuple[float, float] | None:
    """Gövdenin görüntü düzlemindeki bakış yönü (birim vektör) ya da None. Omuz (ve kalça) çizgisine dik:
    sol omuzdan sağ omuza giden s = (sx, sy) için yön (sy, -sx). Kameraya dönük kişide sol omuz görüntünün sağındadır, yön
    aşağı (kameraya) çıkar. Omuzlar dar görünüyorsa (yan duruş) burun omuz ortasına göre yön verir. Yüz noktaları açıkça
    görünüyorsa kişi kameraya dönüktür: hesaplanan yön yukarıyı gösteriyorsa ters çevrilir.
    Bu bir gövde yönüdür, bakış (göz) yönü değildir."""
    if not k:
        return None
    s = [0.0, 0.0]
    n = 0
    for a, c in ((5, 6), (11, 12)):
        if k[a][2] >= KP and k[c][2] >= KP:
            s[0] += k[c][0] - k[a][0]
            s[1] += k[c][1] - k[a][1]
            n += 1
    govde = govde_boyu(k, b)
    yuz_gorunur = k[0][2] >= 0.5 and k[1][2] >= KP and k[2][2] >= KP
    if n and math.hypot(*s) / n >= 0.25 * govde:
        f = (s[1], -s[0])
        L = math.hypot(*f)
        f = (f[0] / L, f[1] / L)
        if yuz_gorunur and f[1] < -0.3:
            f = (-f[0], -f[1])
        return f
    om = _orta(k, (5, 6))
    if om and k[0][2] >= KP:  # yan duruş: burun hangi yandaysa o yöne
        dx = k[0][0] - om[0]
        if abs(dx) >= 0.08 * govde:
            return (1.0 if dx > 0 else -1.0, 0.0)
    return None


def bolgeye_donuk(yon, b, poly: np.ndarray, aci: float) -> bool:
    """Gövde yönü ile ayak noktasından bölgeye (en yakın noktasına; ayak içerideyse bölgenin ortasına) giden yön arasındaki
    açı `aci` dereceden küçük mü."""
    if yon is None:
        return False
    a = ayak(b)
    if icinde(poly, a):
        hedef = (float(poly[:, 0].mean()), float(poly[:, 1].mean()))
    else:
        hedef = en_yakin_nokta(poly, a)
    dx, dy = hedef[0] - a[0], hedef[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 0.05 * max(1.0, float(b[3]) - float(b[1])):
        return False
    c = (yon[0] * dx + yon[1] * dy) / L
    return c >= math.cos(math.radians(aci))


def taraf(cizgi: np.ndarray, p) -> float:
    """Noktanın çizginin hangi yanında olduğu (işaretli uzaklık, piksel)."""
    (ax, ay), (bx, by) = cizgi
    L = math.hypot(bx - ax, by - ay) or 1.0
    return ((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) / L


def cizgi_uzerinde(cizgi: np.ndarray, p, pay: float = 0.1) -> bool:
    """Noktanın çizgiye izdüşümü çizgi parçasının içinde mi (uçlarda `pay` oranında tolerans)."""
    (ax, ay), (bx, by) = cizgi
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L < 1e-9:
        return False
    u = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L
    return -pay <= u <= 1 + pay


def izgara_hucre(p, W: int, H: int) -> tuple[int, int]:
    gx = int(min(IZGARA[0] - 1, max(0, p[0] / W * IZGARA[0])))
    gy = int(min(IZGARA[1] - 1, max(0, p[1] / H * IZGARA[1])))
    return gy, gx


def bos_izgara() -> np.ndarray:
    return np.zeros((IZGARA[1], IZGARA[0]), np.float32)


def bilek_uzaniyor(k, b, en_az_aci: float = 35.0) -> list[tuple[float, float]]:
    """Uzanan bileklerin noktaları. Bilek, kol gövde boyunca aşağı sarkmıyorsa uzanıyor sayılır: omuzdan bileğe yön ile
    omuzdan kalçaya yön arasındaki açı `en_az_aci` dereceden büyük ya da bilek omuzdan yukarıda; ayrıca bilek omuzdan en az
    gövde boyunun 0.45 katı uzakta (el gövdenin önünde değil, dışarıda)."""
    if not k:
        return []
    govde = govde_boyu(k, b)
    out = []
    for omuz, bilek, kalca in ((5, 9, 11), (6, 10, 12)):
        if k[bilek][2] < KP or k[omuz][2] < KP:
            continue
        ox, oy = k[omuz][0], k[omuz][1]
        wx, wy = k[bilek][0] - ox, k[bilek][1] - oy
        # Arkadan bakan kamerada rafa (kameradan uzağa) uzanan kol kısa görünür: bilek omuz hizasına kalkmışsa
        # (omuzdan en çok gövde boyunun YUKARI_ORAN katı aşağıda) uzaklık şartı aranmaz. Sarkan ya da önde bir şey tutan
        # kolda bilek bundan çok daha aşağıdadır.
        yukari = wy < YUKARI_ORAN * govde
        if math.hypot(wx, wy) < 0.45 * govde and not yukari:
            continue
        if k[kalca][2] >= KP:
            hx, hy = k[kalca][0] - ox, k[kalca][1] - oy
        else:
            hx, hy = 0.0, 1.0
        L1, L2 = math.hypot(wx, wy), math.hypot(hx, hy) or 1.0
        aci = math.degrees(math.acos(max(-1.0, min(1.0, (wx * hx + wy * hy) / (L1 * L2)))))
        if aci >= en_az_aci or wy < 0 or yukari:
            out.append((k[bilek][0], k[bilek][1]))
    return out
