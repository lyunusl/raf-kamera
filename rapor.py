"""Veritabanından ekranlar için özetler: Genel Bakış, Uyarılar, Analitik, Raporlar, Excel."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

import depo
import kurallar
import yollar


def aralik(q: dict) -> tuple[str, str]:
    """İstekten zaman aralığı: bas/bit (YYYY-AA-GG) ya da son `gun` gün."""
    simdi = dt.datetime.now()
    if q.get("bas") and q.get("bit"):
        try:
            a, b = dt.date.fromisoformat(str(q["bas"])[:10]), dt.date.fromisoformat(str(q["bit"])[:10])
        except ValueError:
            raise SystemExit("Tarih okunamadı (YYYY-AA-GG).") from None
        if b < a:
            a, b = b, a
        if (b - a).days > 730:
            raise SystemExit("En çok iki yıllık dönem seçilebilir.")
        return a.isoformat() + "T00:00:00", b.isoformat() + "T23:59:59"
    try:
        gun = max(1, min(730, int(q.get("gun", 7))))
    except (TypeError, ValueError):
        gun = 7
    bas = (simdi - dt.timedelta(days=gun - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return bas.isoformat(), simdi.replace(microsecond=0).isoformat()


def _olaylar(bas: str, bit: str, kamera: str | None = None, yanlislar: bool = False) -> list[dict]:
    sql, p = "SELECT * FROM olay WHERE zaman >= ? AND zaman <= ?", [bas, bit]
    if kamera:
        sql += " AND kamera = ?"
        p.append(kamera)
    if not yanlislar:
        sql += " AND durum != 'yanlis'"
    out = depo.sor(sql + " ORDER BY zaman DESC, id DESC", *p)
    vs = depo.genel()["vardiyalar"]
    for o in out:
        o["vardiya"] = depo.vardiya(o["zaman"], vs)
    return out


def _olcumler(bas: str, bit: str, kamera: str | None = None, tam: bool = False) -> list[dict]:
    alanlar = "*" if tam else "id, kamera, kamera_ad, bas, sure_sn, analiz, veri, son_kare"
    sql, p = f"SELECT {alanlar} FROM olcum WHERE bas >= ? AND bas <= ?", [bas, bit]
    if kamera:
        sql += " AND kamera = ?"
        p.append(kamera)
    return depo.sor(sql + " ORDER BY bas", *p)


def son_kritik() -> int:
    """En son kritik olayın numarası (panel yeni kritik olayda siren çalar)."""
    return depo.sor("SELECT COALESCE(MAX(id), 0) AS n FROM olay WHERE duzey = 'kritik'")[0]["n"]


def ayarlar() -> dict[str, dict]:
    """Bütün kamera ayarları: kod → ayar (bozuk dosya atlanır)."""
    out = {}
    for yol in sorted(yollar.AYAR.glob("*.json")) if yollar.AYAR.is_dir() else []:
        if yol.stem.startswith("_"):
            continue
        try:
            a = json.loads(yol.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(a, dict):
            out[a.get("kod") or yol.stem] = a
    return out


def ozellik_acik(ayar: dict, kod: str) -> bool:
    """Özellik bu kamerada açık mı: ayardaki `ozellikler`, yoksa katalogdaki varsayılan."""
    o = (ayar.get("ozellikler") or {}).get(kod)
    if isinstance(o, dict) and "acik" in o:
        return bool(o["acik"])
    return bool(kurallar.KURAL.get(kod, {}).get("varsayilan", False))


ESKI_SN = 600  # çalışma saatinde bu kadar süredir kayıt gelmeyen kamera "veri eski" sayılır


def _son_kayitlar() -> dict[str, str]:
    """Kamera → veritabanındaki son kaydın zamanı (ölçüm sonu, raf kaydı ya da etkileşim)."""
    son: dict[str, str] = {}
    for sql in ("SELECT kamera, MAX(bas) AS z, sure_sn FROM olcum GROUP BY kamera", "SELECT kamera, MAX(zaman) AS z FROM raf_ozet GROUP BY kamera"):
        for r in depo.sor(sql):
            z = r["z"]
            if r.get("sure_sn"):
                try:
                    z = (dt.datetime.fromisoformat(z) + dt.timedelta(seconds=r["sure_sn"])).isoformat()[:19]
                except ValueError:
                    pass
            if z and z > son.get(r["kamera"], ""):
                son[r["kamera"]] = z
    return son


def kameralar() -> list[dict]:
    """Ayar dosyası olan kameralar ve son durumları (son kayıt, veri eskidi mi, açık uyarılar)."""
    import kuyruk

    out = []
    son = _son_kayitlar()
    acik = {r["kamera"]: r for r in depo.sor(
        "SELECT kamera, COUNT(*) AS n, SUM(ciddi) AS ciddi, MAX(puan) AS puan, SUM(suruyor) AS suruyor, "
        "SUM(CASE WHEN suruyor = 1 AND duzey IN ('kritik', 'yuksek') THEN 1 ELSE 0 END) AS suruyor_ciddi FROM olay WHERE durum = 'acik' GROUP BY kamera")}
    simdi = dt.datetime.now()
    calisiyor = depo.calisma_saatinde(simdi)
    katalog_var = bool(kurallar.KURALLAR)
    for kod, a in ayarlar().items():
        ac = acik.get(kod, {})
        kare = yollar.AYAR / f"_kare_{kod}.jpg"
        referans = yollar.AYAR / f"_referans_{kod}.jpg"
        son_kare = yollar.CIKTI / kod / "son_kare.jpg"  # motor, çalışırken saniyede bir yeniler (yüzler gizli)
        bolgeler = a.get("bolgeler") or []
        son_z = son.get(kod)
        canli = kuyruk.SON_KAYIT.get(kod)
        if canli and time.time() - canli < ESKI_SN:
            son_z = max(son_z or "", dt.datetime.fromtimestamp(canli).replace(microsecond=0).isoformat())
        gecen = (simdi - dt.datetime.fromisoformat(son_z)).total_seconds() if son_z else None
        ornek = depo.ornek_kamera(kod) or kod in yollar.ORNEK_ADLARI
        out.append({
            "kod": kod, "ad": a.get("ad", kod), "tur": (a.get("kamera") or {}).get("tur", "rtsp"),
            "bolge": len(bolgeler), "goz": sum(len(b.get("gozler") or []) for b in bolgeler),
            "bolge_turleri": sorted({b.get("tur") for b in bolgeler if b.get("tur")}),
            "kural": (sum(1 for k in kurallar.KURALLAR if ozellik_acik(a, k["kod"])) if katalog_var else len(a.get("ozellikler") or {})),
            "son_analiz": son_z, "son_gecen_sn": round(gecen) if gecen is not None else None,
            # veri eski: çalışma saatinde, kayıt gelmiş ama ESKI_SN'den uzun süredir yeni kayıt yok (örnek kameralarda gösterilmez)
            "eski": bool(not ornek and calisiyor and gecen is not None and gecen > ESKI_SN),
            "son_kare": f"/cikti/{kod}/son_kare.jpg?t={son_kare.stat().st_mtime_ns // 1_000_000}" if son_kare.exists() else None,
            "ayar_karesi": f"/ayar/{kare.name}?t={int(kare.stat().st_mtime)}" if kare.exists() else None,
            "referans_karesi": f"/ayar/{referans.name}?t={int(referans.stat().st_mtime)}" if referans.exists() else None,
            "temiz_kare": (f"/cikti/{kod}/temiz_kare.jpg?t={temiz.stat().st_mtime_ns // 1_000_000}" if (temiz := yollar.CIKTI / kod / "temiz_kare.jpg").exists() else None),
            "referans": a.get("referans"), "gozler_degisim": a.get("gozler_degisim"),
            "acik": ac.get("n", 0), "acik_kritik": ac.get("ciddi") or 0, "suruyor": ac.get("suruyor") or 0, "en_yuksek_puan": ac.get("puan") or 0,
            "suruyor_ciddi": ac.get("suruyor_ciddi") or 0, "ornek": ornek, "ornek_video": kod in yollar.ORNEK_ADLARI,
        })
    return out


def _gunler(bas: str, bit: str) -> list[str]:
    a, b = dt.date.fromisoformat(bas[:10]), dt.date.fromisoformat(bit[:10])
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def ozet(q: dict) -> dict:
    """Genel Bakış."""
    bas, bit = aralik(q)
    olaylar, olcumler = _olaylar(bas, bit), _olcumler(bas, bit)
    gunluk = {g: {"gun": g, "olay": 0, "kritik": 0, "izlenen_sn": 0.0} for g in _gunler(bas, bit)}
    for m in olcumler:
        g = gunluk.get(m["bas"][:10])
        if g:
            g["izlenen_sn"] += m["sure_sn"]
    for o in olaylar:
        g = gunluk.get(o["zaman"][:10])
        if g:
            g["olay"] += 1
            g["kritik"] += o["ciddi"]
    aciklar = sorted((o for o in olaylar if o["durum"] == "acik"), key=lambda o: (-o["suruyor"], -o["puan"], o["zaman"]))
    return {
        "bas": bas, "bit": bit, "tesis": depo.genel()["tesis"],
        "izlenen_sn": round(sum(m["sure_sn"] for m in olcumler)), "olay": len(olaylar),
        "kritik": sum(o["ciddi"] for o in olaylar), "acik": len(aciklar), "suruyor": sum(o["suruyor"] for o in aciklar),
        "seri": [{**g, "izlenen_sn": round(g["izlenen_sn"])} for g in gunluk.values()],
        "kameralar": kameralar(), "canli": aciklar[:12],
    }


def olaylar(q: dict) -> dict:
    """Uyarılar listesi (süzgeçli)."""
    bas, bit = aralik({"gun": q.get("gun", 30), **q})
    liste = _olaylar(bas, bit, q.get("kamera") or None, yanlislar=True)
    secenek_kural = sorted({(o["kural"], o["kural_ad"]) for o in liste}, key=lambda x: x[1])
    secenek_bolge = sorted({o["bolge"] for o in liste if o["bolge"]})
    for alan in ("kategori", "durum", "duzey", "vardiya", "kural", "bolge"):
        if q.get(alan):
            liste = [o for o in liste if str(o[alan]) == q[alan]]
    if q.get("ciddi") == "1":
        liste = [o for o in liste if o["ciddi"]]
    if q.get("sirala") == "puan":
        liste.sort(key=lambda o: (-o["puan"], o["zaman"]))
    try:
        sinir = max(1, min(1000, int(q.get("sinir", 200))))
    except (TypeError, ValueError):
        sinir = 200
    gorevler = defaultdict(list)
    for r in depo.sor("SELECT gorev, olay FROM gorev_olay"):
        gorevler[r["olay"]].append(r["gorev"])
    for o in liste:
        o["gorevler"] = gorevler.get(o["id"], [])
    return {"toplam": len(liste), "suruyor": sum(o["suruyor"] for o in liste), "olaylar": liste[:sinir],
            "kurallar": [{"kod": k, "ad": a} for k, a in secenek_kural], "bolgeler": secenek_bolge}


def analitik(q: dict) -> dict:
    """Analitik: bir kameranın ölçüm katmanları (ısı haritası, ör. koridor yoğunluğu), sayıları ve olayların zamana dağılımı.
    Isı haritası katmanları ölçüm kayıtlarının "izgara" alanından toplanır (bu sürümde motor ızgara üretmez)."""
    bas, bit = aralik({"gun": q.get("gun", 7), **q})
    kamera = q.get("kamera") or None
    olcumler = _olcumler(bas, bit, kamera, tam=True)
    olaylar_ = _olaylar(bas, bit, kamera)
    if q.get("kategori"):
        olaylar_ = [o for o in olaylar_ if o["kategori"] == q["kategori"]]
    if q.get("kural"):
        olaylar_ = [o for o in olaylar_ if o["kural"] == q["kural"]]
    if q.get("ciddi") == "1":
        olaylar_ = [o for o in olaylar_ if o["ciddi"]]
    gen = yuk = 0
    katmanlar: dict[str, list] = {}
    toplamlar: dict[str, float] = defaultdict(float)
    saatlik = [{"saat": h, "izlenen_sn": 0.0, "olay": 0} for h in range(24)]
    for m in olcumler:
        try:
            veri = json.loads(m["veri"] or "{}")
        except ValueError:
            veri = {}
        for ad, v in veri.items() if isinstance(veri, dict) else []:
            if isinstance(v, (int, float)):
                toplamlar[ad] += v
        try:
            iz = json.loads(m["izgara"]) if m["izgara"] else None
        except ValueError:
            iz = None
        if isinstance(iz, dict) and iz.get("gen") and iz.get("yuk"):
            if not gen:
                gen, yuk = int(iz["gen"]), int(iz["yuk"])
            if iz["gen"] == gen and iz["yuk"] == yuk:
                for ad, hucre in (iz.get("katmanlar") or {}).items():
                    hedef = katmanlar.setdefault(ad, [[0.0] * gen for _ in range(yuk)])
                    for y in range(yuk):
                        for x in range(gen):
                            hedef[y][x] += hucre[y][x]
        saatlik[int(m["bas"][11:13])]["izlenen_sn"] += m["sure_sn"]
    for o in olaylar_:
        saatlik[int(o["zaman"][11:13])]["olay"] += 1
    olay_izgara = [[0] * gen for _ in range(yuk)] if gen else []
    for o in olaylar_:
        if gen and o["x"] is not None:
            olay_izgara[min(yuk - 1, max(0, int(o["y"] * yuk)))][min(gen - 1, max(0, int(o["x"] * gen)))] += o["puan"]
    yogun = max(saatlik, key=lambda s: s["olay"]) if olaylar_ else None
    ayar = {}
    if kamera and (yollar.AYAR / f"{kamera}.json").exists():
        ayar = json.loads((yollar.AYAR / f"{kamera}.json").read_text(encoding="utf-8"))
    kural_say = defaultdict(int)
    for o in olaylar_:
        kural_say[(o["kural"], o["kural_ad"])] += 1
    son_kare = yollar.CIKTI / kamera / "son_kare.jpg" if kamera else None
    # en riskli hücrenin payı ("bir köşe riskin %X'i")
    toplam_risk = sum(sum(s) for s in olay_izgara) if gen else 0
    en_hucre = max((v for s in olay_izgara for v in s), default=0) if gen else 0
    return {
        "bas": bas, "bit": bit, "kamera": kamera, "parca": len(olcumler),
        "son_kare": f"/cikti/{kamera}/son_kare.jpg?t={son_kare.stat().st_mtime_ns // 1_000_000}" if son_kare is not None and son_kare.exists() else None,
        "izgara": {"gen": gen, "yuk": yuk, "katmanlar": katmanlar, "olay": olay_izgara},
        "bolgeler": ayar.get("bolgeler") or [],
        "noktalar": [{"x": o["x"], "y": o["y"], "puan": o["puan"], "kural_ad": o["kural_ad"], "id": o["id"]} for o in olaylar_ if o["x"] is not None][:500],
        "sayilar": {
            "toplamlar": {ad: round(v, 1) for ad, v in toplamlar.items()},
            "olay": len(olaylar_), "kritik": sum(o["ciddi"] for o in olaylar_), "izlenen_sn": round(sum(m["sure_sn"] for m in olcumler)),
            "yogun_saat": f"{yogun['saat']:02d}:00" if yogun and yogun["olay"] else None,
            "en_riskli_pay": round(100 * en_hucre / toplam_risk) if toplam_risk else None,
        },
        "saatlik": [{"saat": s["saat"], "izlenen_sn": round(s["izlenen_sn"]), "olay": s["olay"]} for s in saatlik],
        "kurallar": sorted(({"kod": k, "ad": ad, "n": n} for (k, ad), n in kural_say.items()), key=lambda r: -r["n"]),
    }


def rapor(q: dict) -> dict:
    """Raporlar: olay eğilimi ve kural / kamera / vardiya / bölge kırılımları."""
    bas, bit = aralik({"gun": q.get("gun", 30), **q})
    olaylar_, olcumler = _olaylar(bas, bit), _olcumler(bas, bit)
    gunler = _gunler(bas, bit)
    haftalik = len(gunler) > 62

    def kova(tarih: str) -> str:
        if not haftalik:
            return tarih
        d = dt.date.fromisoformat(tarih)
        return (d - dt.timedelta(days=d.weekday())).isoformat()

    egilim = {}
    for g in gunler:
        egilim.setdefault(kova(g), {"d": kova(g), "olay": 0, "kritik": 0, "risk": 0})
    for o in olaylar_:
        e = egilim.get(kova(o["zaman"][:10]))
        if e:
            e["olay"] += 1
            e["kritik"] += o["ciddi"]
            e["risk"] += o["puan"]

    def kirilim(alan: str, ad_alani: str | None = None) -> list[dict]:
        g = defaultdict(lambda: {"n": 0, "kritik": 0, "risk": 0, "sure_sn": 0.0})
        for o in olaylar_:
            x = g[(o[alan], o[ad_alani] if ad_alani else o[alan])]
            x["n"] += 1
            x["kritik"] += o["ciddi"]
            x["risk"] += o["puan"]
            x["sure_sn"] += o["sure_sn"]
        return sorted(({"kod": k, "ad": ad, **{a: (round(v, 1) if isinstance(v, float) else v) for a, v in x.items()}}
                       for (k, ad), x in g.items()), key=lambda r: -r["risk"])

    yanit = []
    for o in olaylar_:
        if o["durum_zamani"] and o["durum"] != "acik":
            try:
                yanit.append((dt.datetime.fromisoformat(o["durum_zamani"]) - dt.datetime.fromisoformat(o["zaman"])).total_seconds() / 60)
            except ValueError:
                pass
    # önceki eşit uzunluktaki dönemle karşılaştırma
    uzun = dt.datetime.fromisoformat(bit) - dt.datetime.fromisoformat(bas)
    obas = (dt.datetime.fromisoformat(bas) - uzun - dt.timedelta(seconds=1)).isoformat()
    obit = (dt.datetime.fromisoformat(bas) - dt.timedelta(seconds=1)).isoformat()
    gorevler = depo.sor("SELECT durum, COUNT(*) AS n FROM gorev GROUP BY durum")
    kategori = kirilim("kategori")
    for r in kategori:
        r["ad"] = kurallar.KATEGORILER.get(r["kod"], r["kod"])
    return {
        "bas": bas, "bit": bit, "tesis": depo.genel()["tesis"], "haftalik": haftalik,
        "olay": len(olaylar_), "onceki_olay": len(_olaylar(obas, obit)), "kritik": sum(o["ciddi"] for o in olaylar_),
        "risk": sum(o["puan"] for o in olaylar_),
        "acik": sum(1 for o in olaylar_ if o["durum"] == "acik"), "cozulen": sum(1 for o in olaylar_ if o["durum"] == "cozuldu"),
        "yanlis": depo.sor("SELECT COUNT(*) AS n FROM olay WHERE zaman >= ? AND zaman <= ? AND durum = 'yanlis'", bas, bit)[0]["n"],
        "izlenen_sn": round(sum(m["sure_sn"] for m in olcumler)),
        "ort_yanit_dk": round(sum(yanit) / len(yanit), 1) if yanit else None,
        "egilim": list(egilim.values()),
        "kurallar": kirilim("kural", "kural_ad"), "kameralar": kirilim("kamera", "kamera_ad"), "vardiyalar": kirilim("vardiya"),
        "kategoriler": kategori, "bolgeler": [r for r in kirilim("bolge") if r["kod"]],
        "gorevler": {r["durum"]: r["n"] for r in gorevler},
    }


def gorevler() -> list[dict]:
    """Görevler; her biri için bağlı olaylar ve kapanış sonrası doğrulama."""
    liste = depo.sor("SELECT * FROM gorev ORDER BY (durum = 'kapandi'), COALESCE(son_tarih, '9999'), id DESC")
    bugun = dt.date.today().isoformat()
    for g in liste:
        bagli = depo.sor("SELECT o.id, o.zaman, o.kural, o.kural_ad, o.kamera, o.kamera_ad, o.bolge, o.puan, o.kare, o.klip FROM gorev_olay b "
                         "JOIN olay o ON o.id = b.olay WHERE b.gorev = ? ORDER BY o.zaman DESC", g["id"])
        g["olaylar"] = bagli
        g["gecikti"] = bool(g["son_tarih"] and g["durum"] != "kapandi" and g["son_tarih"] < bugun)
        # aynı kamera + kural (+ bölge) için haftalık olay sayısı: önlem işe yaradı mı?
        kamera = g["kamera"] or (bagli[0]["kamera"] if bagli else None)
        kural = g["kural"] or (bagli[0]["kural"] if bagli else None)
        g["haftalar"], g["dogrulama"] = [], None
        g["kural_ad"] = kurallar.KURAL.get(kural or "", {}).get("ad") or (bagli[0]["kural_ad"] if bagli else None)
        g["kamera_ad"] = bagli[0]["kamera_ad"] if bagli else None
        if kamera and kural and not g.get("otomatik"):  # elle açılan görev: önlem işe yaradı mı (otomatik görev olayla kapanır)
            sql, p = "SELECT zaman, puan FROM olay WHERE kamera = ? AND kural = ? AND durum != 'yanlis'", [kamera, kural]
            if g["bolge"]:
                sql += " AND bolge = ?"
                p.append(g["bolge"])
            hafta = defaultdict(int)
            for o in depo.sor(sql, *p):
                d = dt.date.fromisoformat(o["zaman"][:10])
                hafta[(d - dt.timedelta(days=d.weekday())).isoformat()] += 1
            g["haftalar"] = [{"hafta": h, "n": n} for h, n in sorted(hafta.items())][-10:]
            if g["durum"] == "kapandi" and g["kapanma"]:
                sonra = depo.sor(sql + " AND zaman > ?", *p, g["kapanma"])
                izleme = depo.sor("SELECT COUNT(*) AS n FROM olcum WHERE kamera = ? AND bas > ?", kamera, g["kapanma"])[0]["n"]
                g["dogrulama"] = {"sonra_olay": len(sonra), "sonra_parca": izleme,
                                  "durum": "bekliyor" if izleme == 0 else ("tekrarladi" if sonra else "dogrulandi")}
    return liste


def excel() -> Path:
    """Son 30 günün raporunu cikti/rapor.xlsx olarak yazar."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    r = rapor({"gun": 30})
    duzey = {"kritik": "kritik", "yuksek": "yüksek", "orta": "orta", "dusuk": "düşük"}
    kitap = Workbook()
    s = kitap.active
    s.title = "Özet"
    for satir in (["Tesis", r["tesis"]], ["Dönem", f"{r['bas'][:10]} – {r['bit'][:10]}"], ["Olay", r["olay"]],
                  ["Önceki dönemde olay", r["onceki_olay"]], ["Kritik olay", r["kritik"]], ["Açık olay", r["acik"]],
                  ["Çözülen olay", r["cozulen"]], ["Yanlış alarm", r["yanlis"]], ["İzlenen süre (saat)", round(r["izlenen_sn"] / 3600, 2)],
                  ["Ortalama yanıt süresi (dk)", r["ort_yanit_dk"]]):
        s.append(satir)
    for ad, baslik, liste in (("Kurallar", "Kural", r["kurallar"]), ("Kameralar", "Kamera", r["kameralar"]),
                              ("Vardiyalar", "Vardiya", r["vardiyalar"]), ("Bölgeler", "Bölge", r["bolgeler"])):
        s = kitap.create_sheet(ad)
        s.append([baslik, "Olay", "Kritik", "Risk puanı toplamı", "Toplam süre (sn)"])
        for x in liste:
            s.append([x["ad"], x["n"], x["kritik"], x["risk"], x["sure_sn"]])
    s = kitap.create_sheet("Olaylar")
    s.append(["No", "Zaman", "Kamera", "Kural", "Kategori", "Düzey", "Bölge", "Vardiya", "Önem", "Olasılık", "Risk puanı", "Süre (sn)", "Durum", "Üstlenen", "Not"])
    for o in _olaylar(r["bas"], r["bit"], yanlislar=True):
        s.append([o["id"], o["zaman"].replace("T", " "), o["kamera_ad"], o["kural_ad"], kurallar.KATEGORILER.get(o["kategori"], o["kategori"]),
                  duzey.get(o["duzey"], o["duzey"]), o["bolge"], o["vardiya"], o["onem"], o["olasilik"], o["puan"], o["sure_sn"],
                  {"acik": "açık", "ustlenildi": "üstlenildi", "cozuldu": "çözüldü", "yanlis": "yanlış alarm"}.get(o["durum"], o["durum"]),
                  o["ustlenen"], o["notlar"]])
    s = kitap.create_sheet("Görevler")
    s.append(["No", "Başlık", "Sorumlu", "Son tarih", "Durum", "Bağlı olay", "Oluşturma", "Kapanma", "Doğrulama"])
    for g in gorevler():
        s.append([g["id"], g["baslik"], g["sorumlu"], g["son_tarih"], {"acik": "açık", "suruyor": "sürüyor", "kapandi": "kapandı"}.get(g["durum"]),
                  len(g["olaylar"]), g["olusturma"].replace("T", " "), (g["kapanma"] or "").replace("T", " "),
                  {"dogrulandi": "kamera doğruladı", "tekrarladi": "tekrarladı", "bekliyor": "izleme bekleniyor"}.get((g["dogrulama"] or {}).get("durum"), "")])
    for s in kitap.worksheets:
        for h in s[1]:
            h.font = Font(bold=True)
        for sutun in s.columns:
            s.column_dimensions[sutun[0].column_letter].width = min(48, max(12, max(len(str(h.value or "")) for h in sutun) + 2))
    yollar.CIKTI.mkdir(parents=True, exist_ok=True)
    hedef = yollar.CIKTI / "rapor.xlsx"
    kitap.save(hedef)
    return hedef


