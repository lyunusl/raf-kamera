"""Raf Kamera'nın AugeLab Studio'ya kaydettiği özel bloklar.

Studio her bloğun dosyasını bu tanımlardan kendisi üretir (node.custom.create). Bloklar incedir: asıl iş, Studio'nun özel
blok klasörünün yanına konan "raf_engine" klasöründeki raf_motor paketindedir (modeller ve onnxruntime de orada).
Studio'nun kendi ortamına hiçbir paket kurulmaz; motorun ek kütüphaneleri sys.path'in SONUNA eklenir.

Sahne:  Raf Video → Raf Kişi → Raf Ürün → Raf Analiz  (kamera kodu dördüne de aynı metin girişinden gelir)
"""
from __future__ import annotations

MOTOR_KLASORU = "raf_engine"  # Studio'nun custom_blocks klasörünün kardeşi
VIDEO_OP = "RafVideo"
VIDEO_BASLIK = "Raf Video"
KISI_OP = "RafKisi"
KISI_BASLIK = "Raf Kişi"
URUN_OP = "RafUrun"
URUN_BASLIK = "Raf Ürün"
ANALIZ_OP = "RafAnaliz"
ANALIZ_BASLIK = "Raf Analiz"

# Dört blokta da aynı: motoru bul, sürümü değiştiyse yeniden yükle.
_YUKLE = """\
klasor = state.get('klasor')
if klasor is None:
    here = globals().get('__file__')
    if here:
        klasor = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(here))), 'raf_engine')
    else:
        klasor = os.path.join(os.environ.get('APPDATA', ''), 'AugeLab Studio', 'marketplace', 'raf_engine')
    if not os.path.isdir(os.path.join(klasor, 'raf_motor')):
        outputs['Durum'] = 'hata: motor bulunamadi (Raf Kamera panelini bir kez acin)'
        return
    for p in (klasor, os.path.join(klasor, 'deps')):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    state['klasor'] = klasor
try:
    damga = os.path.getmtime(os.path.join(klasor, 'surum.txt'))
except OSError:
    damga = 0
if state.get('blok') is None or state.get('damga') != damga:
    imza = ''
    try:
        with open(os.path.join(klasor, 'surum.txt'), encoding='ascii') as f:
            imza = f.read()
    except OSError:
        pass
    eski = sys.modules.get('raf_motor')
    if eski is not None and getattr(eski, '_imza', None) != imza:
        for ad in [m for m in sys.modules if m == 'raf_motor' or m.startswith('raf_motor.')]:
            del sys.modules[ad]
    try:
        state['blok'] = importlib.import_module('raf_motor.blok')
        sys.modules['raf_motor']._imza = imza
    except Exception as exc:
        state['blok'] = None
        outputs['Durum'] = 'hata: motor yuklenemedi: %s: %s' % (type(exc).__name__, exc)
        return
    state['damga'] = damga
    state['durum'] = {}
blok = state['blok']
"""

VIDEO_KODU = """\
outputs['Image'] = None
outputs['Zaman'] = 0
outputs['Bitti'] = False
outputs['Durum'] = ''
""" + _YUKLE + """\
try:
    goruntu, zaman, bitti, durum = blok.video(state['durum'], inputs['Kamera'] or '')
except Exception as exc:
    outputs['Durum'] = 'hata: %s: %s' % (type(exc).__name__, exc)
    return
outputs['Image'] = goruntu
outputs['Zaman'] = zaman
outputs['Bitti'] = bitti
outputs['Durum'] = durum
"""

# Kişiler ve Raf çıkışları varsayılan olarak "hata" değeridir (boş liste "kimse yok / raf boş değil" demektir): motor
# yüklenemezse ya da blok beklenmedik bir hata verirse Raf Analiz bunu görür, ölçüm yapmaz ve panele hata bırakır.
KISI_KODU = """\
outputs['Kisiler'] = '{"hata": "Raf Kisi calismadi"}'
outputs['Durum'] = ''
""" + _YUKLE + """\
try:
    kisiler, durum = blok.kisi(state['durum'], inputs['Image'], inputs['Kamera'] or '', inputs['Zaman'])
except Exception as exc:
    outputs['Kisiler'] = '{"hata": "Raf Kisi: %s"}' % type(exc).__name__
    outputs['Durum'] = 'hata: %s: %s' % (type(exc).__name__, exc)
    return
outputs['Kisiler'] = kisiler
outputs['Durum'] = durum
"""

