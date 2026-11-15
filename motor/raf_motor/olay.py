"""Olay yöneticisi: bir özelliğin koşulu `sure_sn` boyunca sürünce olay BAŞLAR, sürdükçe aynı kimlikle güncellenir, koşul
`bosluk` saniyeden uzun süre görülmeyince KAPANIR (bitti: true). Kayıtlar Kayitci.kare'ye {"baslayan", "suren", "biten"}
olarak verilir (sözleşme 4.1 alanları)."""
from __future__ import annotations

import datetime as dt
import uuid

from . import katalog


class Olaylar:
    def __init__(self, kod: str, ayar: dict, bas_zaman: dt.datetime, W: int, H: int, bosluk: float = 3.0):
        self.k = katalog.KURAL[kod]
        self.ayar = ayar
        self.sure = float(ayar.get("sure_sn", 0.0))
        self.bosluk = bosluk
        self.bas_zaman, self.W, self.H = bas_zaman, W, H
        self.aday: dict = {}   # anahtar → {"bas", "son", "olay" | None, "bilgi"}

    def _kayit(self, a: dict, t: float, bitti: bool) -> dict:
        b = a["bilgi"]
        bolge = b.get("bolge") or {}
        sure = max(0.0, t - a["bas"])
        olas = katalog.olasilik(sure, self.k.get("taban", 3))
        x, y = b.get("xy") or (0.5 * self.W, 0.5 * self.H)
        o = {"kimlik": a["olay"], "bitti": bitti, "kural": self.k["kod"], "kural_ad": self.k["ad"], "kategori": self.k["kategori"],
             "duzey": self.k.get("duzey", "orta"), "onem": int(self.k.get("onem", 2)), "olasilik": olas,
             "puan": katalog.risk(self.k.get("onem", 2), olas), "ciddi": int(bool(self.k.get("ciddi"))),
             "gorev": bool(self.k.get("gorev")), "bolge": bolge.get("kimlik"), "bolge_ad": bolge.get("ad"),
             "zaman": (self.bas_zaman + dt.timedelta(seconds=a["bas"])).replace(microsecond=0).isoformat(),
             "sure_sn": round(sure, 1), "x": round(min(1.0, max(0.0, x / self.W)), 4), "y": round(min(1.0, max(0.0, y / self.H)), 4),
             "aciklama": b.get("aciklama") or self.k["aciklama"]}
        for alan in ("deger", "beklenen", "goz", "urun", "urun_ad"):
            if b.get(alan) is not None:
                o[alan] = b[alan]
        return o

    def guncelle(self, t: float, aktif: dict) -> tuple[list[dict], list[dict], list[dict]]:
        """aktif: {anahtar: {"bolge": bölge, "xy": (x, y) piksel, "deger": sayı, "aciklama": metin, ...}} bu karede koşulu
        sağlayanlar. Dönüş: (başlayan, süren, biten) kayıtlar."""
        baslayan, suren, biten = [], [], []
        for anahtar, bilgi in aktif.items():
            a = self.aday.get(anahtar)
            if a is None:
                a = self.aday[anahtar] = {"bas": t, "son": t, "olay": None, "bilgi": bilgi}
            a["son"], a["bilgi"] = t, bilgi
            if a["olay"] is None and t - a["bas"] >= self.sure:
                a["olay"] = uuid.uuid4().hex
                baslayan.append(self._kayit(a, t, False))
            elif a["olay"] is not None:
                suren.append(self._kayit(a, t, False))
        for anahtar in [k for k, a in self.aday.items() if k not in aktif and t - a["son"] > self.bosluk]:
            a = self.aday.pop(anahtar)
            if a["olay"] is not None:
                biten.append(self._kayit(a, a["son"], True))
        return baslayan, suren, biten

    def acik(self) -> list[dict]:
        return [a for a in self.aday.values() if a["olay"] is not None]

    def bitir(self) -> list[dict]:
        biten = [self._kayit(a, a["son"], True) for a in self.aday.values() if a["olay"] is not None]
        self.aday = {}
        return biten
