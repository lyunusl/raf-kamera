"""Müşteri analizi (Raf Analiz içinde): izlerden ve bölgelerden 30 sn'lik pencere sayıları, ısı haritaları ve kimliksiz
etkileşim kayıtları (sözleşme 4.2 ve 4.4).

Her analiz karesinde (Raf Kişi'nin yeni sırası) `adim()` çağrılır; konum her zaman ayak noktasıdır (kutunun alt ortası).
  geçen    pencerede görülen farklı iz (bölgede: ayak bölgenin içinde; raf bölgesinde: rafın önünde)
  durdu    koridorda ya da raf önünde yavaş (hız < hiz_esik boy/sn) geçen süre esik_sn'yi aşan ziyaret
  bekleme  durulan ziyaretin bölgede geçen toplam süresi; ziyaret bitince sayılır (bekleme_sn toplam, bekleme_sayi adet)
  uzandı   bilek raf bölgesinde (göz tanımlıysa göz kutusunda) ve kol gövdeden ayrık, en_az_kare analiz karesi boyunca
  ilgi_sn  durulan raf ziyaretinde gövdenin rafa dönük olduğu süre (gövde yönü, bakış değil)
  giren/çıkan  ayak noktası giriş çizgisini iç tarafa / dış tarafa geçti
  kuyruk   kasa bölgesinde en_az_sn'den uzun kalan ve yürümeyen (hız < 0.45 boy/sn) kişi sayısı (analiz karelerinin ortalaması ve en çoğu)
  demografi    iz başına oylanmış gövde özelliğinden; her iz bir kez sayılır (iz bitince ya da yeterli örnekle kesinleşince)
Kapalı özelliğin anahtarları ölçüme yazılmaz (yok = ölçülmedi; 0 = ölçüldü, yok).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict, deque

import numpy as np

from . import katalog, olcu

ZIYARET_BOSLUK = 1.5   # sn: bölgeden bu kadar uzun çıkan kişinin ziyareti biter
UZANMA_BOSLUK = 0.45   # sn: bilek bu kadar (ve en az ~1.6 analiz aralığı) görülmezse uzanma biter
IZ_BOSLUK = 0.6        # sn: Raf Kişi listesinden düşen iz bu kadar sonra kapatılır
DERIN_KAT = 2.0        # boy değişim hızının (ln oran / sn) hıza çevrilme katsayısı (bkz. _hiz)


class Musteri:
    def __init__(self, bolgeler: list[dict], ayar: dict, W: int, H: int, bas_zaman: dt.datetime):
        self.W, self.H, self.bas_zaman = W, H, bas_zaman
        self.bolgeler = [b for b in bolgeler if b.get("poly") is not None]
        self.giris = [b for b in bolgeler if b["tur"] == "giris" and b.get("cizgi") is not None and b.get("ic") is not None]
        self.oz = {k: katalog.ozellik_ayari(ayar, k) for k in
                   ("yogunluk", "bekleme", "ilgi", "uzanma", "demografi", "giris_sayim", "kasa_kuyrugu", "toplu_alma", "alma", "geri_koyma")}
        b = self.oz["bekleme"] or katalog.varsayilan_ayarlar("bekleme")
        self.hiz_esik, self.durma_esik, self.raf_yakin = float(b["hiz_esik"]), float(b["esik_sn"]), float(b["raf_yakin"])
        y = self.oz["yogunluk"] or katalog.varsayilan_ayarlar("yogunluk")
        self.harita_durma = float(y["durma_sn"])
        self.durak = [z for z in self.bolgeler if z["tur"] in ("koridor", "raf")]
        self.ortuk = not self.durak  # koridor/raf yoksa bütün kare tek bir alan sayılır (yalnızca kamera geneli)
        self.kasa_en_az = float((self.oz["kasa_kuyrugu"] or katalog.varsayilan_ayarlar("kasa_kuyrugu"))["en_az_sn"])
        self.izler: dict = {}
        self.raf_isaret = False   # raf tarafı alma/bırakma bildirdi mi (alan/birakan anahtarları o zaman yazılır)
        self.alimlar: dict = {}   # iz → deque[(t, bolge, adet)]: raf doğrulamalı alımlar (toplu_alma; iz bitse de pencere kadar)
        self.son_aralik = 1.0 / 3.0  # son iki analiz karesi arası (sn)
        self._pencere()

    # ----------------------------------------------------------------------------------------------- pencere
    def _pencere(self) -> None:
        self.p_gecen, self.p_duran, self.p_uzanan = set(), set(), set()
        self.p_b = defaultdict(lambda: defaultdict(set))         # bölge → ölçü → iz kümesi
        self.p_sayi = defaultdict(float)                          # düz anahtar → sayı
        self.p_kisi: list[int] = []
        self.p_kuyruk: list[int] = []
        self.p_yogunluk, self.p_durma = olcu.bos_izgara(), olcu.bos_izgara()

    def _zaman(self, t: float) -> str:
        return (self.bas_zaman + dt.timedelta(seconds=t)).replace(microsecond=0).isoformat()

    # ----------------------------------------------------------------------------------------------- yardımcılar
    def _hiz(self, z: dict) -> float | None:
        g = z["gecmis"]
        if len(g) < 2:
            return None
        son = g[-1]
        ilk = next((x for x in g if son[0] - x[0] <= 1.5), g[0])
        d = son[0] - ilk[0]
        if d < 0.3:
            return z.get("hiz")
        boy = float(np.median([x[3] for x in g if son[0] - x[0] <= 1.6]))
        duz = float(np.hypot(son[1] - ilk[1], son[2] - ilk[2]) / d / max(boy, 1.0))
        # Kameradan uzaklaşan / yaklaşan kişinin ayak noktası görüntüde az kayar (tavan kamerası, koridor boyunca yürüyüş);
        # boyu ise düzenli küçülür / büyür. Boy değişim hızı da hıza katılır (duran kişide boy sabittir).
        derin = DERIN_KAT * abs(float(np.log(max(son[3], 1.0) / max(ilk[3], 1.0)))) / d
        return max(duz, derin)

    def _bolgede(self, z: dict, b) -> bool:
        if z["tur"] == "raf":
            return olcu.raf_onunde(z["poly"], b, self.raf_yakin)
        return olcu.icinde(z["poly"], olcu.ayak(b))

    def _demo_karar(self, oz: dict | None) -> tuple[str | None, str | None]:
        d = self.oz["demografi"]
        if not d or not oz or oz.get("n", 0) < d["en_az_ornek"]:
            return None, None
        cins = "kadin" if oz["kadin"] >= d["guven"] else "erkek" if oz["kadin"] <= 1 - d["guven"] else None
        yas_ad, yas_p = max(oz["yas"].items(), key=lambda kv: kv[1])
        yas = yas_ad if yas_p >= d["yas_guven"] else None
        return cins, yas

    def _demo_say(self, z: dict, bolge: str | None = None) -> None:
        cins, yas = z["demo"]
        anahtarlar = []
        if cins:
            anahtarlar.append(cins)
        if yas:
            anahtarlar.append("yas_" + yas)
        for a in anahtarlar:
            self.p_sayi[a if bolge is None else f"b:{bolge}:{a}"] += 1

    def _demo_kesinlestir(self, z: dict, bitti: bool) -> None:
        """İz bir kez sayılır: bittiğinde ya da en az 8 örnekle cinsiyeti kesinleşince. Sonraki bölgelere girdikçe o bölgede de
        bir kez sayılır."""
        if not self.oz["demografi"] or z["demo"] is not None:
            return
        cins, yas = self._demo_karar(z.get("oz"))
        n = (z.get("oz") or {}).get("n", 0)
        if not bitti and not (cins and n >= max(8, self.oz["demografi"]["en_az_ornek"])):
            return
        z["demo"] = (cins, yas)
        if not cins and not yas:
            return
        self._demo_say(z)
        for bid in z["gectigi"]:
            self._demo_say(z, bid)

    # ----------------------------------------------------------------------------------------------- adım
    def adim(self, t: float, aralik: float, kisiler: list[dict]) -> dict:
        """Dönüş: {"etkilesim": [...], "kuyruk": {bolge: kişi}, "uzanma_baslayan": [{"iz", "bolge", "goz", "t"}],
        "uzanma_biten": [{"bolge", "goz", "bas", "son"}], "duranlar": {iz: bolge}, "uzanma_gecmis": {iz: deque}}"""
        aralik = float(min(max(aralik, 0.05), 1.0))
        self.son_aralik = aralik
        out ={"etkilesim": [], "kuyruk": {}, "uzanma_baslayan": [], "uzanma_biten": [], "duranlar": {}}
        etkin = [k for k in kisiler if k.get("durum", "izleniyor") == "izleniyor"]
        gorulen = set()
        self.p_kisi.append(len(etkin))
        kuyruk = defaultdict(int)
        for k in etkin:
            iz, b = k["iz"], k["b"]
            gorulen.add(iz)
            z = self.izler.get(iz)
            if z is None:
                z = self.izler[iz] = {"iz": iz, "ilk": t, "gecmis": deque(maxlen=24), "yavas_bas": None, "ziyaret": {}, "uzanma": {},
                                      "uzanmalar": deque(maxlen=64), "taraf": {}, "bekleyen": {}, "kasa": {}, "gectigi": set(), "demo": None, "oz": None}
            # süresi dolan ziyaret/uzanma bu karenin gözleminden ÖNCE kapanır: aradan sonra gelen yeni uzanma eskisine eklenmesin
            self._kapat_eskiler(z, t, out, son=False)
            z["son"] = t
            a = olcu.ayak(b)
            h = max(1.0, float(b[3]) - float(b[1]))
            z["gecmis"].append((t, a[0], a[1], h))
            z["hiz"] = self._hiz(z)
            yavas = z["hiz"] is not None and z["hiz"] < self.hiz_esik
            if yavas:
                z["yavas_bas"] = t if z["yavas_bas"] is None else z["yavas_bas"]
            else:
                z["yavas_bas"] = None
            if k.get("oz"):
                z["oz"] = k["oz"]
            self.p_gecen.add(iz)
            # ısı haritası
            if self.oz["yogunluk"]:
                gy, gx = olcu.izgara_hucre(a, self.W, self.H)
                self.p_yogunluk[gy, gx] += aralik
                if z["yavas_bas"] is not None and t - z["yavas_bas"] >= self.harita_durma:
                    self.p_durma[gy, gx] += aralik
            # bölgeler
            yon = olcu.govde_yonu(k.get("k"), b) if self.oz["ilgi"] else None
            icerde = set()
            for zb in self.bolgeler:
                if not self._bolgede(zb, b):
                    continue
                bid = zb["kimlik"]
                icerde.add(bid)
                self.p_b[bid]["gecen"].add(iz)
                if bid not in z["gectigi"]:
                    z["gectigi"].add(bid)
                    if z["demo"] is not None:
                        self._demo_say(z, bid)
                if zb["tur"] == "kasa":
                    z["kasa"].setdefault(bid, t)
                    if t - z["kasa"][bid] >= self.kasa_en_az and (z["hiz"] is None or z["hiz"] < max(1.5 * self.hiz_esik, 0.45)):
                        kuyruk[bid] += 1
                if zb["tur"] in ("koridor", "raf"):
                    self._ziyaret(z, iz, zb, t, aralik, yavas, yon, out)
            for bid in [b_ for b_ in z["kasa"] if b_ not in icerde]:
                del z["kasa"][bid]
            if self.ortuk and self.oz["bekleme"]:
                self._ziyaret(z, iz, {"kimlik": None, "tur": "_kare", "poly": None}, t, aralik, yavas, None, out)
            for bid, v in z["ziyaret"].items():
                if v["son"] == t and v["durdu"]:
                    out["duranlar"][iz] = bid
            if self.oz["uzanma"] and k.get("k"):
                self._uzanma(z, iz, k, t, out)
            if self.oz["giris_sayim"]:
                self._giris(z, a, h)
        # kasa kuyruğu
        for zb in self.bolgeler:
            if zb["tur"] == "kasa":
                out["kuyruk"][zb["kimlik"]] = kuyruk.get(zb["kimlik"], 0)
        if any(zb["tur"] == "kasa" for zb in self.bolgeler):
            self.p_kuyruk.append(sum(out["kuyruk"].values()))
        # süresi dolan ziyaretler, uzanmalar ve izler
        for iz, z in list(self.izler.items()):
            self._kapat_eskiler(z, t, out, son=False)
            if iz not in gorulen and t - z["son"] > IZ_BOSLUK:
                for bid in list(z["bekleyen"]):  # çizgiyi geçip hemen kaybolan (kapıdan çıkan) kişi
                    self._gecis_say(z, bid)
                self._kapat_eskiler(z, t + 1e9, out, son=True)
                self._demo_kesinlestir(z, True)
                del self.izler[iz]
            elif iz in gorulen:
                self._demo_kesinlestir(z, False)
        out["uzanma_gecmis"] = {iz: z["uzanmalar"] for iz, z in self.izler.items()}
        for iz in [i for i, d in self.alimlar.items() if not d or t - d[-1][0] > 600.0]:
            del self.alimlar[iz]
        out["alma_gecmis"] = self.alimlar
        return out

    def _ziyaret(self, z, iz, zb, t, aralik, yavas, yon, out) -> None:
        bid = zb["kimlik"] if zb["kimlik"] is not None else "_kare"
        v = z["ziyaret"].get(bid)
        if v is None:
            v = z["ziyaret"][bid] = {"bas": t, "son": t, "yavas_sn": 0.0, "durdu": False, "ilgi_sn": 0.0, "ilgi_bekleyen": 0.0,
                                     "tur": zb["tur"], "goz": None}
        v["son"] = t
        if yavas:
            v["yavas_sn"] += aralik
        if self.oz["bekleme"] and not v["durdu"] and v["yavas_sn"] >= self.durma_esik:
            v["durdu"] = True
            self.p_duran.add(iz)
            if zb["kimlik"] is not None:
                self.p_b[zb["kimlik"]]["duran"].add(iz)
        if zb["tur"] == "raf" and self.oz["ilgi"] and yavas and olcu.bolgeye_donuk(yon, z_kutu(z), zb["poly"], self.oz["ilgi"]["aci"]):
            if v["durdu"]:
                self.p_sayi[f"b:{bid}:ilgi_sn"] += aralik + v["ilgi_bekleyen"]
                v["ilgi_sn"] += aralik + v["ilgi_bekleyen"]
                v["ilgi_bekleyen"] = 0.0
            else:
                v["ilgi_bekleyen"] += aralik

    def _uzanma(self, z, iz, k, t, out) -> None:
        bilekler = olcu.bilek_uzaniyor(k["k"], k["b"], self.oz["uzanma"]["kol_aci"])
        if not bilekler:
            return
        for zb in self.bolgeler:
            if zb["tur"] != "raf" or not olcu.kutu_bolge_ortusur(zb["poly"], k["b"], 0.1):
                continue
            goz, isabet = None, False
            for p in bilekler:
                for g in zb["gozler"]:
                    x1, y1, x2, y2 = g["kutu"]
                    if x1 <= p[0] <= x2 and y1 <= p[1] <= y2:
                        goz, isabet = g["kimlik"], True
                        break
                if isabet:
                    break
                if olcu.icinde(zb["poly"], p):
                    isabet = True
            if not isabet:
                continue
            bid = zb["kimlik"]
            u = z["uzanma"].get(bid)
            if u is None:
                u = z["uzanma"][bid] = {"bas": t, "son": t, "kare": 0, "basladi": False, "goz": goz}
            u["son"] = t
            u["kare"] += 1
            u["goz"] = goz or u["goz"]
            if not u["basladi"] and u["kare"] >= self.oz["uzanma"]["en_az_kare"]:
                u["basladi"] = True
                self.p_uzanan.add(iz)
                self.p_b[bid]["uzanan"].add(iz)
                z["uzanmalar"].append((t, bid))
                out["uzanma_baslayan"].append({"iz": iz, "bolge": bid, "goz": u["goz"], "t": t})

    def _giris(self, z, a, h) -> None:
        for zb in self.giris:
            ic = olcu.taraf(zb["cizgi"], zb["ic"])
            if abs(ic) < 1e-6:
                continue
            d = olcu.taraf(zb["cizgi"], a) * (1 if ic > 0 else -1)
            bant = max(3.0, 0.04 * h)
            if abs(d) < bant:
                continue
            yan = 1 if d > 0 else -1
            bid = zb["kimlik"]
            once = z["taraf"].get(bid)
            if once is None:
                z["taraf"][bid] = yan
                continue
            if yan == once:
                z["bekleyen"].pop(bid, None)
                continue
            if not olcu.cizgi_uzerinde(zb["cizgi"], a, 0.15):
                z["taraf"][bid] = yan  # çizgi parçasının dışından dolaşarak geçti: sayılmaz
                z["bekleyen"].pop(bid, None)
                continue
            # Geçiş, yeni tarafta iki analiz karesi kalınca (ya da iz o tarafta biterse) sayılır: tek karelik ayak sıçraması
            # (örtüşme, iz karışması) sayım üretmesin.
            n = z["bekleyen"].get(bid, (yan, 0))[1] + 1 if z["bekleyen"].get(bid, (0, 0))[0] == yan else 1
            z["bekleyen"][bid] = (yan, n)
            if n >= 2:
                self._gecis_say(z, bid)

    def _gecis_say(self, z, bid) -> None:
        yan, _ = z["bekleyen"].pop(bid)
        z["taraf"][bid] = yan
        self.p_sayi["giren" if yan > 0 else "cikan"] += 1

    def _kapat_eskiler(self, z, t, out, son: bool) -> None:
        for bid, v in list(z["ziyaret"].items()):
            if t - v["son"] <= ZIYARET_BOSLUK:
                continue
            del z["ziyaret"][bid]
            if not v["durdu"]:
                continue
            sure = max(0.0, v["son"] - v["bas"])
            self.p_sayi["bekleme_sn"] += sure
            self.p_sayi["bekleme_sayi"] += 1
            if bid != "_kare":
                self.p_sayi[f"b:{bid}:bekleme_sn"] += sure
                self.p_sayi[f"b:{bid}:bekleme_sayi"] += 1
            if v["tur"] == "raf":
                out["etkilesim"].append({"tur": "etkilesim", "zaman": self._zaman(v["bas"]), "bolge": bid, "goz": None,
                                         "eylem": "durdu", "sure_sn": round(sure, 1)})
        # Uzanma, bilek UZANMA_BOSLUK boyunca (ve en az iki analiz karesi) görülmeyince biter: art arda alınan ürünler
        # (toplu alma) ayrı uzanmalar olarak sayılır, tek karelik iskelet kaybı uzanmayı bölmez.
        bosluk = max(UZANMA_BOSLUK, 1.6 * self.son_aralik)
        for bid, u in list(z["uzanma"].items()):
            if t - u["son"] <= bosluk:
                continue
            del z["uzanma"][bid]
            if not u["basladi"]:
                continue
            sure = max(u["son"] - u["bas"], 0.0)
            out["etkilesim"].append({"tur": "etkilesim", "zaman": self._zaman(u["bas"]), "bolge": bid, "goz": u["goz"],
                                     "eylem": "uzandi", "sure_sn": round(sure, 1)})
            # "iz" yalnızca motor içinde kalır (raf doğrulaması toplu_alma için kişiye bağlanır); hiçbir kayda yazılmaz.
            out["uzanma_biten"].append({"bolge": bid, "goz": u["goz"], "bas": u["bas"], "son": u["son"], "iz": z.get("iz")})

    # ----------------------------------------------------------------------------------------------- raf tarafı kancası
    def raf_isareti(self, eylem: str, bolge: str, goz: str | None, t: float, sure: float = 0.0, iz=None,
                    adet: int = 1) -> dict:
        """Raf tarafı (göz değişimi) bir uzanmayı alma ya da geri koyma olarak doğruladığında çağrılır. eylem: "aldi" |
        "birakti". Pencere sayısına ekler ve kuyruğa bırakılacak etkileşim kaydını döndürür (iz ve adet kayda girmez)."""
        self.raf_isaret = True
        if eylem == "aldi" and iz is not None:
            # toplu_alma için: kişinin raf doğrulamasıyla aldığı ürün sayısı (iz, kayda yazılmaz)
            d = self.alimlar.setdefault(iz, deque(maxlen=64))
            d.append((t, bolge, max(1, int(adet or 1))))
        a = "alan" if eylem == "aldi" else "birakan"
        self.p_sayi[a] += 1
        self.p_sayi[f"b:{bolge}:{a}"] += 1
        return {"tur": "etkilesim", "zaman": self._zaman(t), "bolge": bolge, "goz": goz, "eylem": eylem, "sure_sn": round(sure, 1)}

    # ----------------------------------------------------------------------------------------------- ölçüm
    def olcum(self) -> tuple[dict, dict | None]:
        """Pencerenin sayıları (sözleşme 4.2) ve ısı ızgarası; pencere sıfırlanır."""
        for z in self.izler.values():
            self._demo_kesinlestir(z, False)
        v: dict = {"gecen": len(self.p_gecen), "kisi_ort": round(float(np.mean(self.p_kisi)), 2) if self.p_kisi else 0.0}
        if self.oz["bekleme"]:
            v.update(duran=len(self.p_duran), bekleme_sn=round(self.p_sayi["bekleme_sn"], 1), bekleme_sayi=int(self.p_sayi["bekleme_sayi"]))
        if self.oz["uzanma"]:
            v["uzanan"] = len(self.p_uzanan)
        if self.raf_isaret:
            v.update(alan=int(self.p_sayi["alan"]), birakan=int(self.p_sayi["birakan"]))
        if self.oz["giris_sayim"] and self.giris:
            v.update(giren=int(self.p_sayi["giren"]), cikan=int(self.p_sayi["cikan"]))
        if self.p_kuyruk:
            v.update(kuyruk_ort=round(float(np.mean(self.p_kuyruk)), 2), kuyruk_en_cok=int(max(self.p_kuyruk)))
        demo = ("kadin", "erkek", "yas_genc", "yas_yetiskin", "yas_yasli")
        if self.oz["demografi"]:
            for a in demo:
                v[a] = int(self.p_sayi[a])
        for zb in self.bolgeler:
            bid = zb["kimlik"]
            v[f"b:{bid}:gecen"] = len(self.p_b[bid]["gecen"])
            if zb["tur"] in ("koridor", "raf") and self.oz["bekleme"]:
                v[f"b:{bid}:duran"] = len(self.p_b[bid]["duran"])
                v[f"b:{bid}:bekleme_sn"] = round(self.p_sayi[f"b:{bid}:bekleme_sn"], 1)
                v[f"b:{bid}:bekleme_sayi"] = int(self.p_sayi[f"b:{bid}:bekleme_sayi"])
            if zb["tur"] == "raf":
                if self.oz["uzanma"]:
                    v[f"b:{bid}:uzanan"] = len(self.p_b[bid]["uzanan"])
                if self.oz["ilgi"]:
                    v[f"b:{bid}:ilgi_sn"] = round(self.p_sayi[f"b:{bid}:ilgi_sn"], 1)
                if self.raf_isaret:
                    v[f"b:{bid}:alan"] = int(self.p_sayi[f"b:{bid}:alan"])
                    v[f"b:{bid}:birakan"] = int(self.p_sayi[f"b:{bid}:birakan"])
            if self.oz["demografi"]:
                for a in demo:
                    v[f"b:{bid}:{a}"] = int(self.p_sayi[f"b:{bid}:{a}"])
        izgara = None
        if self.oz["yogunluk"]:
            izgara = {"gen": olcu.IZGARA[0], "yuk": olcu.IZGARA[1], "katmanlar": {
                "yogunluk": [[round(float(x), 2) for x in s] for s in self.p_yogunluk],
                "durma": [[round(float(x), 2) for x in s] for s in self.p_durma]}}
        self._pencere()
        return v, izgara

    def bitir(self, t: float) -> list[dict]:
        """Akış bitti: açık ziyaret ve uzanmaları kapatır, izlerin demografisini sayar. Dönüş: etkileşim kayıtları."""
        out = {"etkilesim": [], "uzanma_biten": []}
        for z in self.izler.values():
            self._kapat_eskiler(z, t + 1e9, out, son=True)
            self._demo_kesinlestir(z, True)
        self.izler = {}
        return out["etkilesim"]


def z_kutu(z: dict):
    """İzin son kutusu yerine ayak geçmişinden yaklaşık kutu (yalnızca bolgeye_donuk için: ayak ve boy)."""
    t, x, y, h = z["gecmis"][-1]
    return (x - 0.2 * h, y - h, x + 0.2 * h, y)
