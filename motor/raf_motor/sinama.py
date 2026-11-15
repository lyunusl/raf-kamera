"""Özelliklerin sınama sonucu (panelde gösterilir). katalog.KURALLAR[...]["durum"] buradan gelir.

Her kayıt: {"durum": "hazir" | "sinirli" | "deneysel", "sonuc": kısa Türkçe metin, "sayilar": {...}, "goruntu": hangi
görüntülerle, "tarih": "YYYY-AA-GG"}. Burada olmayan özellik "deneysel" sayılır.

Kural (2026-11-15): "hazir" = programla gelen dokuz örnek mağaza klibinde gerçek AugeLab Studio koşusunda (arayüzsüz,
"Örnek videoları çözümle") doğru; "sinirli" = kısmen doğru; "deneysel" = bu kliplerde çalıştığı gösterilmedi.
Klipler üretilmiş (yapay zekâ ile oluşturulmuş) 10 sn'lik görüntülerdir, gerçek bir mağazadan değildir; ayarları
(bölgeler, gözler, kısa süreler) bu kliplere göre yapılmıştır. Gerçek mağazada ayrıca sınanmalıdır.
Önceki sınamalar (kafe videoları, Commons raf fotoğrafları): egitim/dene_musteri_video.py, dene_raf_durum.py, dene_urun.py,
dene_etiket.py, dene_motor_birlesik.py. "Birlikte" ölçüleri panelde hesaplanır.
"""
_K = "örnek mağaza klipleri (üretilmiş, 10 sn), gerçek Studio"
_T = "2026-11-15"

