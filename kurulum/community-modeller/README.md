# Model paketi

Raf Kamera'nın model paketinin küçük dosyaları. Büyük model dosyaları burada değil, Google Drive'dadır.

- `community-paket.json`: paket kimliği
- `goruntu-<id>.dll`: modelleri AugeLab Studio'nun içinde açan bileşen
- `RUST-NOTICES.txt`: bileşenin bağımlılık bildirimleri
- `etiket-oku.txt`: etiket okuyucunun karakter listesi (o da Google Drive'dan indirilir)
- `<model>.onnx.isgm`: model dosyaları (büyük; depoya konmaz, Google Drive'dan indirilir)

İndirilecek dosyalar `studio_kurulum.MODELLER` tablosuna yazılır (ad, boyut, SHA-256, Drive kimliği). Tablo
değişince `python kurulum/modeller_iss.py` ile `kurulum/modeller.iss` yeniden üretilir.

Paket yokken `kurulum\derle.cmd` durur; yalnızca geliştirme derlemesi yapılabilir: `kurulum\derle.cmd duz`.