# ================================================================ raf, ürün ve müşteri ölçüleri (panel türetir; motor üretmez)
#
# Bütün süreler çalışma saatlerine göre hesaplanır (Ayarlar → Çalışma saatleri): mağaza kapalıyken boş kalan raf kayıp
# satış ya da tepki süresi sayılmaz. Göz durumları raf_durum tablosundaki değişikliklerden aralıklara çevrilir.

BILINEN = ("dolu", "az", "bos", "yanlis")
VARSAYILAN_DONUSUM = 0.3  # alma / durma oranı bilinmiyorsa (duran müşterinin ürün alma olasılığı)


def _t(s) -> dt.datetime:
    return dt.datetime.fromisoformat(str(s)[:19])


def _iso(t: dt.datetime) -> str:
    return t.replace(microsecond=0).isoformat()


def onceki_donem(bas: str, bit: str) -> tuple[str, str]:
    """Aynı uzunlukta, hemen önceki dönem."""
    a, b = _t(bas), _t(bit)
    uzun = b - a
    return _iso(a - uzun - dt.timedelta(seconds=1)), _iso(a - dt.timedelta(seconds=1))


def goz_tanimlari(kamera: str | None = None, ayar: dict | None = None) -> dict[tuple, dict]:
    """Kamera ayarlarındaki gözler: (kamera, bölge, göz) → beklenen ürün, adet, fiyat, kutu."""
    urun = {u["kimlik"]: u for u in depo.urunler()}
    out = {}
    kaynak = {kamera: ayar} if ayar is not None else ayarlar()
    for kod, a in kaynak.items():
        if kamera and kod != kamera:
            continue
        for b in a.get("bolgeler") or []:
            for g in b.get("gozler") or []:
                if not g.get("kimlik"):
                    continue
                u = urun.get(g.get("urun")) or {}
                fiyat = g.get("fiyat") if g.get("fiyat") is not None else u.get("fiyat")
                out[(kod, b.get("kimlik") or "", g["kimlik"])] = {
                    "kamera": kod, "kamera_ad": a.get("ad", kod), "bolge": b.get("kimlik") or "", "bolge_ad": b.get("ad") or "",
                    "bolge_tur": b.get("tur"), "goz": g["kimlik"], "urun": g.get("urun"), "urun_ad": u.get("ad"), "adet": g.get("adet"),
                    "fiyat": fiyat, "beklenen_fiyat": g.get("fiyat"), "kutu": g.get("kutu"), "etiket_kutu": g.get("etiket"),
                }
    return out


