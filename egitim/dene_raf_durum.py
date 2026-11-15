"""Göz durumu (bos_raf, az_stok, yanlis_urun, kapali, alma doğrulaması) gerçek raf fotoğraflarında, düzenlenmiş
kare dizileriyle. Modeller: motor/modeller (urun.onnx, gomme.onnx).

  python egitim/dene_raf_durum.py [raf_41 raf_43 ...]

UYARI: kareler durağan Commons fotoğraflarının düzenlenmiş halidir, gerçek kamera akışı değildir (bkz. raf/senaryo.py).
Gözler `gozler` işiyle önerilir, katalog her gözün ilk yüzünden kurulur, referans = düzenlenmemiş fotoğraf.
Kontrol aralığı 10 sn; süreler varsayılan (bos 30, az 60, yanlis 60, dolu 20 sn). Çıktı: egitim/cikti/raf/durum_rapor.json
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raf"))

import ortak  # noqa: E402
import senaryo as S  # noqa: E402
from raf_motor.raf import RafIzleyici, RafOlaylari  # noqa: E402
from raf_motor.urun import UrunKatalogu  # noqa: E402

ZAMANLAR = [float(t) for t in range(0, 160, 10)]
YANLIS_ALARM = ("bos", "az", "yanlis")


def kos(k: S.Kurulum, kare_fn, kisi_fn=None, tetikler=None, ek_zamanlar=(), referans=True):
    """Kare dizisini izleyiciden geçirir. Dönüş: (geçişler, olaylar, adet değişimleri, kayıtlar, izleyici).
    referans=False: kayıtlı referans yok, ilk kontroller geçici referans olur (sözleşme bölüm 7)."""
    kat = UrunKatalogu(k.veri, k.m)
    kat.yukle()
    iz = RafIzleyici(k.ayar, k.m, katalog=kat, referans=k.im if referans else None)
    ol = RafOlaylari(iz, urun_adi=kat.ad)
    rng = np.random.default_rng(7)
    gec, olay, adet, kayitlar = [], [], [], []
    for t in sorted(set(ZAMANLAR) | set(ek_zamanlar)):
        kare = S.gurultu(kare_fn(t), rng)
        kisiler = kisi_fn(t) if kisi_fn else []
        r = iz.guncelle(kare, t, kisiler, tetik=(tetikler or {}).get(t, ()))
        gec += r["gecisler"]
        adet += r["adet_degisimleri"]
        o = ol.guncelle(r, t)
        olay += o["baslayan"]
        if r["kayit"]:
            kayitlar.append((t, r["kayit"]))
    return gec, olay, adet, kayitlar, iz


def yanlis_alarmlar(gec, hedef_gozler):
    return [g for g in gec if g["goz"] not in hedef_gozler and g["sonra"] in YANLIS_ALARM]


def ortusen(k, goz: str, hedef_gozler) -> bool:
    """Yanlış alarm veren göz, düzenlenen bir gözle örtüşüyor mu (önerilen gözler üst üste binebiliyor)."""
    a = next(g["kutu"] for g in k.gozler if g["kimlik"] == goz)
    for h in hedef_gozler:
        b = next(g["kutu"] for g in k.gozler if g["kimlik"] == h)
        if min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]):
            return True
    return False


def main(adlar):
    m = ortak.modeller()
    rapor = {}
    for ad in adlar:
        veri = tempfile.mkdtemp(prefix="raf_durum_")
        k = S.Kurulum(ad, m, veri)
        R = {"goz": len(k.gozler), "urun": k.urun_sayisi}
        print(f"\n== {ad}: {len(k.gozler)} göz, {k.urun_sayisi} katalog ürünü")
        gid = [g["kimlik"] for g in k.gozler]

        # 1) sabit
        gec, olay, _, kay, iz = kos(k, lambda t: k.im)
        ilk = kay[0][1]["gozler"] if kay else []
        R["sabit"] = {"ilk_dolu": sum(1 for g in ilk if g["durum"] == "dolu"),
                      "ilk_bilinmiyor": sum(1 for g in ilk if g["durum"] == "bilinmiyor"),
                      "yanlis_alarm": len(yanlis_alarmlar(gec, set())), "olay": len(olay)}
        print("  sabit:", R["sabit"], [(g["goz"], g["sonra"]) for g in yanlis_alarmlar(gec, set())])

        # 2) ışık
        seviye = [(1, 0, 1), (0.75, 0, 1), (1.3, 0, 1), (0.85, -20, 1.2), (1.1, 15, 0.8), (0.6, 10, 1)]
        gec, olay, _, _, _ = kos(k, lambda t: S.isik(k.im, *seviye[int(t // 10) % len(seviye)]))
        R["isik"] = {"yanlis_alarm": len(yanlis_alarmlar(gec, set())), "olay": len(olay)}
        print("  ışık:", R["isik"], [(g["goz"], g["sonra"], g["t"]) for g in yanlis_alarmlar(gec, set())])

        # 3) boş
        if k.bos:
            hed = k.hedefler(3)
            def kare_bos(t, hed=hed):
                im = k.im
                if t >= 30:
                    for i in hed:
                        im = S.bosalt(im, k.bos, k.px(k.gozler[i]["kutu"]))
                return im
            gec, olay, _, _, _ = kos(k, kare_bos)
            bul = {gid[i]: [g["t"] for g in gec if g["goz"] == gid[i] and g["sonra"] == "bos"] for i in hed}
            R["bos"] = {"hedef": len(hed), "bulunan": sum(1 for v in bul.values() if v),
                        "sure_sn": [v[0] - 30 for v in bul.values() if v],
                        "baska_durum": [(g["goz"], g["sonra"]) for g in gec if g["goz"] in bul and g["sonra"] != "bos"
                                        and g["once"] != "bilinmiyor"],
                        "yanlis_alarm": len(yanlis_alarmlar(gec, set(bul))),
                        "yanlis_alarm_ortusen": sum(ortusen(k, g["goz"], bul) for g in yanlis_alarmlar(gec, set(bul))),
                        "olay_bos_raf": sum(1 for o in olay if o["kural"] == "bos_raf")}
            print("  boş:", R["bos"])
            cv2.imwrite(ortak.cikti(f"durum_{ad}_bos.jpg"), kare_bos(40))
            # 3b) aynı boşaltma, referans dosyası yokken (geçici referans: ilk 3 kontrol 0-2 sn, sonra 10 sn aralık)
            gec, olay, _, kay, _ = kos(k, kare_bos, referans=False, ek_zamanlar=(1.0, 2.0))
            bul = {gid[i]: [g["t"] for g in gec if g["goz"] == gid[i] and g["sonra"] == "bos"] for i in hed}
            R["bos_gecici_referans"] = {"hedef": len(hed), "bulunan": sum(1 for v in bul.values() if v),
                                        "kayit_referans": sorted({r.get("referans") for _, r in kay}),
                                        "yanlis_alarm": len(yanlis_alarmlar(gec, set(bul)))}
            print("  boş (geçici referans):", R["bos_gecici_referans"])

            # 4) az (sağdaki yüzlerin %60'ı örtülür)
            hed = k.hedefler(3, en_az_adet=3) or k.hedefler(2, en_az_adet=2)
            def kare_az(t, hed=hed):
                im = k.im
                if t >= 30:
                    for i in hed:
                        im = S.bosalt(im, k.bos, k.px(k.gozler[i]["kutu"]), oran_sol=0.4)
                return im
            gec, olay, _, _, _ = kos(k, kare_az)
            sonra = {gid[i]: [g["sonra"] for g in gec if g["goz"] == gid[i] and g["once"] != "bilinmiyor"] for i in hed}
            R["az"] = {"hedef": len(hed), "az": sum(1 for v in sonra.values() if "az" in v),
                       "bos": sum(1 for v in sonra.values() if "bos" in v and "az" not in v),
                       "degismedi": sum(1 for v in sonra.values() if not v),
                       "adetler": [k.gozler[i]["adet"] for i in hed],
                       "yanlis_alarm": len(yanlis_alarmlar(gec, set(sonra)))}
            print("  az:", R["az"], sonra)
            cv2.imwrite(ortak.cikti(f"durum_{ad}_az.jpg"), kare_az(40))

        # 5) yanlış ürün: başka ürünün gözü yapıştırılır
        hed = []
        for i in k.hedefler(4):
            j = next((j for j in range(len(k.gozler)) if k.gozler[j]["urun"] != k.gozler[i]["urun"]
                      and abs(j - i) >= 2 and k.gozler[j]["adet"] == k.gozler[i]["adet"]), None)
            if j is None:
                j = next((j for j in range(len(k.gozler)) if k.gozler[j]["urun"] != k.gozler[i]["urun"] and abs(j - i) >= 2), None)
            if j is not None:
                hed.append((i, j))
        hed = hed[:3]
        def kare_yanlis(t, hed=hed):
            im = k.im
            if t >= 30:
                for i, j in hed:
                    im = S.yapistir(im, k.px(k.gozler[j]["kutu"]), k.px(k.gozler[i]["kutu"]))
            return im
        gec, olay, _, _, _ = kos(k, kare_yanlis)
        sonuc = {gid[i]: [g["sonra"] for g in gec if g["goz"] == gid[i] and g["once"] != "bilinmiyor"] for i, _ in hed}
        R["yanlis"] = {"hedef": len(hed), "yanlis": sum(1 for v in sonuc.values() if "yanlis" in v),
                       "baska": {kk: v for kk, v in sonuc.items() if v and "yanlis" not in v},
                       "yanlis_alarm": len(yanlis_alarmlar(gec, set(sonuc))),
                       "olay_yanlis_urun": sum(1 for o in olay if o["kural"] == "yanlis_urun")}
        print("  yanlış:", R["yanlis"], sonuc)
        cv2.imwrite(ortak.cikti(f"durum_{ad}_yanlis.jpg"), kare_yanlis(40))

        # 6) kapalı: kişi 20-70 sn gözün önünde (göz değişmez); boş kaynağı varsa ikinci göz kişi arkasında boşalır
        i = k.hedefler(1)[0]
        ib = k.hedefler(3)[-1] if k.bos else None
        def kisi_kutu(i):
            x1, y1, x2, y2 = k.px(k.gozler[i]["kutu"])
            w, h = x2 - x1, y2 - y1
            return [max(0, x1 - 0.3 * w), max(0, y1 - 0.5 * h), min(k.W, x2 + 0.3 * w), min(k.H, y2 + 0.8 * h)]
        def kare_kapali(t):
            im = k.im
            if ib is not None and t >= 30:
                im = S.bosalt(im, k.bos, k.px(k.gozler[ib]["kutu"]))
            if 20 <= t <= 70:
                im = S.kisi_ciz(im, kisi_kutu(i))
                if ib is not None:
                    im = S.kisi_ciz(im, kisi_kutu(ib))
            return im
        def kisiler(t):
            if not 20 <= t <= 70:
                return []
            return [{"b": kisi_kutu(x)} for x in ([i] + ([ib] if ib is not None else []))]
        gec, olay, _, kay, _ = kos(k, kare_kapali, kisiler)
        kap = [t for t, r in kay for g in r["gozler"] if g["goz"] == gid[i] and g["durum"] == "kapali"]
        gec_i = [g for g in gec if g["goz"] == gid[i] and g["once"] != "bilinmiyor"]
        R["kapali"] = {"kapali_kayit": len(kap), "kapaliyken_gecis": len(gec_i)}
        if ib is not None:
            b_t = [g["t"] for g in gec if g["goz"] == gid[ib] and g["sonra"] == "bos"]
            R["kapali"]["arkada_bosalan_bos_t"] = b_t[0] if b_t else None
        R["kapali"]["yanlis_alarm"] = len(yanlis_alarmlar(gec, {gid[i]} | ({gid[ib]} if ib is not None else set())))
        print("  kapalı:", R["kapali"])
        cv2.imwrite(ortak.cikti(f"durum_{ad}_kapali.jpg"), kare_kapali(40))

        # 7) alma doğrulaması: 50. sn'de en sağdaki yüz alınır, kişi tarafı uzanmanın bittiğini bildirir (tetik)
        if k.bos:
            al = k.hedefler(3, en_az_adet=2)
            def kare_al(t, al=al):
                im = k.im
                if t >= 50:
                    for i in al:
                        n = k.gozler[i]["adet"]
                        im = S.bosalt(im, k.bos, k.px(k.gozler[i]["kutu"]), oran_sol=(n - 1) / n)
                return im
            tet = {50.0: [("b1", gid[i]) for i in al]}
            gec, olay, ad_d, _, _ = kos(k, kare_al, tetikler=tet, ek_zamanlar=(50.0, 52.0))
            hed_g = {gid[i] for i in al}
            dogru = [a for a in ad_d if a["goz"] in hed_g and a["sonra"] == a["once"] - 1 and a["t"] <= 52.0]
            R["alma"] = {"hedef": len(al), "dogrulanan": len({a["goz"] for a in dogru}),
                         "baska_gozde_degisim": sum(1 for a in ad_d if a["goz"] not in hed_g),
                         "baska_gozde_ortusmeyen": sum(1 for a in ad_d if a["goz"] not in hed_g
                                                       and not ortusen(k, a["goz"], hed_g)),
                         "tum_degisim": [(a["goz"], a["once"], a["sonra"], a["t"]) for a in ad_d],
                         "beklenen_adet": [k.gozler[i]["adet"] for i in al]}
            print("  alma:", R["alma"])
        rapor[ad] = R
    with open(ortak.cikti("durum_rapor.json"), "w", encoding="utf-8") as f:
        json.dump(rapor, f, indent=1, ensure_ascii=False)
    return rapor


if __name__ == "__main__":
    if not ortak.gorseller_var():
        print("test görselleri yok: RAF_TEST_GORSELLERI")
        sys.exit(0)
    main(sys.argv[1:] or ["raf_43", "raf_44", "raf_08", "raf_41", "raf_13"])
