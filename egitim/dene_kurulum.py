"""Studio kurulum sözleşmesini gerçek kurucu çalıştırmadan sınar.

  python egitim/dene_kurulum.py

Akış: resmî kurucuyu indir ve SHA-256 ile doğrula → Visual C++ yoksa Microsoft'tan indir, imzasını
doğrula, kur → Studio'yu sessizce kur, olmazsa resmî kurulum penceresini aç. Studio penceresi açılmaz (Raf Kamera Studio'yu
arayüzsüz kullanır); lisans kodu Studio'nun kendi komutuyla (studio verify) arayüzsüz kaydedilir.
Modeller: kurulum dosyası ve panel aynı tablodan (studio_kurulum.MODELLER → kurulum/modeller.iss) aynı adres ve özetle
indirir; indirme yerel bir HTTP sunucusuyla sınanır (doğru dosya, özeti tutmayan dosya, HTML sayfası, yarım kalan indirme).
Tablo bu sürümde boştur: boş tabloyla hiçbir şeyin eksik sayılmadığı da sınanır.
"""
import hashlib
import io
import os
import ssl
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from urllib.error import URLError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_kurulum as kurulum


def yanit(icerik: bytes):
    """urlopen yanıtı gibi: okunur, bağlam yöneticisidir ve başlık taşır."""
    y = io.BytesIO(icerik)
    y.headers = {"Content-Length": str(len(icerik))}
    return y


