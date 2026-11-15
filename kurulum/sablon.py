"""Geliştirici aracı: programla gelen hazır sahneyi (kurulum/sahne/raf-kamera.pmod) yeniden üretir.

Sahne dosyası yalnızca Studio penceresindeki Dosya → Farklı Kaydet ile kaydedilir.
Bu yüzden sahne bir kez, geliştirici bilgisayarında açık Studio'da kurulur:

    1. AugeLab Studio'yu açın (MCP varsayılan 127.0.0.1:8765 adresinde açık olmalı).
    2. python kurulum/sablon.py           → Raf bloklarını Studio'ya kaydeder ve sahneyi yeni bir sekmede kurar
    3. Studio'da o sekmeyi Dosya → Farklı Kaydet ile kurulum/sahne/raf-kamera.pmod olarak kaydedin.

Sahne dört Raf bloğundan oluşur: Raf Video → Raf Kişi → Raf Ürün → Raf Analiz. Kamera kodunu dördüne de veren bir
metin girişi de vardır; arayüzsüz koşuda o değer yok sayılır (kamera ortam değişkeninden gelir).

Blok tanımları (studio_blok.py) değiştiğinde sahneyi yeniden üretmek gerekmez: bloklar sahneye adlarıyla bağlıdır ve panel
blok dosyalarını her çalıştırmada günceller. Yalnızca giriş/çıkış sayısı ya da sırası değişirse yeniden üretin.
Kullanıcı bilgisayarında bu araç çalışmaz; orada sahne Studio penceresi açılmadan çalıştırılır (studio.py).
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import studio_blok  # noqa: E402

ADRES = "http://127.0.0.1:8765/mcp"
OP_METIN = "119"  # String Input
KOD_BASLIGI = "Raf Kamera Kodu"
SAHNE_KODU = "RAF"  # arayüzsüz koşuda yok sayılır: kamera ortam değişkeninden gelir (raf_motor.blok.ORTAM_KAMERA)


def _anahtar() -> str:
    return "raf-" + secrets.token_hex(12)


async def cagir(arac: str, arg: dict[str, Any]) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(ADRES) as (oku, yaz, *_):
        async with ClientSession(oku, yaz) as oturum:
            await oturum.initialize()
            sonuc = await oturum.call_tool(arac, arg)
    yuk = getattr(sonuc, "structuredContent", None) or getattr(sonuc, "structured_content", None) or {}
    if not yuk and sonuc.content:
        try:
            yuk = json.loads(getattr(sonuc.content[0], "text", "") or "{}")
        except ValueError:
            yuk = {"error": getattr(sonuc.content[0], "text", "")}
    if getattr(sonuc, "isError", False) or getattr(sonuc, "is_error", False) or yuk.get("error"):
        raise SystemExit(f"{arac}: {json.dumps(yuk.get('error') or yuk, ensure_ascii=False)[:500]}")
    veri = dict(yuk.get("data") or {})
    if yuk.get("operation") and "operation" not in veri:
        veri["operation"] = yuk["operation"]
    return veri


async def bekle(veri: dict[str, Any], sinir_sn: float) -> dict[str, Any]:
    is_ = veri.get("operation") or veri
    bas = time.monotonic()
    while is_.get("state") in ("queued", "running") and time.monotonic() - bas < sinir_sn:
        dahasi = await cagir("operation.get", {"operationId": is_["id"], "waitTimeoutMs": 15000, "updateLimit": 1})
        is_ = dahasi.get("operation") or dahasi
    return is_


def sahne_kaynagi() -> str:
    b = studio_blok
    return "\n".join([
        f"kod = node('{OP_METIN}', title='{KOD_BASLIGI}')",
        f"kaynak = node('{b.VIDEO_OP}', title='{b.VIDEO_BASLIK}')",
        f"kisi = node('{b.KISI_OP}', title='{b.KISI_BASLIK}')",
        f"urun = node('{b.URUN_OP}', title='{b.URUN_BASLIK}')",
        f"analiz = node('{b.ANALIZ_OP}', title='{b.ANALIZ_BASLIK}')",
        f"kod.params['threshold'] = '{SAHNE_KODU}'",
        "connect(kod.out[0], kaynak.in_[0])",       # Kamera
        "connect(kaynak.out[0], kisi.in_[0])",      # Image
        "connect(kod.out[0], kisi.in_[1])",         # Kamera
        "connect(kaynak.out[1], kisi.in_[2])",      # Zaman
        "connect(kaynak.out[0], urun.in_[0])",      # Image
        "connect(kod.out[0], urun.in_[1])",         # Kamera
        "connect(kaynak.out[1], urun.in_[2])",      # Zaman
        "connect(kaynak.out[0], analiz.in_[0])",    # Image
        "connect(kisi.out[0], analiz.in_[1])",      # Kisiler
        "connect(urun.out[0], analiz.in_[2])",      # Raf
        "connect(kod.out[0], analiz.in_[3])",       # Kamera
        "connect(kaynak.out[1], analiz.in_[4])",    # Zaman
        "connect(kaynak.out[2], analiz.in_[5])",    # Bitti
    ]) + "\n"


async def main() -> None:
    is_ = await bekle(await cagir("node.custom.create", {"specifications": studio_blok.TANIMLAR, "replaceExisting": True,
                                                          "idempotencyKey": _anahtar()}), 120)
    if is_.get("state") != "succeeded":
        raise SystemExit(f"Raf blokları Studio'ya eklenemedi: {is_.get('error') or is_.get('state')}")
    veri = await cagir("graph.program", {"target": "create_new", "expectedRevision": "none", "idempotencyKey": _anahtar(),
                                         "source": sahne_kaynagi()})
    hedef = Path(__file__).resolve().parent / "sahne" / "raf-kamera.pmod"
    print(f"Sahne Studio'da kuruldu (sahne {veri.get('scene')}). Studio'da bu sekmeyi Dosya → Farklı Kaydet ile şuraya kaydedin:\n  {hedef}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
