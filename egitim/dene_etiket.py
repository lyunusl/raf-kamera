"""Fiyat etiketi okuma (etiket.py) gerçek etiket fotoğraflarında: her etiket için okunan / basılı.

  python egitim/dene_etiket.py           # okuma tablosu + egitim/cikti/raf/etiket_rapor.json
  python egitim/dene_etiket.py --pafta   # etiket kırpıntılarını tek görselde toplar (kutuları elle denetlemek için)

ETIKETLER: (fotoğraf, etiket kutusu piksel [x1,y1,x2,y2], basılı ana fiyat, not). Kutular ve basılı fiyatlar
fotoğraflara bakılarak elle girildi. Fiyat birimi fotoğraftaki para birimidir (TL, $, zł, ¥, CLP; ayrım yapılmaz).
"etiket_yok" sınaması: aynı fotoğrafta etiketin üstüne raf kenarının etiketsiz bir parçası yapıştırılır (düzenleme).
"""
from __future__ import annotations

import json
import os
import sys
import time

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raf"))

import ortak  # noqa: E402
from raf_motor.etiket import EtiketOkuyucu, karsilastir  # noqa: E402

ETIKETLER = [
    ("etiket_23", [500, 900, 805, 1215], 5.79, "büyük üst simge kuruş"),
    ("etiket_23", [900, 515, 970, 560], 5.99, "küçük, arkada"),
    ("etiket_24", [120, 115, 465, 375], 23.00, "üst simge kuruş, el yazısı değil"),
    ("etiket_24", [555, 150, 905, 435], 26.40, "üst simge kuruş, eğik"),
    ("etiket_27", [495, 580, 725, 745], 298.0, "Japonca, yen"),
    ("etiket_28", [370, 350, 560, 450], 745000.0, "elektronik etiket, binlik ayraç"),
    ("etiket_28", [1040, 350, 1185, 440], 845000.0, "elektronik etiket, binlik ayraç"),
    ("etiket_30", [40, 1085, 310, 1375], 14.90, "Türk market etiketi, üst simge kuruş + birim fiyat 19,90"),
    ("etiket_31", [625, 145, 735, 275], 8.00, "Türkçe, EZİNE"),
    ("etiket_31", [960, 135, 1125, 285], 7.50, "Türkçe, üst simge kuruş"),
    ("etiket_31", [390, 440, 485, 560], 8.50, "Türkçe, küçük, uzak"),
    ("etiket_32", [235, 500, 395, 585], 12.00, "Türkçe, kuruş üst simge"),
    ("etiket_33", [585, 375, 690, 450], 5.99, "pazar etiketi"),
    ("etiket_47", [25, 645, 135, 735], 6.40, "ABD raf etiketi"),
    ("etiket_47", [115, 645, 262, 745], 12.79, "ABD raf etiketi"),
    ("etiket_47", [678, 665, 780, 752], 1.86, "ABD raf etiketi"),
    ("etiket_47", [745, 662, 888, 772], 9.29, "ABD raf etiketi"),
    ("raf_07", [100, 915, 300, 1012], 27.67, "ABD raf etiketi"),
    ("raf_07", [500, 915, 700, 1005], 12.44, "ABD raf etiketi"),
    ("raf_08", [800, 40, 882, 86], 21990.0, "Şili, binlik ayraç"),
    ("raf_08", [55, 105, 160, 156], 19990.0, "Şili, binlik ayraç"),
    ("raf_08", [1022, 243, 1082, 282], 2990.0, "Şili, binlik ayraç"),
    ("raf_08", [625, 305, 692, 346], 3990.0, "Şili, binlik ayraç"),
    ("raf_08", [1083, 398, 1138, 432], 2160.0, "Şili, binlik ayraç"),
    ("raf_08", [838, 448, 892, 486], 1820.0, "Şili, binlik ayraç"),
    ("raf_08", [628, 490, 688, 526], 1390.0, "Şili, binlik ayraç"),
    ("raf_08", [203, 575, 272, 617], 3990.0, "Şili, binlik ayraç"),
    ("raf_11", [655, 840, 752, 902], 9.90, "raf kenarı"),
    ("raf_11", [0, 872, 66, 922], 10.99, "raf kenarı, kesik"),
]
# etiket_yok: (fotoğraf, etiketin kutusu, aynı raf kenarının etiketsiz parçası [x1,y1,x2,y2]) — elle seçildi
ETIKETSIZ = [
    ("raf_08", [838, 448, 892, 486], [905, 470, 1000, 500]),
    ("raf_08", [628, 490, 688, 526], [700, 496, 800, 522]),
    ("raf_11", [655, 840, 752, 902], [255, 850, 350, 900]),
    ("etiket_47", [678, 665, 780, 752], [300, 760, 420, 800]),
]