def _dosya_kameralari() -> set[str]:
    """Kaynağı video dosyası olan kameraların kodları (ayar dosyalarından)."""
    out = set()
    for yol in yollar.AYAR.glob("*.json") if yollar.AYAR.is_dir() else []:
        try:
            a = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(a, dict) and (a.get("kamera") or {}).get("tur") == "dosya":
            out.add(str(a.get("kod") or yol.stem))
    return out


def _araliklar(bas: str, bit: str, kamera: str | None = None) -> dict[tuple, list]:
    """Her göz için dönem içindeki durum aralıkları: [(başlangıç, bitiş, durum kaydı)]. Dönemden önceki son kayıt
    başlangıç durumunu verir. Son aralık şimdiye (en çok son görülmeden ESKI_SN sonrasına) kadar sürer: kamera kayıt
    bırakmayı kestiyse eski durum sonsuza uzatılmaz."""
    ek, p = (" AND kamera = ?", [kamera]) if kamera else ("", [])
    satirlar = depo.sor(f"SELECT * FROM raf_durum WHERE zaman >= ? AND zaman <= ?{ek} ORDER BY zaman, id", bas, bit, *p)
    tohum = depo.sor(f"SELECT r.* FROM raf_durum r JOIN (SELECT kamera, bolge, goz, MAX(zaman) AS z FROM raf_durum WHERE zaman < ?{ek} "
                     "GROUP BY kamera, bolge, goz) m ON r.kamera = m.kamera AND r.bolge = m.bolge AND r.goz = m.goz AND r.zaman = m.z ORDER BY r.id",
                     bas, *p)
    son = {(r["kamera"], r["bolge"], r["goz"]): r for r in depo.sor("SELECT * FROM raf_son" + (" WHERE kamera = ?" if kamera else ""), *p)}
    gruplar: dict[tuple, list] = {}
    for r in tohum:  # aynı anda iki kayıt varsa sonuncusu
        gruplar[(r["kamera"], r["bolge"], r["goz"])] = [r]
    for r in satirlar:
        gruplar.setdefault((r["kamera"], r["bolge"], r["goz"]), []).append(r)
    son_an = min(_t(bit), dt.datetime.now().replace(microsecond=0))
    t_bas = _t(bas)
    dosya = _dosya_kameralari()
    out = {}
    for k, liste in gruplar.items():
        s = son.get(k)
        # video dosyası çözümlemesi bitince göz durumu son görüldüğü anda biter (10 sn'lik klipteki boş göz 10 dk boş
        # sayılmasın); canlı kamera kayıt bırakmayı kestiyse en çok ESKI_SN uzatılır
        uzat = 0 if k[0] in dosya else ESKI_SN
        kapanis = min(son_an, _t(s["zaman"]) + dt.timedelta(seconds=uzat)) if s else son_an
        araliklar = []
        for i, r in enumerate(liste):
            t0 = max(_t(r["zaman"]), t_bas)
            t1 = min(_t(liste[i + 1]["zaman"]) if i + 1 < len(liste) else max(kapanis, t0), son_an)
            if t1 > t0:
                araliklar.append((t0, t1, r))
        out[k] = araliklar
    return out