SINAMA: dict = {
    "bos_raf": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                "sonuc": "Üretilmiş 3 raf klibinde boş 5 gözün 5'i bildirildi (raf-bos 2, raf-alma 1, raf-yanlis 2); "
                         "dolu gözlerde yanlış boş uyarısı yok. Gerçek mağaza görüntüsüyle sınanmadı.",
                "sayilar": {"bulunan": "5/5", "yanlis_uyari": 0, "klip": 3}},
    "az_stok": {"durum": "deneysel", "tarih": _T, "goruntu": _K,
                "sonuc": "raf-alma'da 5 kavanozdan 2'ye inen göz klip bitmeden 'az' olmadı (müşteri önündeyken karar "
                         "verilmiyor). Kliplerde gösterilmedi; düzenlenmiş fotoğraflarda 3/5.",
                "sayilar": {"klipte_az": "0/1", "foto_az": "3/5"}},
    "yanlis_urun": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                    "sonuc": "raf-yanlis: sarı kutu mavi şişe gözüne konunca yanlış ürün bildirildi (1/1); diğer 44 gözde "
                             "yanlış uyarı yok. Yalnız bir olay örneği var.",
                    "sayilar": {"bulunan": "1/1", "yanlis_uyari": 0}},
    "etiket_yok": {"durum": "deneysel", "tarih": _T, "goruntu": "Commons etiket fotoğrafları (kliplerde okunur etiket yok)",
                   "sonuc": "Örnek kliplerde etiketler okunacak boyutta değil, sınanmadı. Düzenlenmiş fotoğraflarda etiketi "
                            "kaldırılan 4 kutunun 3'ü bulundu.",
                   "sayilar": {"klip": "sınanmadı", "foto_yok_dendi": "3/4"}},
    "fiyat_farkli": {"durum": "deneysel", "tarih": _T, "goruntu": "Commons etiket fotoğrafları (kliplerde okunur etiket yok)",
                     "sonuc": "Örnek kliplerde sınanmadı. Fotoğraflarda 29 etiketin 26'sı doğru okundu.",
                     "sayilar": {"klip": "sınanmadı", "foto_okunan": "26/29"}},
    "yogunluk": {"durum": "sinirli", "tarih": _T, "goruntu": _K,
                 "sonuc": "Koridor klibinde 5 kişi 7 iz olarak sayıldı (örtülme izi bölüyor); harita kişilerin durduğu "
                          "yerleri gösteriyor.",
                 "sayilar": {"koridor_kisi": "5", "koridor_iz": 7}},
    "bekleme": {"durum": "sinirli", "tarih": _T, "goruntu": _K,
                "sonuc": "Raf kliplerinde duran 6 müşterinin 5'i durdu sayıldı (kısa duraklayan 1 kaçtı); koridorda 3 "
                         "duran kişiye 5 dendi (bölünen izler).",
                "sayilar": {"raf_duran": "5/6", "koridor": "5 (göz: 3)"}},
    "ilgi": {"durum": "sinirli", "tarih": _T, "goruntu": _K,
             "sonuc": "Gövde yönü (bakış değil). Rafa dönük duran müşterilerde süre yazılıyor; saniye düzeyinde göz "
                      "kontrolüyle doğrulanmadı.", "sayilar": {}},
    "uzanma": {"durum": "sinirli", "tarih": _T, "goruntu": _K,
               "sonuc": "Gerçek uzanmalar yakalandı (raf-bos boş göze, raf-alma 2 müşteri, raf-yanlis); toplu klipte ~9 "
                        "alıştan 7'si ayrı sayıldı; bazı kliplerde 0,2 sn'lik fazladan uzanmalar var.",
                "sayilar": {"toplu": "7/~9", "fazla_kisa_uzanma": 3}},
    "alma": {"durum": "hazir", "tarih": _T, "goruntu": _K,
             "sonuc": "raf-alma: 2 müşterinin 2 alışı doğru gözde doğrulandı; raf-yanlis: kutunun alındığı göz 1/1; "
                      "raf-bos'ta (boş göze uzanma) sahte alma yok. Aynı kliplere göre ayarlandı.",
             "sayilar": {"dogrulanan": "3/3", "sahte": 0}},
    "geri_koyma": {"durum": "sinirli", "tarih": _T, "goruntu": _K,
                   "sonuc": "raf-yanlis: kutunun konduğu göz 1/1 bulundu; aynı klipte alt rafta 1 sahte geri koyma.",
                   "sayilar": {"bulunan": "1/1", "sahte": 1}},
    "demografi": {"durum": "deneysel", "tarih": _T, "goruntu": _K,
                  "sonuc": "Kasa klibinde görünen 3-4 kadının hiçbiri kadın sayılmadı (yalnız 4 erkek); koridorda 7 izin "
                           "4'ünde karar (2 kadın, 2 erkek; gözle 3 kadın, 2 erkek). Varsayılan kapalı.",
                  "sayilar": {"kasa_kadin": "0/3-4", "koridor_karar": "4/7"}},
    "giris_sayim": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                    "sonuc": "Giriş klibinde giren 3/3, çıkan 2/2.", "sayilar": {"giren": "3/3", "cikan": "2/2"}},
    "kasa_kuyrugu": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                     "sonuc": "Kasa klibinde kuyruk en çok 7 (gözle 7); eşik 5'te uyarı açıldı ve kapandı.",
                     "sayilar": {"en_cok": "7/7", "uyari": "1/1"}},
    "toplu_alma": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                   "sonuc": "Toplu klipte (göz tanımsız raf) bir kişinin art arda alışları 7 uzanma sayıldı (~9 kutu), "
                            "uyarı açıldı. Gözlü rafta doğrulanmış alım sayısıyla çalışır; bu kliplerde gösterilmedi.",
                   "sayilar": {"uyari": "1/1", "uzanma": "7/~9"}},
    "dolap_acik": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                   "sonuc": "Dolap klibinde açık bırakılan 2. dolap kapağı, müşteri gidince bildirildi (1/1); diğer 3 dolapta "
                            "uyarı yok. Kayıtlı (kapakları kapalı) referans karesi gerekir.",
                   "sayilar": {"bulunan": "1/1", "yanlis_uyari": 0}},
    "dokulme": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                "sonuc": "Dökülme klibinde zemindeki leke bildirildi (1/1); palet ayrıca dökülme sayılmadı. Boş koridorun "
                         "kayıtlı referans karesi gerekir.", "sayilar": {"bulunan": "1/1", "yanlis_uyari": 0}},
    "tikali_koridor": {"durum": "hazir", "tarih": _T, "goruntu": _K,
                       "sonuc": "Dökülme klibinde koridora bırakılan palet tıkalı koridor olarak bildirildi (1/1).",
                       "sayilar": {"bulunan": "1/1"}},
}
