"""Örnek veri üreticisinin eski yeri; asıl kod programla birlikte paketlenen ornek_uretici.py'dedir.

  python egitim/ornek_veri.py            # yükle (veri klasörü: RAF_KAMERA_VERI, yoksa ./veri)
  python egitim/ornek_veri.py --kaldir   # yalnızca örnek verileri kaldır
"""
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parent.parent
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from ornek_uretici import *  # noqa: E402,F401,F403
from ornek_uretici import URUNLER, kaldir, yukle  # noqa: E402,F401

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(kaldir() if "--kaldir" in sys.argv else yukle())
