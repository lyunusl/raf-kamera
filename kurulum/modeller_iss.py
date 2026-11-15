"""kurulum/modeller.iss dosyasını studio_kurulum.MODELLER tablosundan üretir (Inno kurulumu ve panel aynı modelleri,
aynı adres ve SHA-256 özetiyle indirsin diye tablo tek yerde tutulur).

  python kurulum/modeller_iss.py           dosyayı yazar
  python kurulum/modeller_iss.py --denetle dosya tabloyla aynı değilse 1 ile çıkar (derle.cmd ve sınamalar)
"""
from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import studio_kurulum  # noqa: E402

HEDEF = Path(__file__).resolve().with_name("modeller.iss")


def _pascal(metin: str) -> str:
    return "'" + str(metin).replace("'", "''") + "'"


def metin() -> str:
    satirlar = [
        "// Bu dosyayı kurulum/modeller_iss.py üretir (studio_kurulum.MODELLER). Elle değiştirmeyin.",
        "// RafKamera.iss bunu [Code] bölümüne ekler: ModelleriTanimla, indirilecek modellerin listesini kurar.",
        "procedure ModelleriTanimla();",
        "begin",
        f"  SetArrayLength(ModelAdlari, {len(studio_kurulum.MODELLER)});",
        f"  SetArrayLength(ModelBoyutlari, {len(studio_kurulum.MODELLER)});",
        f"  SetArrayLength(ModelOzetleri, {len(studio_kurulum.MODELLER)});",
        f"  SetArrayLength(ModelAdresleri, {len(studio_kurulum.MODELLER)});",
    ]
    for i, m in enumerate(studio_kurulum.MODELLER):
        satirlar += [
            f"  ModelAdlari[{i}] := {_pascal(m['ad'])};",
            f"  ModelBoyutlari[{i}] := {int(m['boyut'])};",
            f"  ModelOzetleri[{i}] := {_pascal(m['sha256'])};",
            f"  ModelAdresleri[{i}] := {_pascal(studio_kurulum.model_url(m))};",
        ]
    satirlar.append("end;")
    return "\n".join(satirlar) + "\n"


if __name__ == "__main__":
    beklenen = metin()
    if "--denetle" in sys.argv[1:]:
        mevcut = HEDEF.read_text(encoding="utf-8") if HEDEF.is_file() else ""
        if mevcut != beklenen:
            print("kurulum/modeller.iss studio_kurulum.MODELLER ile aynı değil: python kurulum/modeller_iss.py çalıştırın.")
            raise SystemExit(1)
        print("kurulum/modeller.iss güncel.")
    else:
        HEDEF.write_text(beklenen, encoding="utf-8", newline="\n")
        print(HEDEF.name, "yazıldı:", len(studio_kurulum.MODELLER), "model")