URUN_KODU = """\
outputs['Raf'] = '{"hata": "Raf Urun calismadi"}'
outputs['Durum'] = ''
""" + _YUKLE + """\
try:
    raf, durum = blok.urun(state['durum'], inputs['Image'], inputs['Kamera'] or '', inputs['Zaman'])
except Exception as exc:
    outputs['Raf'] = '{"hata": "Raf Urun: %s"}' % type(exc).__name__
    outputs['Durum'] = 'hata: %s: %s' % (type(exc).__name__, exc)
    return
outputs['Raf'] = raf
outputs['Durum'] = durum
"""

ANALIZ_KODU = """\
outputs['Image'] = None
outputs['Olaylar'] = '[]'
outputs['Durum'] = ''
outputs['Yeni Olay'] = False
""" + _YUKLE + """\
try:
    goruntu, olaylar, durum, yeni = blok.analiz(state['durum'], inputs['Image'], inputs['Kisiler'] or '[]', inputs['Raf'] or '[]', inputs['Kamera'] or '', inputs['Zaman'], bool(inputs['Bitti']))
except Exception as exc:
    outputs['Durum'] = 'hata: %s: %s' % (type(exc).__name__, exc)
    return
outputs['Image'] = goruntu
outputs['Olaylar'] = olaylar
outputs['Durum'] = durum
outputs['Yeni Olay'] = yeni
"""

VIDEO = {
    "resolverKey": "raf_video",
    "name": VIDEO_OP,
    "opCode": VIDEO_OP,
    "title": VIDEO_BASLIK,
    "kind": "computation",
    "description": (
        "Bir kameranın ayarındaki video dosyasını kare kare okur; arayüzsüz çalışmada canlı kameranın akışını da okur. "
        "'Kamera' girişi kamera kodudur. Çıkışlar: görüntü, görüntünün saniye cinsinden zamanı (canlı akışta -1), "
        "akış bittiğinde bir kez True olan Bitti ve durum."
    ),
    "imports": ["sys", "os", "importlib"],
    "inputs": [{"name": "Kamera", "type": "String"}],
    "outputs": [{"name": "Image", "type": "ImageAny"}, {"name": "Zaman", "type": "Number"}, {"name": "Bitti", "type": "Boolean"},
                {"name": "Durum", "type": "String"}],
    "parameters": [],
    "processCode": VIDEO_KODU,
}

KISI = {
    "resolverKey": "raf_kisi",
    "name": KISI_OP,
    "opCode": KISI_OP,
    "title": KISI_BASLIK,
    "kind": "computation",
    "description": (
        "Kişi analizi: tespit, takip, iskelet, baş kutusu ve (açıksa) gövde özellikleri. "
        "Çıkış: JSON {sira, kisiler: [{iz, b: [x1, y1, x2, y2], bas: [x1, y1, x2, y2], ...}]} ve durum. "
        "'bas' kutusu görüntüde yüz gizlemek için kullanılır."
    ),
    "imports": ["sys", "os", "importlib"],
    "inputs": [{"name": "Image", "type": "ImageAny"}, {"name": "Kamera", "type": "String"}, {"name": "Zaman", "type": "Number"}],
    "outputs": [{"name": "Kisiler", "type": "String"}, {"name": "Durum", "type": "String"}],
    "parameters": [],
    "processCode": KISI_KODU,
}

URUN = {
    "resolverKey": "raf_urun",
    "name": URUN_OP,
    "opCode": URUN_OP,
    "title": URUN_BASLIK,
    "kind": "computation",
    "description": (
        "Raf analizi: göz (slot) doluluğu, ürün eşleme ve fiyat etiketi; tek seferlik raf işleri. "
        "Çıkış: JSON {sira, gozler: [...]} ve durum."
    ),
    "imports": ["sys", "os", "importlib"],
    "inputs": [{"name": "Image", "type": "ImageAny"}, {"name": "Kamera", "type": "String"}, {"name": "Zaman", "type": "Number"}],
    "outputs": [{"name": "Raf", "type": "String"}, {"name": "Durum", "type": "String"}],
    "parameters": [],
    "processCode": URUN_KODU,
}

