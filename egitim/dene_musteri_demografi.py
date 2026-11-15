"""Yaş grubu / cinsiyet (PULC gövde özelliği) değerlendirme yardımcısı: gerçek videolarda iz başına oylanmış olasılıkları
ve yüzü gizlenmiş en büyük kırpıntıyı çıkarır; kişiler göz kontrolüyle etiketlenip modelin kararıyla karşılaştırılır.

  set RAF_DENEME_VIDEOLARI=<videoların klasörü>
  python egitim/dene_musteri_demografi.py <çıktı klasörü> [video,video,...]

Çıktı: <çıktı>/demografi.jpg (numaralı kırpıntılar) ve demografi.json (iz, örnek sayısı, kadın olasılığı, yaş olasılıkları
iki indeks sırasına göre). Göz etiketleri egitim/demografi_etiket.json'a yazılır (yalnızca "kadin"/"erkek"/"?" ve yaş
grubu; kişisel bilgi yoktur) ve `--karsilastir` ile sayılır.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from motor_ortak import Zincir, video_klasoru  # noqa: E402

VIDEOLAR = ["teras.mp4", "salon.mp4", "bahce.mp4", "gercek_kafe.mp4", "gercek_teras.mp4", "kasa.mp4"]
ETIKET = Path(__file__).resolve().parent / "demografi_etiket.json"


def topla(cikti: Path, videolar: list[str], en_az_boy: int = 140) -> list[dict]:
    kl = video_klasoru()
    z = Zincir("raf_demografi_")
    kayit: dict = {}
    try:
        for ad in videolar:
            kod = "d" + Path(ad).stem.replace("_", "")
            # en_az_ornek 1: ham oylar görülsün; karar eşiği burada uygulanmaz
            z.kamera(kod, str(kl / ad), [], {"demografi": {"acik": True, "en_az_ornek": 1, "en_az_boy": en_az_boy}})
            for s in z.calistir(kod, en_cok=900):
                if s["a"]["Image"] is None:
                    continue
                k = json.loads(s["k"]["Kisiler"])
                if not k.get("yeni"):
                    continue
                im = s["a"]["Image"]
                for p in k.get("kisiler", []):
                    if not p.get("oz") or p.get("durum") != "izleniyor":
                        continue
                    a = f"{kod}:{p['iz']}"
                    b = [int(v) for v in p["b"]]
                    alan = (b[2] - b[0]) * (b[3] - b[1])
                    r = kayit.setdefault(a, {"video": ad, "iz": p["iz"], "alan": 0})
                    r["oz"] = p["oz"]
                    if alan > r["alan"]:
                        r["alan"] = alan
                        r["kirp"] = im[max(0, b[1]):b[3], max(0, b[0]):b[2]].copy()
    finally:
        z.temizle()
    liste = sorted(kayit.values(), key=lambda r: (r["video"], r["iz"]))
    cikti.mkdir(parents=True, exist_ok=True)
    hucre = []
    for i, r in enumerate(liste):
        c = r.pop("kirp")
        h = 220
        c = cv2.resize(c, (max(1, int(c.shape[1] * h / c.shape[0])), h))
        c = cv2.copyMakeBorder(c, 26, 0, 0, max(0, 110 - c.shape[1]), cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(c, f"#{i}", (3, 20), 0, 0.7, (0, 0, 255), 2)
        hucre.append(c)
        r["no"] = i
    satirlar, satir, gen = [], [], 0
    for c in hucre:
        if gen + c.shape[1] > 1600 and satir:
            satirlar.append(satir)
            satir, gen = [], 0
        satir.append(c)
        gen += c.shape[1]
    if satir:
        satirlar.append(satir)
    if satirlar:
        imler = [np.hstack(s + [np.full((246, 1600 - sum(x.shape[1] for x in s), 3), 255, np.uint8)]) for s in satirlar]
        cv2.imwrite(str(cikti / "demografi.jpg"), np.vstack(imler), [cv2.IMWRITE_JPEG_QUALITY, 80])
    (cikti / "demografi.json").write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
    return liste


def karsilastir(liste: list[dict], etiket: dict, guven: float = 0.75, yas_guven: float = 0.6, en_az: int = 3) -> dict:
    """Göz etiketiyle karşılaştırma. Yaş için iki indeks sırası denenir: "gozlem" (19 = 60+, 21 = 18 altı; kisi.YAS_SIRASI)
    ve "paddle" (attr_rec.py ad listesi: 19 = 18 altı, 21 = 60+)."""
    out = {"cins": {"dogru": 0, "yanlis": 0, "karar_yok": 0}, "yas_gozlem": {"dogru": 0, "yanlis": 0, "karar_yok": 0},
           "yas_paddle": {"dogru": 0, "yanlis": 0, "karar_yok": 0}, "esiksiz_cins": {"dogru": 0, "yanlis": 0}}
    for r in liste:
        e = etiket.get(f"{r['video']}:{r['iz']}")
        if not e:
            continue
        oz = r["oz"]
        if e.get("cins") in ("kadin", "erkek"):
            esiksiz = "kadin" if oz["kadin"] > 0.5 else "erkek"
            out["esiksiz_cins"]["dogru" if esiksiz == e["cins"] else "yanlis"] += 1
            karar = None if oz["n"] < en_az else "kadin" if oz["kadin"] >= guven else "erkek" if oz["kadin"] <= 1 - guven else None
            out["cins"]["karar_yok" if karar is None else "dogru" if karar == e["cins"] else "yanlis"] += 1
        if e.get("yas") in ("genc", "yetiskin", "yasli"):
            y = oz["yas"]  # gozlem sırasıyla adlandırılmış
            for sira, ad_esle in (("yas_gozlem", {"yasli": "yasli", "yetiskin": "yetiskin", "genc": "genc"}),
                                  ("yas_paddle", {"yasli": "genc", "yetiskin": "yetiskin", "genc": "yasli"})):
                ad, p = max(y.items(), key=lambda kv: kv[1])
                karar = ad_esle[ad] if (p >= yas_guven and oz["n"] >= en_az) else None
                out[sira]["karar_yok" if karar is None else "dogru" if karar == e["yas"] else "yanlis"] += 1
    return out


if __name__ == "__main__":
    if video_klasoru() is None:
        print("atlandı: RAF_DENEME_VIDEOLARI verilmedi")
        sys.exit(0)
    cikti = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path(os.environ.get("TEMP", ".")) / "raf_demografi"
    videolar = sys.argv[2].split(",") if len(sys.argv) > 2 else VIDEOLAR
    if "--karsilastir" in sys.argv and (cikti / "demografi.json").is_file():
        liste = json.loads((cikti / "demografi.json").read_text(encoding="utf-8"))
    else:
        liste = topla(cikti, videolar)
    for r in liste:
        print(f"#{r['no']:<3} {r['video']:<18} iz {r['iz']:<4} n={r['oz']['n']:<2} kadın={r['oz']['kadin']:.2f} "
              f"yaş(19,20,21)={r['oz']['yas']['yasli']:.2f},{r['oz']['yas']['yetiskin']:.2f},{r['oz']['yas']['genc']:.2f}")
    if ETIKET.is_file():
        print(json.dumps(karsilastir(liste, json.loads(ETIKET.read_text(encoding="utf-8"))), ensure_ascii=False))
