"""PP-OCR tanıma modelinin .yml dosyasındaki karakter listesini motorun okuduğu düz metne çevirir.

Kullanım: python egitim/raf/harf_listesi.py <model.yml> [<çıktı.txt>]
Çıktı varsayılanı motor/modeller/etiket-oku.txt: satır başına bir karakter, UTF-8. Model sözlüğün sonuna boşluğu
kendisi ekler (indeks 0 = boş/blank, son indeks = boşluk); motor bunu raf_modeller.harfleri_oku içinde yapar.
"""
from __future__ import annotations

import os
import sys

import yaml

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        y = yaml.safe_load(f)
    harfler = y["PostProcess"]["character_dict"]
    if any(len(h) != 1 or h in "\r\n" for h in harfler):
        print("beklenmeyen karakter girdisi")
        return 1
    hedef = sys.argv[2] if len(sys.argv) > 2 else os.path.join(KOK, "motor", "modeller", "etiket-oku.txt")
    with open(hedef, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(harfler) + "\n")
    print(f"{len(harfler)} karakter -> {os.path.basename(hedef)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
