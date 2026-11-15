"""Motor sınamalarının ortak yardımcısı: Studio olmadan dört bloğu zincir hâlinde çalıştırır.

Studio'nun yaptığı gibi: blokların _process kodu studio_blok tanımlarından üretilir, motor (raf_motor + modeller) geçici bir
"marketplace" klasöründe custom_blocks'un yanına (raf_engine) konur. Gerçek videolar depoya kopyalanmaz: klasörleri
RAF_DENEME_VIDEOLARI ortam değişkeninden okunur.

  zincir = Zincir()                       # geçici klasör, motor kopyası
  zincir.kamera("k1", "video.mp4", bolgeler=[...], ozellikler={...})
  for adim in zincir.calistir("k1"): ...  # her kare: {"v", "k", "u", "a"} blok çıkışları
  zincir.kayitlar()                       # kuyruktaki kayıtlar
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

import studio_blok  # noqa: E402

ORTAM_VIDEOLAR = "RAF_DENEME_VIDEOLARI"


def video_klasoru() -> Path | None:
    yol = os.environ.get(ORTAM_VIDEOLAR, "")
    return Path(yol) if yol and Path(yol).is_dir() else None


class Zincir:
    def __init__(self, on_ek: str = "raf_motor_"):
        for ad in [m for m in sys.modules if m == "raf_motor" or m.startswith("raf_motor.")]:
            del sys.modules[ad]  # önceki zincirin (silinmiş) motor kopyası kullanılmasın
        sys.path[:] = [p for p in sys.path if Path(p).name not in ("raf_engine", "deps") or "raf_engine" not in p]
        self.gecici = Path(tempfile.mkdtemp(prefix=on_ek))
        self.veri = self.gecici / "veri"
        os.environ["RAF_KAMERA_VERI"] = str(self.veri)
        self.market = self.gecici / "marketplace"
        (self.market / "custom_blocks").mkdir(parents=True)
        self.motor = self.market / studio_blok.MOTOR_KLASORU
        shutil.copytree(KOK / "motor" / "raf_motor", self.motor / "raf_motor", ignore=shutil.ignore_patterns("__pycache__"))
        if (KOK / "motor" / "modeller").is_dir():
            shutil.copytree(KOK / "motor" / "modeller", self.motor / "modeller")
        # deps (onnxruntime): studio.motoru_yerlestir gibi raf_engine/deps; motor/deps yoksa RAF_DEPS ortam değişkeni
        deps = KOK / "motor" / "deps"
        if not deps.is_dir() and os.environ.get("RAF_DEPS"):
            deps = Path(os.environ["RAF_DEPS"])
        if deps.is_dir():
            shutil.copytree(deps, self.motor / "deps", ignore=shutil.ignore_patterns("__pycache__"))
        (self.motor / "surum.txt").write_text("sinama", encoding="ascii")
        (self.motor / "ayar.json").write_text(json.dumps({"veri": str(self.veri)}), encoding="utf-8")
        (self.veri / "ayar").mkdir(parents=True)
        self.V, self.K, self.U, self.A = (self._islev(t) for t in studio_blok.TANIMLAR)

    def _islev(self, tanim):
        govde = "".join("    " + s + "\n" if s.strip() else "\n" for s in tanim["processCode"].rstrip("\n").split("\n"))
        ad_alani = {"__file__": str(self.market / "custom_blocks" / (tanim["opCode"] + ".py"))}
        exec("import sys, os, importlib\ndef _process(inputs, parameters, state, outputs):\n" + govde, ad_alani)
        return ad_alani["_process"]

    @staticmethod
    def _cagir(islev, state, **girdiler):
        outputs = {}
        islev(girdiler, {}, state, outputs)
        return outputs

    def kamera(self, kod: str, video: str, bolgeler=(), ozellikler=None, **ek) -> None:
        a = {"kod": kod, "ad": kod, "kamera": {"tur": "dosya", "yol": str(video), "baslangic": "2026-11-15T10:00:00"},
             "bolgeler": list(bolgeler), "ozellikler": ozellikler or {}, **ek}
        (self.veri / "ayar" / f"{kod}.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")

    def calistir(self, kod: str, kosu: str = "k1", en_cok: int | None = None):
        sv, sk, su, sa = {}, {}, {}, {}
        self.durumlar = (sv, sk, su, sa)
        kam = f"{kod}#{kosu}"
        n = 0
        while True:
            v = self._cagir(self.V, sv, Kamera=kam)
            k = self._cagir(self.K, sk, Image=v["Image"], Kamera=kam, Zaman=v["Zaman"])
            u = self._cagir(self.U, su, Image=v["Image"], Kamera=kam, Zaman=v["Zaman"])
            a = self._cagir(self.A, sa, Image=v["Image"], Kisiler=k["Kisiler"], Raf=u["Raf"], Kamera=kam, Zaman=v["Zaman"],
                            Bitti=v["Bitti"])
            yield {"v": v, "k": k, "u": u, "a": a}
            n += v["Image"] is not None
            if v["Bitti"] or (v["Image"] is None and not v["Bitti"] and str(v["Durum"]).startswith(("hata", "bitti"))):
                break
            if en_cok is not None and n >= en_cok:
                # erken bitir: Studio'nun durdurma dosyası gibi
                dur = self.gecici / f"{kod}.dur"
                dur.write_text("", encoding="ascii")
                os.environ["RAF_DUR"] = str(dur)
                en_cok = None
        os.environ.pop("RAF_DUR", None)

    def blok(self):
        return sys.modules["raf_motor.blok"]

    def kayitlar(self, tur: str | None = None) -> list[dict]:
        out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.veri / "kuyruk").glob("*.json"))]
        return [k for k in out if tur is None or k.get("tur") == tur]

    def temizle(self) -> None:
        shutil.rmtree(self.gecici, ignore_errors=True)