@unittest.skipUnless(os.name == "nt", "Windows kurulum senaryosu")
class StudioKurulumTesti(unittest.TestCase):
    def setUp(self):
        gecici = self.enterContext(tempfile.TemporaryDirectory())
        self.veri = Path(gecici) / "veri"
        self.hedef = Path(gecici) / "Programlar" / "Studio"
        self.studio = self.hedef / kurulum.EXE
        self.is_ = SimpleNamespace(dur=threading.Event())
        self.enterContext(patch.dict(os.environ, {"PROCESSOR_ARCHITEW6432": "AMD64"}))
        self.enterContext(patch.object(kurulum.yollar, "VERI", self.veri))
        self.enterContext(patch.object(kurulum, "varsayilan_klasor", return_value=self.hedef))
        self.enterContext(patch.object(kurulum, "kurulu_studio", side_effect=self._bul))
        self.enterContext(patch.object(kurulum, "_kurulumu_bekle", side_effect=lambda *a: self._bul()))
        self.enterContext(patch.object(kurulum.time, "sleep"))
        self.enterContext(patch.object(kurulum, "studio_calisiyor", return_value=False))
        self.vc_var = True
        self.enterContext(patch.object(kurulum, "vc_kurulu", side_effect=lambda: self.vc_var))
        self.imza = self.enterContext(patch.object(kurulum, "microsoft_imzali", return_value=True))
        self.indir = self.enterContext(patch.object(kurulum.urllib.request, "urlopen"))
        self.calistir = self.enterContext(patch.object(kurulum, "_harici_program"))
        self.izinle = self.enterContext(patch.object(kurulum, "_izinle_calistir"))
        self.icerik = b"MZ test icin kurulum paketi"
        self.vc_icerik = b"MZ test icin visual c++ paketi"
        self.gercek_sha = kurulum.KURULUM_SHA256
        self.enterContext(patch.object(kurulum, "KURULUM_SHA256", hashlib.sha256(self.icerik).hexdigest()))
        self.indir.side_effect = lambda istek, **kw: yanit(self.vc_icerik if istek.full_url == kurulum.VC_URL else self.icerik)
        kurulum.DURUM.update(asama="bos", hata="")

    def _bul(self):
        return kurulum._studio_exe(self.hedef)

    def _studio_olustur(self, *_a, **_kw):
        self.hedef.mkdir(parents=True, exist_ok=True)
        self.studio.touch()
        python = self.hedef / "Python"
        paket = python / "Lib" / "site-packages" / "studio"
        paket.mkdir(parents=True, exist_ok=True)
        (python / "pythonw.exe").touch()
        (paket / "__init__.py").touch()
        return 0

    def _indirilenler(self):
        return [c.args[0].full_url for c in self.indir.call_args_list]

    def test_var_olan_kurulum_korunur(self):
        self._studio_olustur()
        self.assertEqual(kurulum.kur(self.is_), {"kurulu": True})
        self.indir.assert_not_called()
        self.izinle.assert_not_called()
        self.calistir.assert_not_called()  # Studio penceresi açılmaz

    def test_ilk_kurulum_sessiz_ve_pencere_acmaz(self):
        self.izinle.side_effect = self._studio_olustur
        self.assertEqual(kurulum.kur(self.is_), {"kurulu": True})
        self.assertEqual(self._indirilenler(), [kurulum.KURULUM_URL])
        tls = self.indir.call_args.kwargs["context"]
        self.assertTrue(tls.check_hostname)
        self.assertEqual(tls.verify_mode, ssl.CERT_REQUIRED)
        kurucu, parametre = self.izinle.call_args.args[:2]
        self.assertEqual(kurucu.parent, self.veri / "kurulum")
        self.assertIn("--silent", parametre)
        self.assertIn(f'--install-dir "{self.hedef}"', parametre)
        self.calistir.assert_not_called()  # ne kurulum penceresi ne Studio penceresi açıldı
        self.assertEqual(kurulum.DURUM["asama"], "bos")
        self.assertFalse(hasattr(kurulum, "ac"))

    def test_sessiz_kurulum_olmazsa_resmi_pencere_acilir(self):
        self.izinle.return_value = 1603
        pencere = MagicMock()
        pencere.__enter__.return_value = pencere
        pencere.wait.side_effect = self._studio_olustur
        self.calistir.return_value = pencere
        self.assertEqual(kurulum.kur(self.is_), {"kurulu": True})
        cagrilar = self.calistir.call_args_list
        self.assertEqual(len(cagrilar), 1)  # yalnızca resmî kurulum penceresi; Studio başlatılmadı
        self.assertEqual(cagrilar[0].kwargs, {"cwd": self.veri / "kurulum"})

    def test_visual_cpp_yoksa_imzasi_dogrulanip_kurulur(self):
        self.vc_var = False

        def calistir(program, parametre="", **kw):
            if program.name == "vc_redist.x64.exe":
                self.assertEqual(parametre, "/install /passive /norestart")
                self.vc_var = True
                return 3010  # yeniden başlatma gerekebilir: başarı sayılır
            return self._studio_olustur()

        self.izinle.side_effect = calistir
        self.assertEqual(kurulum.kur(self.is_), {"kurulu": True})
        self.assertEqual(self._indirilenler(), [kurulum.KURULUM_URL, kurulum.VC_URL])
        self.imza.assert_called_once()
        self.assertEqual([c.args[0].name for c in self.izinle.call_args_list][0], "vc_redist.x64.exe")

    def test_imzasi_dogrulanmayan_visual_cpp_calistirilmaz(self):
        self.vc_var = False
        self.imza.return_value = False
        with self.assertRaisesRegex(SystemExit, "Microsoft imzası doğrulanamadı"):
            kurulum.kur(self.is_)
        self.izinle.assert_not_called()
        self.calistir.assert_not_called()
        self.assertFalse((self.veri / "kurulum" / "vc_redist.x64.exe").exists())
        self.assertEqual(kurulum.DURUM["asama"], "hata")

    def test_windows_izni_verilmezse_anlasilir_hata(self):
        self.vc_var = False
        self.izinle.side_effect = OSError(None, "iptal", None, 1223)
        with self.assertRaisesRegex(SystemExit, "Windows izni verilmedi"):
            kurulum.kur(self.is_)

    def test_eksik_kurulumun_uzerine_yazilmaz(self):
        self.hedef.mkdir(parents=True)
        self.studio.touch()
        (self.hedef / "korunacak.txt").touch()
        with self.assertRaisesRegex(SystemExit, "klasörü dolu"):
            kurulum.kur(self.is_)
        self.indir.assert_not_called()
        self.calistir.assert_not_called()

    def test_dogrulanmamis_paket_calistirilmaz(self):
        self.indir.side_effect = lambda *a, **kw: yanit(b"MZ gecersiz")
        with self.assertRaisesRegex(SystemExit, "doğrulaması başarısız"):
            kurulum.kur(self.is_)
        self.izinle.assert_not_called()
        self.calistir.assert_not_called()
        self.assertFalse(list((self.veri / "kurulum").iterdir()))

    def test_exe_olmayan_indirme_calistirilmaz(self):
        self.indir.side_effect = lambda *a, **kw: yanit(b"<html>hata sayfasi</html>")
        with self.assertRaisesRegex(SystemExit, "eksik ya da bozuk"):
            kurulum.kur(self.is_)
        self.izinle.assert_not_called()

    def test_kurucu_basari_donse_bile_studio_yoksa_hata(self):
        self.izinle.return_value = 0
        self.calistir.return_value.__enter__.return_value.wait.return_value = 0
        with self.assertRaisesRegex(SystemExit, "kurulumu tamamlanmadı veya bulunamadı"):
            kurulum.kur(self.is_)
        self.calistir.assert_called_once()  # sessiz kurulum Studio bırakmadı: resmî pencere açıldı, yine yok
        self.assertEqual(kurulum.DURUM["asama"], "hata")

    def test_gecersiz_tls_ile_kurucu_calistirilmaz(self):
        self.indir.side_effect = URLError(ssl.SSLCertVerificationError("sertifika"))
        with self.assertRaisesRegex(SystemExit, "TLS sertifikası doğrulanamadı"):
            kurulum.kur(self.is_)
        self.izinle.assert_not_called()
        self.calistir.assert_not_called()

    def test_kurulumdan_sonra_acilan_studio_kapatilir(self):
        self.izinle.side_effect = self._studio_olustur
        kurulum.studio_calisiyor.return_value = True
        with patch.object(kurulum.subprocess, "run") as calistir:
            self.assertEqual(kurulum.kur(self.is_), {"kurulu": True})
        self.assertEqual(calistir.call_args.args[0][:3], ["taskkill", "/IM", kurulum.EXE])

    def test_lisans_kodu_arayuzsuz_kaydedilir_ve_saklanmaz(self):
        self._studio_olustur()
        kod = "ABCD-1234-EFGH-5678"
        with patch.object(kurulum.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as calistir:
            kurulum.lisans_kaydet(" " + kod + "\n")
        komut = calistir.call_args.args[0]
        self.assertEqual(komut[0], str(self.hedef / "Python" / "python.exe"))
        self.assertEqual(komut[1:], ["-c", kurulum.VERIFY])
        self.assertNotIn(kod, " ".join(komut))  # kod komut satırında görünmez
        self.assertEqual(calistir.call_args.kwargs["env"]["RAF_LISANS_KODU"], kod)
        self.assertNotIn(kod, "".join(str(p) for p in self.veri.rglob("*")) if self.veri.exists() else "")

    def test_reddedilen_lisans_kodu_hata_metninde_gorunmez(self):
        self._studio_olustur()
        kod = "GECERSIZ-KOD-9999"
        cikti = SimpleNamespace(returncode=1, stdout="", stderr=f"Verification failed for {kod}: invalid code")
        with patch.object(kurulum.subprocess, "run", return_value=cikti):
            with self.assertRaises(SystemExit) as h:
                kurulum.lisans_kaydet(kod)
        self.assertNotIn(kod, str(h.exception.code))
        self.assertIn("kaydedilemedi", str(h.exception.code))

    def test_bicimsiz_lisans_kodu_studioya_verilmez(self):
        self._studio_olustur()
        with patch.object(kurulum.subprocess, "run") as calistir:
            for kod in ("", "kisa", "iki kelime kod", "--help"):
                with self.assertRaisesRegex(SystemExit, "geçersiz"):
                    kurulum.lisans_kaydet(kod)
        calistir.assert_not_called()

    def test_kurulum_dosyasi_ayni_studio_kurucusunu_kullanir(self):
        import re

        iss = (Path(__file__).resolve().parent.parent / "kurulum" / "RafKamera.iss").read_text(encoding="utf-8")
        tanim = dict(re.findall(r'^#define (\w+) "([^"]*)"', iss, flags=re.M))
        self.assertEqual(tanim["StudioUrl"], kurulum.KURULUM_URL)
        self.assertEqual(tanim["StudioSha256"], self.gercek_sha)
        self.assertEqual(tanim["VcUrl"], kurulum.VC_URL)
        self.assertEqual(tanim["HesapUrl"], kurulum.HESAP_URL)
        self.assertEqual(tanim["StudioExe"], kurulum.EXE)

    def test_durum_paneli_icin(self):
        d = kurulum.durum()
        self.assertEqual(set(d), {"asama", "ne", "indirilen", "toplam", "hata", "gecen", "calisiyor"})


KOK = Path(__file__).resolve().parent.parent


class ModelSozlesmesiTesti(unittest.TestCase):
    """Kurulum dosyası ve panel aynı model tablosunu kullanır (kurulum/modeller.iss, studio_kurulum.MODELLER'dan üretilir)."""

    def test_kurulum_dosyasi_ayni_modelleri_indirir(self):
        sys.path.insert(0, str(KOK / "kurulum"))
        import modeller_iss

        iss = (KOK / "kurulum" / "RafKamera.iss").read_text(encoding="utf-8")
        self.assertIn('#include "modeller.iss"', iss)
        self.assertNotIn("drive.usercontent.google.com", iss)  # adresler yalnızca üretilen dosyada
        self.assertEqual((KOK / "kurulum" / "modeller.iss").read_text(encoding="utf-8"), modeller_iss.metin(),
                         "kurulum/modeller.iss eski: python kurulum/modeller_iss.py çalıştırın")
        ornek = [{"ad": "kisi.onnx.isgm", "boyut": 1234, "sha256": "ab" * 32, "drive": "KIMLIK-1"},
                 {"ad": "urun.onnx.isgm", "boyut": 99, "sha256": "cd" * 32, "drive": "KIMLIK-2"}]
        with patch.object(kurulum, "MODELLER", ornek):
            metin = modeller_iss.metin()
        self.assertIn("SetArrayLength(ModelAdlari, 2);", metin)
        for i, m in enumerate(ornek):
            self.assertIn(f"ModelAdlari[{i}] := '{m['ad']}';", metin)
            self.assertIn(f"ModelBoyutlari[{i}] := {m['boyut']};", metin)
            self.assertIn(f"ModelOzetleri[{i}] := '{m['sha256']}';", metin)
            self.assertIn(f"ModelAdresleri[{i}] := 'https://drive.usercontent.google.com/download?id={m['drive']}"
                          "&export=download&confirm=t';", metin)

    def test_tablo_bicimi(self):
        adlar = [m["ad"] for m in kurulum.MODELLER]
        self.assertEqual(len(adlar), len(set(adlar)))
        for m in kurulum.MODELLER:
            # korumalı paket girdisi <ad>.isgm; yardımcı dosya (etiket-oku.txt) "duz": True ile
            self.assertTrue(m["ad"].endswith(".isgm") or m.get("duz") is True, m["ad"])
            self.assertIsInstance(m["boyut"], int)
            self.assertRegex(m["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(m["drive"], r"^[A-Za-z0-9_-]{10,}$")

    def test_sabitler_yerel_model_dosyalarina_uyar(self):
        yerel = [m for m in kurulum.MODELLER if (KOK / "kurulum" / "community-modeller" / m["ad"]).is_file()]
        if not yerel:
            self.skipTest("yerel model dosyası yok (kurulum/community-modeller)")
        for m in yerel:
            dosya = KOK / "kurulum" / "community-modeller" / m["ad"]
            self.assertEqual(dosya.stat().st_size, m["boyut"])
            with dosya.open("rb") as f:
                self.assertEqual(hashlib.file_digest(f, "sha256").hexdigest(), m["sha256"])

    def test_paket_exe_ye_buyuk_modeli_koymaz(self):
        spec = (KOK / "kurulum" / "RafKamera.spec").read_text(encoding="utf-8")
        self.assertIn("[isaret, dll]]", spec)
        self.assertNotIn("[isaret, dll, *modeller]", spec)
        self.assertIn('"__pycache__" not in ad', spec)

    def test_paket_yoksa_derleme_anlasilir_turkce_hatayla_durur(self):
        derle = (KOK / "kurulum" / "derle.cmd").read_bytes()
        self.assertIn(b"\r\n", derle)  # .cmd dosyası CRLF kalmalı
        metin = derle.decode("ascii")
        for dosya in ("community-paket.json", "goruntu-*.dll", "RUST-NOTICES.txt", "raf-kamera.pmod"):
            self.assertIn(dosya, metin)
        self.assertIn("Korumali model paketi eksik", metin)
        self.assertIn("Hazir sahne yok", metin)


class Sunucu:
    """Yerel HTTP sunucusu: her istekte `self.govde` döner; `self.kes` verilirse o kadar bayttan sonra bağlantıyı keser."""

    def __init__(self):
        import http.server

        dis = self

        class Isleyici(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                dis.istekler.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", dis.tur)
                if dis.uzunluk is not False:
                    self.send_header("Content-Length", str(len(dis.govde) if dis.uzunluk is None else dis.uzunluk))
                self.end_headers()
                self.wfile.write(dis.govde if dis.kes is None else dis.govde[:dis.kes])
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *a):
                pass

        self.govde, self.tur, self.kes, self.uzunluk, self.istekler = b"", "application/octet-stream", None, None, []
        self.sunucu = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
        threading.Thread(target=self.sunucu.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.sunucu.server_address[1]}/download?id=DENEME&export=download&confirm=t"

    def kapat(self):
        self.sunucu.shutdown()
        self.sunucu.server_close()


class ModelIndirmeTesti(unittest.TestCase):
    """studio_kurulum.model_indir: yerel sunucudan indirme, boyut ve SHA-256 doğrulaması, yarım dosya bırakmama.
    Tabloya sınama süresince yerel sunucuyu gösteren bir model konur."""

    def setUp(self):
        self.klasor = Path(self.enterContext(tempfile.TemporaryDirectory())) / "modeller"
        self.icerik = os.urandom(700_000)  # birkaç parçalık (256 KB) gerçek akış
        self.sunucu = Sunucu()
        self.addCleanup(self.sunucu.kapat)
        self.sunucu.govde = self.icerik
        self.ad = "deneme.onnx.isgm"
        self.m = {"ad": self.ad, "boyut": len(self.icerik), "sha256": hashlib.sha256(self.icerik).hexdigest(),
                  "drive": "DENEME-KIMLIK", "url": self.sunucu.url}
        self.enterContext(patch.object(kurulum.yollar, "MODELLER", self.klasor))
        self.enterContext(patch.object(kurulum.yollar, "PAKET_MODELLER", self.klasor))  # kaynak koddan: ikisi aynı klasör
        self.enterContext(patch.object(kurulum.yollar, "DONDURULMUS", False))
        self.enterContext(patch.dict(kurulum._DOGRULANAN, {}, clear=True))
        self.enterContext(patch.object(kurulum, "MODELLER", [self.m]))
        kurulum.MODEL_DURUM.update(asama="bos", ne="", indirilen=0, toplam=0, hata="")
        self.hedef = self.klasor / self.ad

    def _kalanlar(self):
        return sorted(p.name for p in self.klasor.iterdir()) if self.klasor.exists() else []

    def test_bos_tabloyla_hicbir_sey_eksik_sayilmaz(self):
        self._isaretli()
        with patch.object(kurulum, "MODELLER", []):
            self.assertFalse(kurulum.model_gerekli())
            self.assertEqual(kurulum.eksik_modeller(), [])
            d = kurulum.model_durumu()
            self.assertEqual((d["eksik"], d["sayi"], d["boyut"]), (False, 0, 0))
            self.assertEqual(kurulum.model_indirmeyi_baslat(), (False, "Modeller zaten yerinde."))
            with patch.object(kurulum.yollar, "DONDURULMUS", True):
                self.assertEqual(dict(kurulum.motor_modelleri()), {kurulum.MODEL_ISARETI: self.klasor / kurulum.MODEL_ISARETI})
        self.assertEqual(self.sunucu.istekler, [])

    def test_drive_adresi_kimlikten_uretilir(self):
        self.assertEqual(kurulum.model_url({"drive": "ABC_123-xyz"}),
                         "https://drive.usercontent.google.com/download?id=ABC_123-xyz&export=download&confirm=t")
        self.assertEqual(kurulum.model_url(self.m), self.sunucu.url)

    def test_dogru_dosya_indirilir_ve_yerine_konur(self):
        self.assertTrue(kurulum.model_indir(self.m))
        self.assertEqual(self.hedef.read_bytes(), self.icerik)
        self.assertEqual(self._kalanlar(), [self.ad])  # geçici dosya kalmaz
        self.assertEqual(kurulum.MODEL_DURUM["indirilen"], len(self.icerik))
        self.assertEqual(kurulum.MODEL_DURUM["asama"], "bos")
        self.assertTrue(kurulum.model_indirildi(self.m))
        self.assertTrue(kurulum.model_dogrulandi(self.m))  # indirip doğrulanan dosya bu süreçte doğrulanmış sayılır
        self.assertEqual(self.sunucu.istekler, ["/download?id=DENEME&export=download&confirm=t"])

    def test_ozeti_tutmayan_dosya_reddedilir(self):
        bozuk = bytearray(self.icerik)
        bozuk[len(bozuk) // 2] ^= 0xFF  # aynı boyut, farklı içerik
        self.sunucu.govde = bytes(bozuk)
        with self.assertRaisesRegex(SystemExit, "SHA-256"):
            kurulum.model_indir(self.m)
        self.assertEqual(self._kalanlar(), [])

    def test_html_sayfasi_reddedilir(self):
        self.sunucu.govde, self.sunucu.tur = b"<!DOCTYPE html><html><body>Google Drive - kota asildi</body></html>", "text/html"
        with self.assertRaisesRegex(SystemExit, "uyarı sayfası"):
            kurulum.model_indir(self.m)
        self.assertEqual(self._kalanlar(), [])
        self.sunucu.uzunluk = False  # boyut başlığı olmadan da: içerik boyutu ve özeti tutmaz
        with self.assertRaisesRegex(SystemExit, "uyarı sayfası"):
            kurulum.model_indir(self.m)
        self.assertEqual(self._kalanlar(), [])

    def test_yarim_kalan_indirme_reddedilir_ve_eski_dosya_korunur(self):
        self.klasor.mkdir(parents=True)
        self.hedef.write_bytes(b"onceki")  # boyutu yanlış eski dosya: indirme başarısızsa yerinde kalır
        self.sunucu.kes = len(self.icerik) // 3  # başlık tam boyutu söyler, bağlantı erken kapanır
        with self.assertRaises(SystemExit):
            kurulum.model_indir(self.m)
        self.assertEqual(self.hedef.read_bytes(), b"onceki")
        self.assertEqual(self._kalanlar(), [self.ad])
        self.assertFalse(kurulum.model_indirildi(self.m))

    def test_durdurulan_indirme_dosya_birakmaz(self):
        dur = threading.Event()
        dur.set()
        self.assertFalse(kurulum.model_indir(self.m, dur))
        self.assertEqual(self._kalanlar(), [])

    def test_panel_indirmeyi_arka_planda_baslatir_ve_hatayi_gosterir(self):
        self.klasor.mkdir(parents=True)
        self.assertEqual(kurulum.model_indirmeyi_baslat(), (False, "Modeller zaten yerinde."))  # işaret yok: düz model
        (self.klasor / kurulum.MODEL_ISARETI).write_text("{}", encoding="ascii")
        self.assertTrue(kurulum.model_durumu()["eksik"])
        self.sunucu.govde = b"<html>yok</html>"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(kurulum.model_indirmeyi_baslat()[0], True)
            self._bekle()
        d = kurulum.model_durumu()
        self.assertEqual((d["asama"], d["eksik"]), ("hata", True))
        self.assertIn("uyarı sayfası", d["hata"])
        self.sunucu.govde = self.icerik  # Yeniden dene
        with redirect_stdout(io.StringIO()):
            self.assertEqual(kurulum.model_indirmeyi_baslat(), (True, ""))
            self._bekle()
        self.assertEqual((kurulum.model_durumu()["asama"], kurulum.model_durumu()["eksik"]), ("bos", False))
        self.assertEqual(kurulum.model_indirmeyi_baslat(), (False, "Modeller zaten yerinde."))

    def test_iki_model_sirayla_indirilir(self):
        ikinci_icerik = os.urandom(300_000)
        ikinci_sunucu = Sunucu()
        self.addCleanup(ikinci_sunucu.kapat)
        ikinci_sunucu.govde = ikinci_icerik
        ikinci = {"ad": "ikinci.onnx.isgm", "boyut": len(ikinci_icerik), "sha256": hashlib.sha256(ikinci_icerik).hexdigest(),
                  "drive": "IKINCI-KIMLIK", "url": ikinci_sunucu.url}
        self._isaretli()
        with patch.object(kurulum, "MODELLER", [self.m, ikinci]):
            self.assertEqual(kurulum.model_durumu()["eksik_sayi"], 2)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(kurulum.model_indirmeyi_baslat(), (True, ""))
                self._bekle()
            self.assertEqual(kurulum.model_durumu()["eksik_sayi"], 0)
            self.assertEqual((self.klasor / "ikinci.onnx.isgm").read_bytes(), ikinci_icerik)
            self.assertEqual(self.hedef.read_bytes(), self.icerik)

    def test_gecici_dosya_bu_surece_ozgu_ve_kurulumunkinden_ayri(self):
        adlar = []
        gercek = kurulum.os.replace

        def kaydet(kaynak, hedef):
            adlar.append(Path(kaynak).name)
            return gercek(kaynak, hedef)

        with patch.object(kurulum.os, "replace", side_effect=kaydet):
            self.assertTrue(kurulum.model_indir(self.m))
        self.assertEqual(adlar, [f"{self.ad}.{os.getpid()}.indiriliyor"])
        self.assertNotEqual(adlar[0], self.ad + ".yeni")  # kurulum dosyası .yeni kullanır

    def _isaretli(self, paket: Path | None = None):
        paket = paket or self.klasor
        paket.mkdir(parents=True, exist_ok=True)
        self.klasor.mkdir(parents=True, exist_ok=True)
        (paket / kurulum.MODEL_ISARETI).write_text("{}", encoding="ascii")

    def test_acilista_eski_yarim_indirmeler_silinir(self):
        self._isaretli()
        eski = self.klasor / f"{self.ad}.4242.indiriliyor"
        eski.write_bytes(b"yarim")
        kurulum_yenisi = self.klasor / f"{self.ad}.yeni"
        kurulum_yenisi.write_bytes(b"kurulum")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(kurulum.model_indirmeyi_baslat(), (True, ""))
            self._bekle()
        self.assertFalse(eski.exists())
        self.assertTrue(kurulum_yenisi.exists())  # kurulum dosyasının geçici adına dokunulmaz
        self.assertEqual(self.hedef.read_bytes(), self.icerik)

    def test_ayni_boyutta_bozuk_model_bulunur_silinir_ve_yeniden_indirilir(self):
        self._isaretli()
        bozuk = bytearray(self.icerik)
        bozuk[12345] ^= 0xFF
        self.hedef.write_bytes(bytes(bozuk))
        self.assertTrue(kurulum.model_indirildi(self.m))  # boyut tutuyor
        self.assertTrue(kurulum.model_durumu()["eksik"] is False)  # kaynak koddan boyut yeter; exe'de aşağıda
        with patch.object(kurulum.yollar, "DONDURULMUS", True):
            self.assertTrue(kurulum.model_durumu()["eksik"])
            with redirect_stdout(io.StringIO()) as cikti:
                self.assertEqual(kurulum.model_indirmeyi_baslat(), (True, ""))
                self._bekle()
            self.assertIn("bozuk", cikti.getvalue())
            self.assertEqual(self.hedef.read_bytes(), self.icerik)
            self.assertEqual(len(self.sunucu.istekler), 1)
            self.assertTrue(kurulum.model_dogrulandi(self.m))
            self.assertFalse(kurulum.model_durumu()["eksik"])

    def test_dogru_model_yalnizca_dogrulanir_indirilmez(self):
        self._isaretli()
        self.hedef.write_bytes(self.icerik)
        with patch.object(kurulum.yollar, "DONDURULMUS", True):
            self.assertFalse(kurulum.model_dogrulandi(self.m))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(kurulum.model_indirmeyi_baslat(), (True, ""))
                self._bekle()
            self.assertEqual(self.sunucu.istekler, [])
            self.assertTrue(kurulum.model_dogrulandi(self.m))
            self.assertEqual(kurulum.model_indirmeyi_baslat(), (False, "Modeller zaten yerinde."))
            with patch.object(kurulum.hashlib, "file_digest", side_effect=AssertionError("yeniden okundu")):
                for _ in range(3):  # durum yoklaması dosyayı yeniden okumaz
                    self.assertFalse(kurulum.model_durumu()["eksik"])

    def test_dogrulanmamis_model_kullanilmaz(self):
        paket = self.klasor.parent / "paket"
        self._isaretli(paket)
        (paket / "goruntu-ab.dll").write_bytes(b"guvenilir")
        self.hedef.write_bytes(self.icerik)  # doğru içerik, ama bu süreçte doğrulanmadı
        (self.klasor / "goruntu-ab.dll").write_bytes(b"degistirilmis")
        (self.klasor / "fazla.dll").write_bytes(b"x")
        with patch.object(kurulum.yollar, "DONDURULMUS", True), patch.object(kurulum.yollar, "PAKET_MODELLER", paket):
            adlar = dict(kurulum.motor_modelleri())
            self.assertEqual(adlar, {kurulum.MODEL_ISARETI: paket / kurulum.MODEL_ISARETI, "goruntu-ab.dll": paket / "goruntu-ab.dll"})
            self.assertTrue(kurulum.model_durumu()["eksik"])
            self.assertIsNone(kurulum.dogrulanmis_ozet(self.hedef))
            self.assertTrue(kurulum.model_dogrula(self.m))
            adlar = dict(kurulum.motor_modelleri())
            self.assertEqual(adlar[self.ad], self.hedef)
            self.assertEqual(adlar["goruntu-ab.dll"], paket / "goruntu-ab.dll")
            self.assertNotIn("fazla.dll", adlar)
            self.assertEqual(kurulum.dogrulanmis_ozet(self.hedef), bytes.fromhex(self.m["sha256"]))
            os.utime(self.hedef, ns=(1, 1))  # doğrulamadan sonra değişti
            self.assertNotIn(self.ad, dict(kurulum.motor_modelleri()))

    def test_dogrulanmamis_modelle_analiz_baslamaz(self):
        import uygulama

        paket = self.klasor.parent / "paket"
        self._isaretli(paket)
        (paket / kurulum.MODEL_ISARETI).write_text('{"id": "%s"}' % ("ab" * 16), encoding="ascii")
        (paket / f"goruntu-{'ab' * 16}.dll").write_bytes(b"dll")
        self.hedef.write_bytes(self.icerik)
        with patch.object(kurulum.yollar, "DONDURULMUS", True), patch.object(kurulum.yollar, "PAKET_MODELLER", paket):
            kurulum.MODEL_DURUM.update(asama="dogrulaniyor")
            self.assertIn("doğrulanıyor", uygulama._model_engeli())
            self.assertFalse(uygulama._model_var())
            kurulum.MODEL_DURUM.update(asama="bos")
            self.assertIn("indirilmedi", uygulama._model_engeli())
            self.assertEqual(uygulama.model_kilidi()["durum"], "hazirlaniyor")
        import kurallar

        motor_katalog = sys.modules[kurallar.eksik_dosyalar.__module__]
        # model yokken (indirme tablosu ve motorun model listesi boş) analiz engellenmez
        with patch.object(kurulum, "MODELLER", []), patch.object(motor_katalog, "MODEL_DOSYALARI", []):
            self.assertIsNone(uygulama._model_engeli())
            self.assertTrue(uygulama._model_var())

    def test_yardimci_dosya_indirilir_dogrulanir_motora_gider(self):
        """etiket-oku.txt gibi yardımcı dosya ("duz": True) korumalı modellerle aynı yoldan indirilir, SHA-256 ile
        doğrulanır, Studio'nun motor klasörüne aynı adla gider ve paket başlığı aranmadığı için "bozuk" sayılmaz."""
        import uygulama

        metin = "0123456789.,-TL\n".encode("utf-8") * 50
        sunucu = Sunucu()
        self.addCleanup(sunucu.kapat)
        sunucu.govde = metin
        duz = {"ad": "etiket-oku.txt", "boyut": len(metin), "sha256": hashlib.sha256(metin).hexdigest(),
               "drive": "DUZ-KIMLIK-123", "url": sunucu.url, "duz": True}
        self.assertFalse(kurulum.korumali(duz))
        self.assertTrue(kurulum.korumali(self.m))
        paket = self.klasor.parent / "paket"
        self._isaretli(paket)
        kimlik = "ab" * 16
        (paket / kurulum.MODEL_ISARETI).write_text('{"id": "%s"}' % kimlik, encoding="ascii")
        (paket / f"goruntu-{kimlik}.dll").write_bytes(b"dll")
        from raf_motor import community_model as cm

        icerik = cm.SIHIR + bytes.fromhex(kimlik) + os.urandom(1000)  # korumalı girdinin başlığı paket kimliğini taşır
        self.sunucu.govde = icerik
        self.m.update(boyut=len(icerik), sha256=hashlib.sha256(icerik).hexdigest())
        with patch.object(kurulum, "MODELLER", [self.m, duz]), patch.object(kurulum.yollar, "DONDURULMUS", True), \
                patch.object(kurulum.yollar, "PAKET_MODELLER", paket):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(kurulum.model_indirmeyi_baslat(), (True, ""))
                self._bekle()
            self.assertEqual((self.klasor / "etiket-oku.txt").read_bytes(), metin)
            self.assertTrue(kurulum.model_dogrulandi(duz))
            self.assertFalse(kurulum.model_durumu()["eksik"])
            adlar = dict(kurulum.motor_modelleri())
            self.assertEqual(adlar["etiket-oku.txt"], self.klasor / "etiket-oku.txt")  # motor klasörüne aynı adla
            self.assertEqual(adlar[self.ad], self.hedef)
            self.assertEqual(uygulama.model_kilidi()["durum"], "studio_kosusunda_dogrulanir")  # "bozuk" değil
        with patch.object(kurulum, "MODELLER", [self.m, duz]):
            sys.path.insert(0, str(KOK / "kurulum"))
            import modeller_iss

            iss = modeller_iss.metin()
        self.assertIn("ModelAdlari[1] := 'etiket-oku.txt';", iss)
        self.assertIn(f"ModelOzetleri[1] := '{duz['sha256']}';", iss)

    def _bekle(self):
        for t in threading.enumerate():
            if t.name == "model-indirme":
                t.join(30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
