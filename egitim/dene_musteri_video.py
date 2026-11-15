"""Müşteri ve operasyon özelliklerinin gerçek (kafe) videolarında sınanması. Videolar depoda değildir:

  set RAF_DENEME_VIDEOLARI=<videoların klasörü>
  python egitim/dene_musteri_video.py [çıktı klasörü]

Her video için bölgeler burada elle çizildi (kafe görüntüsü, perakende değil: tezgâh = kasa, masa/vitrin = raf, yürüme
yolu = koridor, kapı = giriş). Göz sayımları (GOZ) videoların yüzü gizlenmiş karelerine bakılarak yazıldı; motorun sonucu
bunlarla karşılaştırılır. Çıktı klasörüne işaretli, yüzü gizlenmiş kareler yazılır (göz kontrolü için).
Sonuçlar motor/raf_motor/sinama.py'ye elle aktarılır (bu betik dosyayı değiştirmez).
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

DENEMELER = {
    "kasa.mp4": {
        "bolgeler": [
            {"kimlik": "c1", "ad": "Kasa önü", "tur": "kasa", "poly": [[0.02, 0.45], [0.98, 0.45], [0.98, 0.97], [0.02, 0.97]], "esik": 4},
            {"kimlik": "r1", "ad": "Tezgâh", "tur": "raf", "poly": [[0.05, 0.17], [0.95, 0.17], [0.95, 0.36], [0.05, 0.36]]}],
        "ozellikler": {"kasa_kuyrugu": {"sure_sn": 5}},
        # göz: kasa önünde duran müşteri sayısı (yürüyerek gelen sayılmaz) ve karedeki bütün kişiler (2 barista dahil)
        "GOZ": {"kuyruk": {1: 5, 5: 6, 9: 6, 14: 6}, "kisi": {1: 7, 5: 8, 9: 9, 14: 8}},
        "kareler": [1, 5, 9, 14],
    },
    "teras.mp4": {
        "bolgeler": [
            {"kimlik": "r1", "ad": "Masa sağ", "tur": "raf", "poly": [[0.71, 0.6], [0.86, 0.6], [0.86, 0.8], [0.71, 0.8]]},
            {"kimlik": "r2", "ad": "Masa üst", "tur": "raf", "poly": [[0.62, 0.12], [0.75, 0.12], [0.75, 0.26], [0.62, 0.26]]},
            {"kimlik": "r3", "ad": "Masa sol", "tur": "raf", "poly": [[0.21, 0.56], [0.35, 0.56], [0.35, 0.75], [0.21, 0.75]]},
            {"kimlik": "k1", "ad": "Yol", "tur": "koridor", "poly": [[0.36, 0.3], [0.62, 0.3], [0.62, 0.97], [0.36, 0.97]]}],
        "ozellikler": {"tikali_koridor": {"sure_sn": 5}, "dokulme": {"acik": True, "sure_sn": 5}},
        # göz: garson sağ masayı toplar/siler (0-8 sn, en az 1 uzanma), üst masaya servis yapar (~12-14 sn);
        # sol masada oturan kişi baştan sona durur ve masaya dönüktür; üst masada 4 kişi oturur. Yolda engel/leke yok.
        "GOZ": {"kisi": {1: 6, 7: 6, 13: 6}, "uzanma_r1": 1, "uzanma_r2_garson": 1, "duran_r3": 1, "duran_r2": 4, "koridor_olay": 0},
        "kareler": [1, 3, 7, 13],
    },
    "salon.mp4": {
        "bolgeler": [
            {"kimlik": "g1", "ad": "Kapı", "tur": "giris", "cizgi": [[0.12, 0.66], [0.22, 0.33]], "ic": [0.45, 0.6]},
            {"kimlik": "k1", "ad": "Salon yolu", "tur": "koridor", "poly": [[0.25, 0.45], [0.62, 0.45], [0.75, 0.98], [0.2, 0.98]]}],
        "ozellikler": {"tikali_koridor": {"sure_sn": 5}, "dokulme": {"acik": True, "sure_sn": 5}},
        # göz: ~10-14 sn iki kişi kapıdan girer; ~20-27 sn garson ve bir kişi kapıdan çıkar. Yolda engel/leke yok.
        "GOZ": {"giren": 2, "cikan": 2, "koridor_olay": 0},
        "kareler": [12, 14, 24, 26],
    },
    "gercek_kafe.mp4": {
        "bolgeler": [
            {"kimlik": "d1", "ad": "Vitrin dolabı", "tur": "dolap", "poly": [[0.87, 0.12], [1.0, 0.12], [1.0, 0.38], [0.87, 0.38]]},
            {"kimlik": "k1", "ad": "Yol", "tur": "koridor", "poly": [[0.55, 0.15], [0.85, 0.15], [0.85, 0.45], [0.55, 0.45]]}],
        "ozellikler": {"dolap_acik": {"sure_sn": 5}, "tikali_koridor": {"sure_sn": 5}, "dokulme": {"acik": True, "sure_sn": 5}},
        # göz: vitrin kapalı kalır; 1.6 sn'deki karede 18 kişi görünüyor (3'ü kısmen saklı: bitki arkası, kenar)
        "GOZ": {"kisi": {1.6: 18, 6: 18, 10: 18}, "dolap_olay": 0},
        "kareler": [1.6, 6, 10],
    },
}


def kos(z: Zincir, ad: str, d: dict, cikti: Path) -> dict:
    kod = "v" + Path(ad).stem.replace("_", "")
    z.kamera(kod, str(video_klasoru() / ad), d["bolgeler"], d["ozellikler"])
    zamanlar = sorted(set(list(d.get("GOZ", {}).get("kisi", {}).keys()) + list(d.get("GOZ", {}).get("kuyruk", {}).keys()) + d["kareler"]))
    ornek, i, imler = {}, 0, []
    for s in z.calistir(kod):
        if s["v"]["Image"] is None:
            continue
        t = float(s["v"]["Zaman"])
        k = json.loads(s["k"]["Kisiler"])
        if i < len(zamanlar) and t >= zamanlar[i] and k.get("yeni"):
            st = z.durumlar[3].get("durum") or {}
            ornek[zamanlar[i]] = {"kisi": sum(1 for kk in k["kisiler"] if kk.get("durum") == "izleniyor"),
                                  "kuyruk": sum((st.get("son_kuyruk") or {}).values()) if st.get("son_kuyruk") else None}
            if zamanlar[i] in d["kareler"]:
                im = s["a"]["Image"].copy()
                H, W = im.shape[:2]
                cv2.putText(im, f"t={t:.1f}", (W - 170, 60), 0, 1.2, (0, 0, 255), 3)
                imler.append(cv2.resize(im, (800, int(800 * H / W))))
            i += 1
    kayitlar = z.kayitlar()
    if imler:
        rows = [np.hstack(imler[r:r + 2] + [np.zeros_like(imler[0])] * (2 - len(imler[r:r + 2]))) for r in range(0, len(imler), 2)]
        cv2.imwrite(str(cikti / f"{kod}.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 72])
    return {"ornek": ornek, "kayitlar": kayitlar}


def main() -> int:
    if video_klasoru() is None:
        print("atlandı: RAF_DENEME_VIDEOLARI verilmedi")
        return 0
    cikti = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get("TEMP", ".")) / "raf_musteri_video"
    cikti.mkdir(parents=True, exist_ok=True)
    rapor = {}
    for ad, d in DENEMELER.items():
        z = Zincir("raf_video_")
        try:
            r = kos(z, ad, d, cikti)
        finally:
            z.temizle()
        olcum = [k for k in r["kayitlar"] if k["tur"] == "olcum"]
        veri: dict = {}
        for o in olcum:
            for a, v in o["veri"].items():
                veri[a] = veri.get(a, 0) + v if not a.startswith(("kisi_ort", "kuyruk_")) else max(veri.get(a, 0), v)
        olay = [k for k in r["kayitlar"] if k["tur"] == "olay" and not k.get("bitti")]
        baslayan = {}
        for o in olay:
            baslayan.setdefault(o["kural"], {})[o["kimlik"]] = o
        etk = [k for k in r["kayitlar"] if k["tur"] == "etkilesim"]
        rapor[ad] = {"goz": d["GOZ"], "kisi_ornek": {str(t): v["kisi"] for t, v in r["ornek"].items()},
                     "kuyruk_ornek": {str(t): v["kuyruk"] for t, v in r["ornek"].items() if v["kuyruk"] is not None},
                     "veri": veri, "olaylar": {k: [(o["zaman"][11:], o.get("bolge"), o.get("deger")) for o in v.values()] for k, v in baslayan.items()},
                     "etkilesim": [(e["zaman"][11:], e["bolge"], e["eylem"], e["sure_sn"]) for e in etk]}
        print(f"\n=== {ad}")
        print("  göz:", json.dumps(d["GOZ"], ensure_ascii=False))
        print("  kişi (izleniyor) örnekleri:", rapor[ad]["kisi_ornek"], " kuyruk örnekleri:", rapor[ad]["kuyruk_ornek"])
        print("  ölçüm toplamı:", json.dumps({a: round(v, 1) for a, v in veri.items()}, ensure_ascii=False))
        print("  olaylar:", json.dumps(rapor[ad]["olaylar"], ensure_ascii=False))
        print("  etkileşimler:", rapor[ad]["etkilesim"])
    (cikti / "rapor.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nişaretli kareler ve rapor: {cikti}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