def _saatlere(a: dt.datetime, b: dt.datetime):
    """[a, b) aralığını saat dilimlerine böler: (an, saniye)."""
    while a < b:
        sinir = min(b, a.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1))
        yield a, (sinir - a).total_seconds()
        a = sinir


def olcum_toplamlari(bas: str, bit: str, kamera: str | None = None) -> dict[str, dict]:
    """Kamera → {"sure_sn": izlenen süre, "veri": olcum.veri anahtarlarının toplamı, "kuyruk_en_cok": en büyük kuyruk}."""
    out: dict[str, dict] = {}
    for m in _olcumler(bas, bit, kamera):
        o = out.setdefault(m["kamera"], {"sure_sn": 0.0, "veri": defaultdict(float), "kuyruk_en_cok": 0.0, "kuyruk_agirlik": 0.0})
        o["sure_sn"] += m["sure_sn"] or 0
        try:
            veri = json.loads(m["veri"] or "{}")
        except ValueError:
            veri = {}
        for ad, v in (veri.items() if isinstance(veri, dict) else []):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if ad == "kuyruk_en_cok":
                    o["kuyruk_en_cok"] = max(o["kuyruk_en_cok"], v)
                elif ad == "kuyruk_ort":
                    o["kuyruk_agirlik"] += v * (m["sure_sn"] or 0)
                else:
                    o["veri"][ad] += v
    for o in out.values():
        o["kuyruk_ort"] = round(o["kuyruk_agirlik"] / o["sure_sn"], 2) if o["sure_sn"] else None
    return out


def _donusum(olc: dict[str, dict]) -> float:
    duran = sum(o["veri"].get("duran", 0) for o in olc.values())
    alan = sum(o["veri"].get("alan", 0) for o in olc.values())
    return min(0.9, max(0.05, alan / duran)) if duran >= 20 else VARSAYILAN_DONUSUM


def raf_olculeri(bas: str, bit: str, kamera: str | None = None, g: dict | None = None) -> dict:
    """Göz başına dönem ölçüleri ve toplamlar.

    boş / az / dolu süresi: çalışma saatine düşen saniye.
    Raf doldurma tepki süresi: gözün dolu iken az ya da boş olduğu andan yeniden dolu olduğu ana kadar geçen çalışma süresi.
    Kayıp satış (TAHMİN): boş_süre × alma_hızı. Alma hızı gözün kendi geçmişinden (dönemde en az 3 alma ve 1 saat ürün varken
    izleme) = alma / ürünün bulunduğu süre; yoksa bölgeden = (bölgede duran kişi / izlenen süre) × (alma/durma oranı) / bölgedeki göz sayısı.
    Tutar = adet × gözün fiyatı (yoksa ürünün katalog fiyatı)."""
    g = g or depo.genel()
    tanim = goz_tanimlari(kamera)
    araliklar = _araliklar(bas, bit, kamera)
    ek, p = (" AND kamera = ?", [kamera]) if kamera else ("", [])
    alma: dict[tuple, int] = defaultdict(int)
    for r in depo.sor(f"SELECT kamera, bolge, goz, COUNT(*) AS n FROM etkilesim WHERE eylem = 'aldi' AND goz IS NOT NULL AND zaman >= ? AND zaman <= ?{ek} "
                      "GROUP BY kamera, bolge, goz", bas, bit, *p):
        alma[(r["kamera"], r["bolge"] or "", r["goz"])] += r["n"]
    olc = olcum_toplamlari(bas, bit, kamera)
    donusum = _donusum(olc)
    bolge_goz = defaultdict(int)
    for k in tanim:
        bolge_goz[(k[0], k[1])] += 1
    matris = [[0.0] * 24 for _ in range(7)]  # haftanın günü × saat: boş göz-dakika
    gozler, dolum = [], []
    for k, t in tanim.items():
        sn: dict[str, float] = defaultdict(float)
        bekleyen = None
        for t0, t1, r in araliklar.get(k, []):
            durum = r["durum"]
            for a, b in depo.calisma_parcalari(t0, t1, g):
                sn[durum] += (b - a).total_seconds()
                if durum == "bos":
                    for an, s in _saatlere(a, b):
                        matris[an.weekday()][an.hour] += s / 60
            if durum in ("az", "bos"):
                if bekleyen is None:
                    bekleyen = {"bas": t0, "bos": durum == "bos"}
                elif durum == "bos":
                    bekleyen["bos"] = True
            elif durum == "dolu" and bekleyen is not None:
                dolum.append({**{a: t[a] for a in ("kamera", "kamera_ad", "bolge", "bolge_ad", "goz", "urun", "urun_ad")},
                              "bas": _iso(bekleyen["bas"]), "bit": _iso(t0), "bos": bekleyen["bos"],
                              "sure_sn": round(depo.calisma_suresi(bekleyen["bas"], t0, g))})
                bekleyen = None
        mevcut = sn["dolu"] + sn["az"]
        n_alma = alma.get(k, 0)
        if n_alma >= 3 and mevcut >= 3600:
            oran, yontem = n_alma / mevcut, "goz"
        else:
            o = olc.get(k[0])
            duran = o["veri"].get(f"b:{k[1]}:duran", 0) if o else 0
            oran = (duran / o["sure_sn"]) * donusum / max(1, bolge_goz[(k[0], k[1])]) if o and o["sure_sn"] else 0.0
            yontem = "bolge"
        kayip = sn["bos"] * oran
        gozler.append({**t, "bos_sn": round(sn["bos"]), "az_sn": round(sn["az"]), "dolu_sn": round(sn["dolu"]), "yanlis_sn": round(sn["yanlis"]),
                       "izlenen_sn": round(sum(sn.values())), "alma": n_alma, "kayip_adet": round(kayip, 1),
                       "kayip_tutar": round(kayip * t["fiyat"], 2) if t.get("fiyat") else None, "yontem": yontem,
                       "bekleyen": _iso(bekleyen["bas"]) if bekleyen else None})
    sureler = sorted(d["sure_sn"] for d in dolum)
    toplam = {
        "bos_sn": sum(x["bos_sn"] for x in gozler), "kayip_adet": round(sum(x["kayip_adet"] for x in gozler), 1),
        "kayip_tutar": round(sum(x["kayip_tutar"] or 0 for x in gozler), 2), "dolum_sayi": len(sureler),
        "dolum_ort_sn": round(sum(sureler) / len(sureler)) if sureler else None,
        "dolum_medyan_sn": round(statistics.median(sureler)) if sureler else None,
        "dolum_p90_sn": round(sureler[min(len(sureler) - 1, int(0.9 * len(sureler)))]) if sureler else None,
        "donusum": round(donusum, 3),
    }
    return {"gozler": gozler, "dolum": dolum, "matris": [[round(v, 1) for v in s] for s in matris],
            "saatlik_bos_dk": [round(sum(matris[d][h] for d in range(7)), 1) for h in range(24)], "toplam": toplam}


def _simdi_sayilari(tanim: dict[tuple, dict], son: dict[tuple, dict]) -> dict:
    """Gözlerin şu anki durumu: sayılar, ortalama doluluk ve planogram uyumu (beklenen ürünü taşıyan gözlerin oranı,
    ürünü tanımlı ve durumu bilinen gözler içinde)."""
    say = defaultdict(int)
    doluluk, uyum_pay, uyum_payda = [], 0, 0
    for k, t in tanim.items():
        s = son.get(k)
        durum = s["durum"] if s else "tanimsiz"
        say[durum] += 1
        if s and s["etiket"] in ("farkli", "yok"):
            say["etiket_sorun"] += 1
        if durum in BILINEN:
            doluluk.append(s["doluluk"] if s["doluluk"] is not None else (0.0 if durum == "bos" else 1.0 if durum == "dolu" else 0.3))
            if t.get("urun"):
                uyum_payda += 1
                uyum_pay += durum in ("dolu", "az") and (not s["gorulen"] or s["gorulen"] == t["urun"])
    return {"sayilar": {"goz": len(tanim), **say}, "doluluk": round(sum(doluluk) / len(doluluk), 3) if doluluk else None,
            "uyum": round(uyum_pay / uyum_payda, 3) if uyum_payda else None}


def _son_durumlar(kamera: str | None = None) -> dict[tuple, dict]:
    return {(r["kamera"], r["bolge"], r["goz"]): r for r in depo.sor("SELECT * FROM raf_son" + (" WHERE kamera = ?" if kamera else ""), *([kamera] if kamera else []))}


def _raf_egilimi(bas: str, bit: str, kamera: str | None = None) -> list[dict]:
    """Doluluk ve planogram uyumu: iki günden kısa dönemde saatlik, değilse günlük ortalama (raf_ozet)."""
    saatlik = (_t(bit) - _t(bas)).total_seconds() <= 2 * 86400
    uzun = 13 if saatlik else 10
    ek, p = (" AND kamera = ?", [kamera]) if kamera else ("", [])
    rows = depo.sor(f"SELECT substr(zaman, 1, {uzun}) AS d, AVG(doluluk) AS doluluk, AVG(uyum) AS uyum, COUNT(*) AS n FROM raf_ozet "
                    f"WHERE zaman >= ? AND zaman <= ?{ek} GROUP BY d ORDER BY d", bas, bit, *p)
    return [{"d": r["d"] + (":00" if saatlik else ""), "doluluk": round(r["doluluk"], 3) if r["doluluk"] is not None else None,
             "uyum": round(r["uyum"], 3) if r["uyum"] is not None else None} for r in rows]