def pafta():
    parcalar = []
    for ad, k, f, _ in ETIKETLER:
        im = ortak.gorsel(ad)
        c = im[k[1]:k[3], k[0]:k[2]]
        r = 120 / c.shape[0]
        c = cv2.resize(c, (max(1, int(c.shape[1] * r)), 120))
        c = cv2.copyMakeBorder(c, 22, 0, 0, max(0, 260 - c.shape[1]), cv2.BORDER_CONSTANT)
        cv2.putText(c, f"{ad} {f}", (2, 16), 0, 0.5, (0, 255, 255), 1)
        parcalar.append(c[:, :max(260, c.shape[1])])
    for ad, k, kaynak in ETIKETSIZ:
        im = _etiketsiz(ortak.gorsel(ad), k, kaynak)
        c = im[k[1]:k[3], k[0]:k[2]]
        r = 120 / c.shape[0]
        c = cv2.resize(c, (max(1, int(c.shape[1] * r)), 120))
        c = cv2.copyMakeBorder(c, 22, 0, 0, max(0, 260 - c.shape[1]), cv2.BORDER_CONSTANT)
        cv2.putText(c, f"{ad} etiketsiz", (2, 16), 0, 0.5, (0, 255, 255), 1)
        parcalar.append(c)
    gen = max(p.shape[1] for p in parcalar)
    parcalar = [cv2.copyMakeBorder(p, 0, 4, 0, gen - p.shape[1], cv2.BORDER_CONSTANT) for p in parcalar]
    satirlar = [np.hstack(parcalar[i:i + 4] + [np.zeros_like(parcalar[0])] * (4 - len(parcalar[i:i + 4])))
                for i in range(0, len(parcalar), 4)]
    cv2.imwrite(ortak.cikti("etiket_pafta.jpg"), np.vstack(satirlar))


def _etiketsiz(im, k, kaynak):
    out = im.copy()
    p = im[kaynak[1]:kaynak[3], kaynak[0]:kaynak[2]]
    out[k[1]:k[3], k[0]:k[2]] = cv2.resize(p, (k[2] - k[0], k[3] - k[1]), interpolation=cv2.INTER_LINEAR)
    return out


def main():
    ok = EtiketOkuyucu(ortak.modeller())
    satirlar, dogru, sureler = [], 0, []
    bek_dogru = 0
    for ad, k, basili, notu in ETIKETLER:
        im = ortak.gorsel(ad)
        H, W = im.shape[:2]
        kn = [k[0] / W, k[1] / H, k[2] / W, k[3] / H]
        a = time.perf_counter()
        r = ok.oku(im, kn)
        sureler.append((time.perf_counter() - a) * 1000)
        rb = ok.oku(im, kn, beklenen=basili)                       # planogramdaki fiyat biliniyorsa
        rf = ok.oku(im, kn, beklenen=round(basili * 1.1 + 1, 2))   # beklenen farklıysa "farkli" denmeli
        d = r["fiyat"] is not None and abs(r["fiyat"] - basili) < 0.005
        dogru += d
        bek_dogru += rb["etiket"] == "uygun"
        satirlar.append({"foto": ad, "basili": basili, "okunan": r["fiyat"], "dogru": d, "metin": r["metin"],
                         "durum": r["durum"], "beklenenle": rb["etiket"], "farkli_beklenenle": rf["etiket"], "not": notu})
        print(f"{ad:10s} basılı {basili:>10} okunan {str(r['fiyat']):>10} {'✓' if d else '✗'}  beklenenle={rb['etiket']:9s}"
              f" farklıyla={rf['etiket']:9s} metin={r['metin'][:60]!r}")
    yok = []
    for ad, k, kaynak in ETIKETSIZ:
        im = _etiketsiz(ortak.gorsel(ad), k, kaynak)
        H, W = im.shape[:2]
        r = ok.oku(im, [k[0] / W, k[1] / H, k[2] / W, k[3] / H])
        yok.append({"foto": ad, "durum": r["durum"], "metin": r["metin"]})
        print(f"{ad:10s} etiketsiz -> {r['durum']} {r['metin']!r}")
    n = len(ETIKETLER)
    ozet = {"etiket": n, "fiyat_dogru": dogru, "beklenen_verilince_uygun": bek_dogru,
            "farkli_beklenende_farkli": sum(1 for s in satirlar if s["farkli_beklenenle"] == "farkli"),
            "farkli_beklenende_yanlislikla_uygun": sum(1 for s in satirlar if s["farkli_beklenenle"] == "uygun"),
            "gercek_etikete_yok_dendi": sum(1 for s in satirlar if s["durum"] == "yok"),
            "etiketsiz": len(yok),"etiketsiz_yok_dendi": sum(1 for y in yok if y["durum"] == "yok"),
            "okuma_ms_medyan": round(float(np.median(sureler)), 1)}
    print(json.dumps(ozet, ensure_ascii=False))
    with open(ortak.cikti("etiket_rapor.json"), "w", encoding="utf-8") as f:
        json.dump({"ozet": ozet, "etiketler": satirlar, "etiketsiz": yok}, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    if not ortak.gorseller_var():
        print("test görselleri yok: RAF_TEST_GORSELLERI")
        sys.exit(0)
    pafta() if "--pafta" in sys.argv else main()