ANALIZ = {
    "resolverKey": "raf_analiz",
    "name": ANALIZ_OP,
    "opCode": ANALIZ_OP,
    "title": ANALIZ_BASLIK,
    "kind": "computation",
    "description": (
        "Kişi ve raf sonuçlarını birleştirir, olayları ve ölçümleri panelin kuyruğuna bırakır, yüzleri gizlenmiş "
        "işaretli görüntüyü verir. Çıkışlar: görüntü, başlayan olaylar (JSON), durum, Yeni Olay. Zaman ve Bitti, "
        "Raf Video'dan gelir."
    ),
    "imports": ["sys", "os", "importlib"],
    "inputs": [{"name": "Image", "type": "ImageAny"}, {"name": "Kisiler", "type": "String"}, {"name": "Raf", "type": "String"},
               {"name": "Kamera", "type": "String"}, {"name": "Zaman", "type": "Number"}, {"name": "Bitti", "type": "Boolean"}],
    "outputs": [{"name": "Image", "type": "ImageAny"}, {"name": "Olaylar", "type": "String"}, {"name": "Durum", "type": "String"},
                {"name": "Yeni Olay", "type": "Boolean"}],
    "parameters": [],
    "processCode": ANALIZ_KODU,
}

TANIMLAR = [VIDEO, KISI, URUN, ANALIZ]


def imza() -> str:
    """Blok tanımlarının özeti: giriş ya da çıkışlar değiştiyse hazır sahnenin yeniden üretilmesi gerekir."""
    import hashlib
    import json

    return hashlib.sha1(json.dumps(TANIMLAR, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def dosya_metni(t: dict) -> str:
    """Bloğun Studio'nun özel blok klasörüne konacak dosyası: Studio'nun node.custom.create ile tanımdan ürettiği dosyanın
    aynısı. Arayüzsüz çalışmada (studio run) Studio açık olmadığından dosyayı panel kendisi yazar."""
    op = t["opCode"]
    girisler = ",\n".join(f"        SocketTypes.{g['type']}({g['name']!r}, multiple=False)" for g in t["inputs"])
    cikislar = ",\n".join(f"        SocketTypes.{c['type']}({c['name']!r}, multiple=False)" for c in t["outputs"])
    adlar = ", ".join(repr(c["name"]) for c in t["outputs"])
    if len(t["outputs"]) == 1:
        adlar += ","
    islem = "".join(("        " + s if s.strip() else "") + "\n" for s in t["processCode"].rstrip("\n").split("\n"))
    girdi = ",\n".join(f"            {g['name']!r}: self.input[{g['name']!r}].data" for g in t["inputs"])
    cikti = ",\n".join(f"            {c['name']!r}: None" for c in t["outputs"])
    ithal = "".join(f"import {m}\n" for m in t.get("imports") or [])
    return (
        "from studio.custom_block import (\n"
        "    Block, CheckBox, DropDown, Label, SocketTypes, TextInput, add_block,\n"
        ")\n\n"
        f"{ithal}\n"
        f"class {op}(Block):\n"
        f"    op_code = {op!r}\n"
        f"    input_sockets = [\n{girisler}\n    ]\n"
        f"    output_sockets = [\n{cikislar}\n    ]\n"
        "    _augelab_generated_spec_version = 1\n"
        f"    _augelab_output_names = ({adlar})\n\n"
        "    def init(self):\n"
        f"        self.op_title = {t['title']!r}\n"
        "        self.width = 280\n"
        "        self.height = 150\n"
        f"        self.tooltip = {t['description']!r}\n"
        "        pass\n"
        "        self._augelab_generated_state = {}\n\n"
        "    @staticmethod\n"
        "    def _process(inputs, parameters, state, outputs):\n"
        f"{islem}\n"
        "    def run(self):\n"
        f"        inputs = {{\n{girdi}\n        }}\n"
        "        parameters = {\n            \n        }\n"
        "        state = self._augelab_generated_state\n"
        f"        outputs = {{\n{cikti}\n        }}\n"
        "        self._process(inputs, parameters, state, outputs)\n"
        "        unknown = set(outputs).difference(self._augelab_output_names)\n"
        "        if unknown:\n"
        "            raise ValueError(f\"Undeclared generated outputs: {sorted(unknown)}\")\n"
        "        for output_name in self._augelab_output_names:\n"
        "            self.output[output_name].data = outputs[output_name]\n\n\n"
        f"add_block({op}.op_code, {op})\n"
    )