def _kare_adresi(kod: str) -> str | None:
    """Raf / ısı haritası arka planı: motorun temiz karesi (yüzler gizli, çizim yok), yoksa referans karesi, yoksa son kare
    (yüzler gizli ama motorun çizimleri üstünde). Bağlantı denemesinin ham karesi burada gösterilmez."""
    for yol, adres in ((yollar.CIKTI / kod / "temiz_kare.jpg", f"/cikti/{kod}/temiz_kare.jpg"), (yollar.AYAR / f"_referans_{kod}.jpg", f"/ayar/_referans_{kod}.jpg"),
                       (yollar.CIKTI / kod / "son_kare.jpg", f"/cikti/{kod}/son_kare.jpg")):
        if yol.exists():
            return f"{adres}?t={yol.stat().st_mtime_ns // 1_000_000}"
    return None


def raflar(q: dict) -> dict:
    """Raflar ekranı: raf kameraları, seçili kameranın bölgeleri ve gözleri (şu anki durum + dönem ölçüleri)."""
    bas, bit = aralik(q)
    tum = ayarlar()
    raf_kameralari = [kod for kod, a in tum.items() if any(b.get("gozler") for b in a.get("bolgeler") or [])]
    kamera = q.get("kamera") if q.get("kamera") in raf_kameralari else (raf_kameralari[0] if raf_kameralari else None)
    ozetler = []
    son_tum = _son_durumlar()
    for kod in raf_kameralari:
        s = _simdi_sayilari(goz_tanimlari(kod, tum[kod]), son_tum)
        ozetler.append({"kod": kod, "ad": tum[kod].get("ad", kod), **s})
    if kamera is None:
        return {"bas": bas, "bit": bit, "kameralar": ozetler, "kamera": None}
    a = tum[kamera]
    urun = {u["kimlik"]: u for u in depo.urunler()}
    olc = raf_olculeri(bas, bit, kamera)
    olcu = {(x["bolge"], x["goz"]): x for x in olc["gozler"]}
    son = {(k[1], k[2]): v for k, v in son_tum.items() if k[0] == kamera}
    bolgeler = []
    for b in a.get("bolgeler") or []:
        gozler = []
        for gz in b.get("gozler") or []:
            s = son.get((b.get("kimlik"), gz.get("kimlik"))) or {}
            o = olcu.get((b.get("kimlik"), gz.get("kimlik"))) or {}
            u = urun.get(gz.get("urun")) or {}
            gozler.append({
                "kimlik": gz.get("kimlik"), "kutu": gz.get("kutu"), "etiket_kutu": gz.get("etiket"), "urun": gz.get("urun"), "urun_ad": u.get("ad"),
                "gorsel": (u.get("gorseller") or [None])[0], "adet": gz.get("adet"), "fiyat": gz.get("fiyat"),
                "durum": s.get("durum") or "tanimsiz", "doluluk": s.get("doluluk"), "gorulen_adet": s.get("adet"), "gorulen": s.get("gorulen"),
                "gorulen_ad": (urun.get(s.get("gorulen")) or {}).get("ad"), "benzerlik": s.get("benzerlik"), "etiket": s.get("etiket"),
                "okunan_fiyat": s.get("fiyat"), "degisim": s.get("degisim"), "zaman": s.get("zaman"),
                **{x: o.get(x) for x in ("bos_sn", "az_sn", "dolu_sn", "alma", "kayip_adet", "kayip_tutar", "yontem")},
            })
        bolgeler.append({"kimlik": b.get("kimlik"), "ad": b.get("ad"), "tur": b.get("tur"), "poly": b.get("poly"), "cizgi": b.get("cizgi"), "gozler": gozler})
    simdi_ = _simdi_sayilari(goz_tanimlari(kamera, a), son_tum)
    referans = depo.sor("SELECT referans FROM raf_ozet WHERE kamera = ? ORDER BY zaman DESC, id DESC LIMIT 1", kamera)
    kayit = a.get("referans") or {}
    return {
        "bas": bas, "bit": bit, "kameralar": ozetler, "kamera": kamera, "kamera_ad": a.get("ad", kamera), "kare": _kare_adresi(kamera),
        "bolgeler": bolgeler, **simdi_, "egilim": _raf_egilimi(bas, bit, kamera), "toplam": olc["toplam"], "matris": olc["matris"],
        "dolum": sorted(olc["dolum"], key=lambda d: d["bit"], reverse=True)[:50],
        "referans_gecici": bool(referans and referans[0]["referans"] == "gecici"),
        "referans": kayit or None,
        "referans_eski": bool(kayit and a.get("gozler_degisim") and a["gozler_degisim"] > kayit.get("zaman", "")),
    }


def goz_gecmisi(q: dict) -> dict:
    """Bir gözün geçmişi: durum aralıkları, doldurma süreleri, etkileşimler, okunan fiyatlar, olaylar."""
    bas, bit = aralik(q)
    kamera, goz = str(q.get("kamera") or ""), str(q.get("goz") or "")
    tanim = [t for k, t in goz_tanimlari(kamera).items() if k[2] == goz]
    if not tanim:
        raise SystemExit("Göz bulunamadı.")
    t = tanim[0]
    k = (kamera, t["bolge"], goz)
    araliklar = _araliklar(bas, bit, kamera).get(k, [])
    olc = raf_olculeri(bas, bit, kamera)
    o = next((x for x in olc["gozler"] if x["goz"] == goz and x["bolge"] == t["bolge"]), {})
    etk = depo.sor("SELECT substr(zaman, 1, 10) AS gun, eylem, COUNT(*) AS n FROM etkilesim WHERE kamera = ? AND goz = ? AND zaman >= ? AND zaman <= ? "
                   "GROUP BY gun, eylem ORDER BY gun", kamera, goz, bas, bit)
    gunluk: dict[str, dict] = {}
    for r in etk:
        gunluk.setdefault(r["gun"], {"gun": r["gun"], "durdu": 0, "uzandi": 0, "aldi": 0, "birakti": 0})[r["eylem"]] = r["n"]
    fiyatlar = depo.sor("SELECT zaman, fiyat, etiket FROM raf_durum WHERE kamera = ? AND goz = ? AND zaman <= ? AND (fiyat IS NOT NULL OR etiket IN ('yok', 'farkli', 'okunamadi')) "
                        "ORDER BY zaman DESC LIMIT 30", kamera, goz, bit)
    olaylar_ = depo.sor("SELECT id, zaman, kural, kural_ad, sure_sn, suruyor, durum, kare FROM olay WHERE kamera = ? AND goz = ? ORDER BY zaman DESC LIMIT 20", kamera, goz)
    return {
        "bas": bas, "bit": bit, **t, "olcu": o, "son": (_son_durumlar(kamera).get(k)),
        "araliklar": [{"bas": _iso(a), "bit": _iso(b), "durum": r["durum"], "etiket": r["etiket"], "fiyat": r["fiyat"], "gorulen": r["gorulen"]} for a, b, r in araliklar],
        "dolum": [d for d in olc["dolum"] if d["goz"] == goz and d["bolge"] == t["bolge"]],
        "etkilesim": list(gunluk.values()), "fiyatlar": fiyatlar, "olaylar": olaylar_,
    }


def urun_listesi(q: dict) -> dict:
    """Ürünler ekranı: katalog + her ürünün yerleri (kamera / bölge / göz), şu anki durumu ve dönem ölçüleri."""
    bas, bit = aralik(q)
    olc = raf_olculeri(bas, bit)
    son = _son_durumlar()
    yer = defaultdict(list)
    for x in olc["gozler"]:
        if x.get("urun"):
            s = son.get((x["kamera"], x["bolge"], x["goz"])) or {}
            yer[x["urun"]].append({**{a: x[a] for a in ("kamera", "kamera_ad", "bolge", "bolge_ad", "goz", "adet", "fiyat", "bos_sn", "alma", "kayip_adet", "kayip_tutar", "yontem")},
                                   "durum": s.get("durum") or "tanimsiz", "etiket": s.get("etiket"), "okunan_fiyat": s.get("fiyat")})
    liste = []
    for u in depo.urunler():
        y = yer.get(u["kimlik"], [])
        liste.append({**u, "yerler": y, "goz": len(y), "bos_simdi": sum(1 for v in y if v["durum"] == "bos"),
                      "az_simdi": sum(1 for v in y if v["durum"] == "az"), "bos_sn": sum(v["bos_sn"] for v in y), "alma": sum(v["alma"] for v in y),
                      "kayip_adet": round(sum(v["kayip_adet"] for v in y), 1), "kayip_tutar": round(sum(v["kayip_tutar"] or 0 for v in y), 2),
                      "fiyat_sorun": sum(1 for v in y if v["etiket"] in ("farkli", "yok"))})
    return {"bas": bas, "bit": bit, "urunler": liste, "toplam": olc["toplam"]}


def _histogram(degerler: list[float], sinirlar: list[float]) -> list[dict]:
    kutular = [{"alt": a, "ust": b, "n": 0} for a, b in zip([0.0] + sinirlar, sinirlar + [None])]
    for v in degerler:
        for k in kutular:
            if v >= k["alt"] and (k["ust"] is None or v < k["ust"]):
                k["n"] += 1
                break
    return kutular


def musteri(q: dict) -> dict:
    """Müşteri ekranı: yoğunluk haritası, huni, bekleme dağılımı, bölge karşılaştırması, giriş-çıkış, demografi (tahmin,
    yalnızca toplu sayılar), en yoğun saatler."""
    bas, bit = aralik(q)
    tum = ayarlar()
    kamera = q.get("kamera") if q.get("kamera") in tum else None
    olcumler = _olcumler(bas, bit, kamera, tam=True)
    toplam: dict[str, float] = defaultdict(float)
    bolge: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    saatlik = [{"saat": h, "giren": 0.0, "cikan": 0.0, "gecen": 0.0, "kuyruk": 0.0, "kuyruk_sn": 0.0} for h in range(24)]
    haftalik = [[0.0] * 24 for _ in range(7)]
    gunluk: dict[str, dict] = {}
    gunler = set()
    kuyruk_en_cok, giris_var = 0.0, False
    izgaralar: dict[str, dict] = {}
    for m in olcumler:
        try:
            veri = json.loads(m["veri"] or "{}")
        except ValueError:
            veri = {}
        if not isinstance(veri, dict):
            veri = {}
        an = _t(m["bas"])
        gunler.add(m["bas"][:10])
        s = saatlik[an.hour]
        g = gunluk.setdefault(m["bas"][:10], {"gun": m["bas"][:10], "giren": 0.0, "gecen": 0.0, "alan": 0.0})
        for ad, v in veri.items():
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            if ad.startswith("b:"):
                parca = ad.split(":")
                if len(parca) == 3:
                    bolge[(m["kamera"], parca[1])][parca[2]] += v
                continue
            if ad == "kuyruk_en_cok":
                kuyruk_en_cok = max(kuyruk_en_cok, v)
                continue
            if ad == "kuyruk_ort":
                s["kuyruk"] += v * (m["sure_sn"] or 0)
                s["kuyruk_sn"] += m["sure_sn"] or 0
                continue
            toplam[ad] += v
            if ad in ("giren", "cikan", "gecen"):
                s[ad] += v
            if ad in g:
                g[ad] += v
        giris_var = giris_var or "giren" in veri
        trafik = veri.get("giren") if "giren" in veri else 0
        haftalik[an.weekday()][an.hour] += trafik or 0
        iz = None
        if m["izgara"]:
            try:
                iz = json.loads(m["izgara"])
            except ValueError:
                iz = None
        if isinstance(iz, dict) and iz.get("gen") and iz.get("yuk"):
            hedef = izgaralar.setdefault(m["kamera"], {"gen": int(iz["gen"]), "yuk": int(iz["yuk"]), "katmanlar": {}})
            if hedef["gen"] == iz["gen"] and hedef["yuk"] == iz["yuk"]:
                for ad, hucre in (iz.get("katmanlar") or {}).items():
                    t = hedef["katmanlar"].setdefault(ad, [[0.0] * hedef["gen"] for _ in range(hedef["yuk"])])
                    for y in range(hedef["yuk"]):
                        for x in range(hedef["gen"]):
                            t[y][x] += hucre[y][x]
    if not giris_var:  # giriş sayımı yoksa haftalık yoğunluk "geçen" kişiden
        for m in olcumler:
            try:
                v = json.loads(m["veri"] or "{}").get("gecen", 0)
            except (ValueError, AttributeError):
                v = 0
            an = _t(m["bas"])
            haftalik[an.weekday()][an.hour] += v or 0
    harita_kamera = kamera if kamera in izgaralar else (next(iter(izgaralar)) if izgaralar else None)
    harita = izgaralar.get(harita_kamera) if harita_kamera else None
    if harita:
        for ad, t in harita["katmanlar"].items():
            harita["katmanlar"][ad] = [[round(v, 1) for v in s] for s in t]
    # bölge tablosu
    satirlar = []
    for (kod, bk), v in bolge.items():
        b = next((x for x in (tum.get(kod, {}).get("bolgeler") or []) if x.get("kimlik") == bk), None)
        if b is None:
            continue
        satirlar.append({"kamera": kod, "kamera_ad": tum[kod].get("ad", kod), "bolge": bk, "ad": b.get("ad") or bk, "tur": b.get("tur"),
                         **{a: round(v.get(a, 0)) for a in ("gecen", "duran", "uzanan", "alan", "birakan", "bekleme_sayi", "kadin", "erkek")},
                         "ilgi_sn": round(v.get("ilgi_sn", 0)),
                         "ort_bekleme_sn": round(v["bekleme_sn"] / v["bekleme_sayi"], 1) if v.get("bekleme_sayi") else None,
                         "durma_orani": round(v["duran"] / v["gecen"], 3) if v.get("gecen") else None,
                         "alma_orani": round(v["alan"] / v["gecen"], 3) if v.get("gecen") else None})
    satirlar.sort(key=lambda r: -r["gecen"])
    huni_kaynak = [r for r in satirlar if r["tur"] in ("raf", "dolap")] or satirlar
    huni = {a: (round(toplam.get(a, 0)) if kamera else sum(r[a] for r in huni_kaynak)) for a in ("gecen", "duran", "uzanan", "alan")}
    ek, p = (" AND kamera = ?", [kamera]) if kamera else ("", [])
    durmalar = [r["sure_sn"] for r in depo.sor(f"SELECT sure_sn FROM etkilesim WHERE eylem = 'durdu' AND sure_sn IS NOT NULL AND zaman >= ? AND zaman <= ?{ek}", bas, bit, *p)]
    gun_sayisi = max(1, len(gunler))
    demografi = {a: round(toplam.get(a, 0)) for a in ("kadin", "erkek", "yas_genc", "yas_yetiskin", "yas_yasli")}
    yogun = sorted(({"saat": s["saat"], "n": round(s["giren"] if giris_var else s["gecen"])} for s in saatlik), key=lambda x: -x["n"])
    return {
        "bas": bas, "bit": bit, "kamera": kamera, "gun_sayisi": gun_sayisi, "giris_var": giris_var,
        "toplam": {"giren": round(toplam.get("giren", 0)), "cikan": round(toplam.get("cikan", 0)), "gecen": round(toplam.get("gecen", 0)),
                   "ort_bekleme_sn": round(toplam["bekleme_sn"] / toplam["bekleme_sayi"], 1) if toplam.get("bekleme_sayi") else None,
                   "kuyruk_en_cok": round(kuyruk_en_cok) if kuyruk_en_cok else None},
        "huni": huni, "bolgeler": satirlar,
        "bekleme": {"n": len(durmalar), "ort": round(sum(durmalar) / len(durmalar), 1) if durmalar else None,
                    "medyan": round(statistics.median(durmalar), 1) if durmalar else None,
                    "dagilim": _histogram(durmalar, [5, 15, 30, 60, 120])},
        "saatlik": [{"saat": s["saat"], "giren": round(s["giren"] / gun_sayisi, 1), "cikan": round(s["cikan"] / gun_sayisi, 1),
                     "gecen": round(s["gecen"] / gun_sayisi, 1), "kuyruk": round(s["kuyruk"] / s["kuyruk_sn"], 2) if s["kuyruk_sn"] else None} for s in saatlik],
        "haftalik": [[round(v) for v in s] for s in haftalik], "gunluk": sorted(({**g, **{a: round(g[a]) for a in ("giren", "gecen", "alan")}} for g in gunluk.values()), key=lambda g: g["gun"]),
        "demografi": demografi, "yogun_saatler": [y for y in yogun[:3] if y["n"]],
        "harita": {"kamera": harita_kamera, "kare": _kare_adresi(harita_kamera) if harita_kamera else None, **(harita or {"gen": 0, "yuk": 0, "katmanlar": {}}),
                   "bolgeler": (tum.get(harita_kamera, {}).get("bolgeler") or []) if harita_kamera else []},
        "harita_kameralari": sorted(izgaralar),
    }


def _gorev_tepkileri(bas: str, bit: str) -> list[float]:
    return [r["tepki_sn"] for r in depo.sor("SELECT tepki_sn FROM gorev WHERE tepki_sn IS NOT NULL AND kapanma >= ? AND kapanma <= ?", bas, bit)]


def gorev_listesi(q: dict) -> dict:
    """Görevler (süzgeçli) ve tepki süresi istatistikleri. Tepki: görevin açılmasından kapanmasına kadar geçen süre."""
    bas, bit = aralik({"gun": q.get("gun", 30), **q})
    liste = gorevler()
    for alan in ("durum", "kamera", "kural", "sorumlu"):
        if q.get(alan):
            liste = [g for g in liste if str(g.get(alan) or "") == q[alan]]
    if q.get("kaynak") == "otomatik":
        liste = [g for g in liste if g.get("otomatik")]
    elif q.get("kaynak") == "elle":
        liste = [g for g in liste if not g.get("otomatik")]
    # kapananlar yalnızca dönem içindekiler (açıklar her zaman listede)
    liste = [g for g in liste if g["durum"] != "kapandi" or (g["kapanma"] or "") >= bas]
    tepki = sorted(_gorev_tepkileri(bas, bit))
    kural_tepki = defaultdict(list)
    for r in depo.sor("SELECT kural, tepki_sn FROM gorev WHERE tepki_sn IS NOT NULL AND kapanma >= ? AND kapanma <= ?", bas, bit):
        kural_tepki[r["kural"] or ""].append(r["tepki_sn"])
    sorumlular = sorted({g["sorumlu"] for g in gorevler() if g.get("sorumlu")})
    sayi = {d: depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE durum = ?", d)[0]["n"] for d in ("acik", "suruyor")}
    sayi["kapandi"] = depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE durum = 'kapandi' AND kapanma >= ? AND kapanma <= ?", bas, bit)[0]["n"]
    return {
        "bas": bas, "bit": bit, "gorevler": liste[:500], "toplam": len(liste), "sayilar": sayi, "sorumlular": sorumlular,
        "tepki": {"n": len(tepki), "ort_sn": round(sum(tepki) / len(tepki)) if tepki else None, "medyan_sn": round(statistics.median(tepki)) if tepki else None,
                  "p90_sn": round(tepki[min(len(tepki) - 1, int(0.9 * len(tepki)))]) if tepki else None,
                  "dagilim": _histogram([t / 60 for t in tepki], [5, 15, 30, 60, 120])},
        "kural_tepki": sorted(({"kural": k, "ad": kurallar.KURAL.get(k, {}).get("ad") or k or "Elle", "n": len(v), "ort_sn": round(sum(v) / len(v))}
                               for k, v in kural_tepki.items()), key=lambda r: -r["n"]),
        "geciken": sum(1 for g in liste if g.get("gecikti")),
    }


def _ziyaretci(olc: dict[str, dict]) -> int | None:
    giren = [o["veri"]["giren"] for o in olc.values() if "giren" in o["veri"]]
    return round(sum(giren)) if giren else None


def _bekleme(olc: dict[str, dict]) -> float | None:
    sn = sum(o["veri"].get("bekleme_sn", 0) for o in olc.values())
    n = sum(o["veri"].get("bekleme_sayi", 0) for o in olc.values())
    return round(sn / n, 1) if n else None


def _ortalama(liste: list[dict], alan: str) -> float | None:
    v = [x[alan] for x in liste if x.get(alan) is not None]
    return round(sum(v) / len(v), 3) if v else None


def genel_bakis(q: dict) -> dict:
    """Genel Bakış: şu anki raf durumu, dönem sayıları (önceki dönemle), dikkat isteyenler, kameralar ve grafikler."""
    bas, bit = aralik(q)
    g = depo.genel()
    obas, obit = onceki_donem(bas, bit)
    tanim = goz_tanimlari()
    son = _son_durumlar()
    simdi_ = _simdi_sayilari(tanim, son)
    olc, oolc = olcum_toplamlari(bas, bit), olcum_toplamlari(obas, obit)
    raf, oraf = raf_olculeri(bas, bit, g=g), raf_olculeri(obas, obit, g=g)
    kams = kameralar()
    tum = ayarlar()
    # kuyruk: kasa bölgesi olan kameraların son 15 dakikadaki son ölçümü
    simdi = dt.datetime.now()
    kuyruk_simdi = None
    for kod, a in tum.items():
        if any(b.get("tur") == "kasa" for b in a.get("bolgeler") or []):
            r = depo.sor("SELECT bas, veri FROM olcum WHERE kamera = ? AND bas >= ? ORDER BY bas DESC LIMIT 1", kod, _iso(simdi - dt.timedelta(minutes=15)))
            if r:
                try:
                    v = json.loads(r[0]["veri"]).get("kuyruk_ort")
                except (ValueError, AttributeError):
                    v = None
                if isinstance(v, (int, float)):
                    kuyruk_simdi = (kuyruk_simdi or 0) + v
    acik_gorev = depo.sor("SELECT COUNT(*) AS n FROM gorev WHERE durum != 'kapandi'")[0]["n"]
    # dikkat isteyenler
    dikkat = []
    for k, s in son.items():
        t = tanim.get(k)
        if t is None:
            continue
        if s["durum"] in ("bos", "az", "yanlis"):
            dikkat.append({"tur": s["durum"], "kamera": k[0], "kamera_ad": t["kamera_ad"], "bolge_ad": t["bolge_ad"], "goz": k[2],
                           "urun_ad": t.get("urun_ad"), "gorulen_ad": None, "zaman": s["degisim"], "oncelik": {"bos": 0, "yanlis": 2, "az": 3}[s["durum"]]})
        if s["etiket"] in ("farkli", "yok"):
            dikkat.append({"tur": "etiket_" + s["etiket"], "kamera": k[0], "kamera_ad": t["kamera_ad"], "bolge_ad": t["bolge_ad"], "goz": k[2],
                           "urun_ad": t.get("urun_ad"), "beklenen": t.get("beklenen_fiyat"), "okunan": s["fiyat"], "zaman": s["degisim"], "oncelik": 4})
    for o in depo.sor("SELECT id, zaman, kamera, kamera_ad, kural, kural_ad, bolge, deger, kare FROM olay WHERE suruyor = 1 AND durum = 'acik' "
                      "AND kategori = 'operasyon' ORDER BY zaman DESC LIMIT 10"):
        dikkat.append({"tur": "olay", **o, "oncelik": 1})
    for k in kams:
        if k["eski"]:
            dikkat.append({"tur": "eski", "kamera": k["kod"], "kamera_ad": k["ad"], "zaman": k["son_analiz"], "oncelik": 1})
    for gv in depo.sor("SELECT id, baslik, son_tarih, olusturma FROM gorev WHERE durum != 'kapandi' AND son_tarih IS NOT NULL AND son_tarih < ?", simdi.date().isoformat()):
        dikkat.append({"tur": "gorev_gecikti", **gv, "zaman": gv["olusturma"], "oncelik": 5})
    dikkat.sort(key=lambda d: (d["oncelik"], d.get("zaman") or ""))
    # grafikler: saatlik trafik (dönem ortalaması ve bugün) ve doluluk
    bugun = simdi.date().isoformat()
    saatlik = [{"saat": h, "ort": 0.0, "bugun": 0.0} for h in range(24)]
    gunler = set()
    alan = "giren" if _ziyaretci(olc) is not None else "gecen"
    for m in _olcumler(bas, bit):
        try:
            v = json.loads(m["veri"] or "{}").get(alan, 0)
        except (ValueError, AttributeError):
            v = 0
        if not isinstance(v, (int, float)):
            continue
        gunler.add(m["bas"][:10])
        saatlik[int(m["bas"][11:13])]["ort"] += v
        if m["bas"][:10] == bugun:
            saatlik[int(m["bas"][11:13])]["bugun"] += v
    for s in saatlik:
        s["ort"] = round(s["ort"] / max(1, len(gunler)), 1)
    a, b = depo.calisma_araligi(g)
    egilim = _raf_egilimi(bas, bit)
    return {
        "bas": bas, "bit": bit, "tesis": g["tesis"], "para": g.get("para_birimi") or "₺", "calisma": g.get("calisma"),
        "simdi": {**simdi_, "kuyruk": round(kuyruk_simdi, 1) if kuyruk_simdi is not None else None, "acik_gorev": acik_gorev},
        "donem": {"ziyaretci": _ziyaretci(olc), "ort_bekleme_sn": _bekleme(olc), "kuyruk_en_cok": max([o["kuyruk_en_cok"] for o in olc.values()] or [0]) or None,
                  "kayip_tutar": raf["toplam"]["kayip_tutar"], "kayip_adet": raf["toplam"]["kayip_adet"], "dolum_ort_sn": raf["toplam"]["dolum_ort_sn"],
                  "doluluk": _ortalama(egilim, "doluluk"), "uyum": _ortalama(egilim, "uyum"), "bos_sn": raf["toplam"]["bos_sn"]},
        "onceki": {"ziyaretci": _ziyaretci(oolc), "ort_bekleme_sn": _bekleme(oolc), "kayip_tutar": oraf["toplam"]["kayip_tutar"],
                   "kayip_adet": oraf["toplam"]["kayip_adet"], "dolum_ort_sn": oraf["toplam"]["dolum_ort_sn"],
                   "doluluk": _ortalama(_raf_egilimi(obas, obit), "doluluk")},
        "dikkat": dikkat[:30], "dikkat_toplam": len(dikkat), "kameralar": kams,
        "trafik": {"alan": alan, "saatlik": saatlik, "acilis": a // 60, "kapanis": (b + 59) // 60 if b > a else 24},
        "egilim": egilim, "en_kayip": _urune_gore_kayip(raf["gozler"])[:5],
    }


def _urune_gore_kayip(gozler: list[dict]) -> list[dict]:
    """Kayıp satış tahmini ürün başına (bir ürün birden çok gözde olabilir)."""
    urun: dict = {}
    for x in gozler:
        if x["kayip_adet"] <= 0:
            continue
        a = urun.setdefault(x.get("urun") or f"{x['kamera']}:{x['goz']}", {"urun": x.get("urun"), "urun_ad": x.get("urun_ad"), "goz": x["goz"],
                                                                          "kamera": x["kamera"], "kamera_ad": x["kamera_ad"], "kayip_adet": 0.0, "kayip_tutar": None})
        a["kayip_adet"] = round(a["kayip_adet"] + x["kayip_adet"], 1)
        if x["kayip_tutar"] is not None:
            a["kayip_tutar"] = round((a["kayip_tutar"] or 0) + x["kayip_tutar"], 2)
    return sorted(urun.values(), key=lambda a: -(a["kayip_tutar"] or a["kayip_adet"]))


def rapor_ozeti(q: dict) -> dict:
    """Raporlar ekranı: dönem ve önceki dönem karşılaştırması, günlük tablo, en çok kayıp, en çok boş kalan gözler."""
    bas, bit = aralik({"gun": q.get("gun", 7), **q})
    obas, obit = onceki_donem(bas, bit)
    g = depo.genel()

    def donem(a: str, b: str) -> dict:
        olc = olcum_toplamlari(a, b)
        raf = raf_olculeri(a, b, g=g)
        eg = _raf_egilimi(a, b)
        tep = _gorev_tepkileri(a, b)
        topla = lambda ad: round(sum(o["veri"].get(ad, 0) for o in olc.values()))  # noqa: E731
        return {"ziyaretci": _ziyaretci(olc), "gecen": topla("gecen"), "duran": topla("duran"), "alan": topla("alan"),
                "ort_bekleme_sn": _bekleme(olc), "doluluk": _ortalama(eg, "doluluk"), "uyum": _ortalama(eg, "uyum"),
                "bos_saat": round(raf["toplam"]["bos_sn"] / 3600, 1), "kayip_adet": raf["toplam"]["kayip_adet"], "kayip_tutar": raf["toplam"]["kayip_tutar"],
                "dolum_ort_sn": raf["toplam"]["dolum_ort_sn"], "dolum_sayi": raf["toplam"]["dolum_sayi"],
                "gorev_tepki_sn": round(sum(tep) / len(tep)) if tep else None, "gorev_kapanan": len(tep),
                "olay": depo.sor("SELECT COUNT(*) AS n FROM olay WHERE zaman >= ? AND zaman <= ? AND durum != 'yanlis'", a, b)[0]["n"],
                "kuyruk_en_cok": max([o["kuyruk_en_cok"] for o in olc.values()] or [0]) or None, "_raf": raf}

    su, once = donem(bas, bit), donem(obas, obit)
    raf = su.pop("_raf")
    once.pop("_raf")
    # günlük tablo
    gunluk = {d: {"gun": d, "giren": 0, "gecen": 0, "alan": 0, "olay": 0, "bos_dk": 0.0, "doluluk": None} for d in _gunler(bas, bit)}
    for m in _olcumler(bas, bit):
        try:
            v = json.loads(m["veri"] or "{}")
        except ValueError:
            v = {}
        x = gunluk.get(m["bas"][:10])
        if x and isinstance(v, dict):
            for a in ("giren", "gecen", "alan"):
                x[a] += v.get(a, 0) if isinstance(v.get(a, 0), (int, float)) else 0
    for r in depo.sor("SELECT substr(zaman, 1, 10) AS d, COUNT(*) AS n FROM olay WHERE zaman >= ? AND zaman <= ? AND durum != 'yanlis' GROUP BY d", bas, bit):
        if r["d"] in gunluk:
            gunluk[r["d"]]["olay"] = r["n"]
    for r in depo.sor("SELECT substr(zaman, 1, 10) AS d, AVG(doluluk) AS v FROM raf_ozet WHERE zaman >= ? AND zaman <= ? GROUP BY d", bas, bit):
        if r["d"] in gunluk and r["v"] is not None:
            gunluk[r["d"]]["doluluk"] = round(r["v"], 3)
    # günlük boş süre: göz aralıklarından
    for k, araliklar in _araliklar(bas, bit).items():
        for t0, t1, r in araliklar:
            if r["durum"] == "bos":
                for a, b in depo.calisma_parcalari(t0, t1, g):
                    for an, s in _saatlere(a, b):
                        x = gunluk.get(an.date().isoformat())
                        if x:
                            x["bos_dk"] += s / 60
    for x in gunluk.values():
        x["bos_dk"] = round(x["bos_dk"])
        for a in ("giren", "gecen", "alan"):
            x[a] = round(x[a])
    urun = defaultdict(lambda: {"kayip_adet": 0.0, "kayip_tutar": 0.0, "bos_sn": 0, "alma": 0})
    for x in raf["gozler"]:
        if x.get("urun"):
            u = urun[(x["urun"], x.get("urun_ad") or x["urun"])]
            u["kayip_adet"] += x["kayip_adet"]
            u["kayip_tutar"] += x["kayip_tutar"] or 0
            u["bos_sn"] += x["bos_sn"]
            u["alma"] += x["alma"]
    en_kayip = sorted(({"urun": k[0], "ad": k[1], **{a: round(v, 1) if isinstance(v, float) else v for a, v in u.items()}} for k, u in urun.items()),
                      key=lambda r: -(r["kayip_tutar"] or r["kayip_adet"]))[:10]
    en_bos = sorted((x for x in raf["gozler"] if x["bos_sn"] > 0), key=lambda x: -x["bos_sn"])[:10]
    return {"bas": bas, "bit": bit, "obas": obas, "obit": obit, "tesis": g["tesis"], "para": g.get("para_birimi") or "₺", "calisma": g.get("calisma"),
            "su": su, "once": once, "gunluk": list(gunluk.values()), "en_kayip": en_kayip,
            "en_bos": [{a: x[a] for a in ("kamera_ad", "bolge_ad", "goz", "urun_ad", "bos_sn", "kayip_adet", "kayip_tutar")} for x in en_bos],
            "saatlik_bos_dk": raf["saatlik_bos_dk"], "matris": raf["matris"]}


def _katla(s: str) -> str:
    return str(s or "").replace("İ", "i").replace("I", "ı").casefold()


def ara(q: dict) -> dict:
    """Genel arama: ürün (ad, barkod, kategori), göz (ürününün adı), bölge ve kamera adları."""
    metin = _katla(q.get("q", "")).strip()
    if len(metin) < 2:
        return {"sonuclar": []}
    out = []
    for u in depo.urunler():
        if any(metin in _katla(u.get(a)) for a in ("ad", "barkod", "kategori")):
            out.append({"tur": "urun", "kimlik": u["kimlik"], "ad": u["ad"], "alt": " · ".join(x for x in (u.get("kategori"), u.get("barkod")) if x)})
    tum = ayarlar()
    for k, t in goz_tanimlari().items():
        if t.get("urun_ad") and metin in _katla(t["urun_ad"]):
            out.append({"tur": "goz", "kamera": k[0], "goz": k[2], "ad": t["urun_ad"], "alt": f"{t['kamera_ad']} · {t['bolge_ad']} · göz {k[2]}"})
    for kod, a in tum.items():
        if metin in _katla(a.get("ad")) or metin in _katla(kod):
            out.append({"tur": "kamera", "kamera": kod, "ad": a.get("ad", kod), "alt": "kamera"})
        for b in a.get("bolgeler") or []:
            if metin in _katla(b.get("ad")):
                out.append({"tur": "bolge", "kamera": kod, "bolge": b.get("kimlik"), "bolge_tur": b.get("tur"), "ad": b.get("ad"), "alt": f"{a.get('ad', kod)} · bölge"})
    return {"sonuclar": out[:30]}


# ---------------------------------------------------------------- dışa aktarma (Excel / CSV)

def _dk_yaz(sn) -> float | None:
    return round(sn / 60, 1) if sn is not None else None


def disa_tablo(ad: str, q: dict) -> tuple[str, list[str], list[list]]:
    """Yöneticinin isteyebileceği tablolar: (başlık, sütunlar, satırlar)."""
    bas, bit = aralik(q)
    zaman = lambda s: (s or "").replace("T", " ")  # noqa: E731
    if ad == "tukenmeler":
        raf = raf_olculeri(bas, bit)
        satirlar = [[d["kamera_ad"], d["bolge_ad"], d["goz"], d.get("urun_ad") or "", zaman(d["bas"]), zaman(d["bit"]), _dk_yaz(d["sure_sn"]),
                     "boş" if d["bos"] else "azaldı"] for d in sorted(raf["dolum"], key=lambda d: d["bas"])]
        satirlar += [[x["kamera_ad"], x["bolge_ad"], x["goz"], x.get("urun_ad") or "", zaman(x["bekleyen"]), "doldurulmadı", None, "sürüyor"]
                     for x in raf["gozler"] if x["bekleyen"]]
        return "Stok tükenmeleri", ["Kamera", "Raf", "Göz", "Ürün", "Başladı", "Dolduruldu", "Tepki (dk, çalışma saati)", "Durum"], satirlar
    if ad == "gorevler":
        liste = [x for x in gorevler() if (x["olusturma"] or "") <= bit and (x["durum"] != "kapandi" or (x["kapanma"] or "") >= bas)]
        return "Görevler", ["No", "Başlık", "Kamera", "Sorumlu", "Durum", "Açıldı", "Başladı", "Kapandı", "Tepki (dk)", "Kaynak", "Not"], [
            [x["id"], x["baslik"], x.get("kamera") or "", x.get("sorumlu") or "", {"acik": "açık", "suruyor": "sürüyor", "kapandi": "kapandı"}.get(x["durum"], x["durum"]),
             zaman(x["olusturma"]), zaman(x.get("baslama")), zaman(x.get("kapanma")), _dk_yaz(x.get("tepki_sn")), "otomatik" if x.get("otomatik") else "elle",
             x.get("notlar") or ""] for x in liste]
    if ad == "kayip-satis":
        u = urun_listesi(q)
        return "Kayıp satış (tahmin)", ["Ürün", "Barkod", "Göz sayısı", "Boş süre (saat)", "Alma", "Tahmini kayıp adet", "Tahmini kayıp tutar"], [
            [x["ad"], x.get("barkod") or "", x["goz"], round(x["bos_sn"] / 3600, 2), x["alma"], x["kayip_adet"], x["kayip_tutar"]]
            for x in sorted(u["urunler"], key=lambda x: -(x["kayip_tutar"] or x["kayip_adet"]))]
    if ad == "trafik":
        satirlar: dict[tuple, dict] = {}
        for m in _olcumler(bas, bit):
            try:
                v = json.loads(m["veri"] or "{}")
            except ValueError:
                v = {}
            x = satirlar.setdefault((m["bas"][:10], int(m["bas"][11:13])), defaultdict(float))
            for a in ("giren", "cikan", "gecen", "duran", "alan"):
                if isinstance(v.get(a), (int, float)):
                    x[a] += v[a]
            if isinstance(v.get("kuyruk_en_cok"), (int, float)):
                x["kuyruk"] = max(x["kuyruk"], v["kuyruk_en_cok"])
        return "Saatlik trafik", ["Gün", "Saat", "Giren", "Çıkan", "Geçen (kamera)", "Duran", "Alan", "En uzun kuyruk"], [
            [d, f"{h:02d}:00", round(x["giren"]), round(x["cikan"]), round(x["gecen"]), round(x["duran"]), round(x["alan"]), round(x["kuyruk"]) or None]
            for (d, h), x in sorted(satirlar.items())]
    if ad == "olaylar":
        liste = _olaylar(bas, bit, yanlislar=True)
        return "Uyarılar", ["No", "Zaman", "Kamera", "Özellik", "Bölge", "Ürün", "Düzey", "Süre (dk)", "Durum", "Üstlenen", "Not"], [
            [o["id"], zaman(o["zaman"]), o["kamera_ad"], o["kural_ad"], o.get("bolge") or "", o.get("urun_ad") or "", o["duzey"], _dk_yaz(o["sure_sn"]),
             o["durum"], o.get("ustlenen") or "", o.get("notlar") or ""] for o in liste]
    raise SystemExit("Bilinmeyen tablo.")


DISA_TABLOLAR = ("tukenmeler", "gorevler", "kayip-satis", "trafik", "olaylar")


def disa_csv(ad: str, q: dict) -> str:
    baslik, sutunlar, satirlar = disa_tablo(ad, q)
    tampon = io.StringIO()
    yaz = csv.writer(tampon, delimiter=";", lineterminator="\n")
    yaz.writerow(sutunlar)
    for s in satirlar:
        yaz.writerow(["" if v is None else (str(v).replace(".", ",") if isinstance(v, float) else v) for v in s])
    return tampon.getvalue()


def disa_excel(adlar: list[str], q: dict) -> Path:
    """Bir ya da birden çok tabloyu tek Excel dosyasına yazar (her tablo ayrı sayfa)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    bas, bit = aralik(q)
    kitap = Workbook()
    kitap.remove(kitap.active)
    for ad in adlar:
        baslik, sutunlar, satirlar = disa_tablo(ad, q)
        s = kitap.create_sheet(baslik[:31])
        s.append(sutunlar)
        for satir in satirlar:
            s.append(satir)
        for h in s[1]:
            h.font = Font(bold=True)
        for sutun in s.columns:
            s.column_dimensions[sutun[0].column_letter].width = min(42, max(10, max(len(str(h.value or "")) for h in sutun) + 2))
    yollar.CIKTI.mkdir(parents=True, exist_ok=True)
    ad = adlar[0] if len(adlar) == 1 else "rapor"
    hedef = yollar.CIKTI / f"raf-kamera-{ad}-{bas[:10]}-{bit[:10]}.xlsx"
    kitap.save(hedef)
    return hedef
