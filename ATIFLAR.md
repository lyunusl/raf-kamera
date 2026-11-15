# Atıflar ve üçüncü taraf bileşenler

Raf Kamera'nın kodu GNU AGPL-3.0 lisanslıdır. [Lisans](LICENSE)

## Modeller

Raf Kamera yedi yapay zekâ modeli ve etiket okuyucunun karakter listesini kullanır. Bunlar programın içinde gelmez:
kurulum sırasında (ya da ilk açılışta) Google Drive'dan indirilir ve her biri `studio_kurulum.MODELLER` tablosundaki boyut
ve SHA-256 özetiyle doğrulanır. Modeller AugeLab Studio'nun içinde çalışır. Özgün ağırlıklar aşağıdaki kaynaklarda
herkese açıktır.

| Dosya | Ne yapar | Kaynak | Lisans |
|---|---|---|---|
| `kisi.onnx` | Kişi dedektörü | [Ultralytics YOLO11s](https://docs.ultralytics.com/models/yolo11/), ONNX'e çevrildi | AGPL-3.0 |
| `iskelet.onnx` | Vücut noktaları (uzanma ve gövde yönü için) | [Ultralytics YOLO11n-pose](https://docs.ultralytics.com/tasks/pose/), ONNX'e çevrildi | AGPL-3.0 |
| `ozellik.onnx` | Kişi özellikleri (yaş grubu ve cinsiyet tahmini) | [PaddleClas](https://github.com/PaddlePaddle/PaddleClas) PULC `person_attribute`, ONNX'e çevrildi | Apache-2.0 |
| `urun.onnx` | Raftaki ürün dedektörü | [YOLO11s ürün dedektörü (chistopat)](https://huggingface.co/chistopat/sku110k-yolo11-object-detector), ONNX'e çevrildi | AGPL-3.0 |
| `gomme.onnx` | Ürün görüntüsü benzerliği (göz ve planogram eşleme) | [timm/efficientnet_b0.ra_in1k](https://huggingface.co/timm/efficientnet_b0.ra_in1k), ONNX'e çevrildi | Apache-2.0 |
| `etiket-bul.onnx` | Fiyat etiketinde yazı bölgesi bulma | [PaddlePaddle/PP-OCRv5_mobile_det_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx) | Apache-2.0 |
| `etiket-oku.onnx` | Etiket yazısını okuma (Latin alfabesi, Türkçe harfler dahil) | [PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx](https://huggingface.co/PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx) | Apache-2.0 |
| `etiket-oku.txt` | Etiket okuyucunun karakter listesi | Aynı modelin karakter listesi | Apache-2.0 |

Lisans metinleri: [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html) · [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0)

### İndirme yeri

Dosyalar Google Drive'dadır. Kimlikler, boyutlar ve SHA-256 özetleri `studio_kurulum.py` içindeki `MODELLER`
tablosundadır; kurulum dosyasının listesi (`kurulum/modeller.iss`) aynı tablodan üretilir.

| İndirilen dosya | Boyut | Google Drive kimliği |
|---|---|---|
| `kisi.onnx.isgm` | 38,6 MB | `1x85kHFRrm0fxlkaUCxyunnTsuQ6RyzSO` |
| `iskelet.onnx.isgm` | 12,1 MB | `1QkOXSoLbWL5XyKGBKV0IUSYs8sTBDhua` |
| `ozellik.onnx.isgm` | 6,9 MB | `1w4AVdk_GGgSuxtblnLdN55L-ILk5jXG_` |
| `urun.onnx.isgm` | 37,9 MB | `1R_OPYNjVH-KqnGDe7qA_7HuQPjFeM-R9` |
| `gomme.onnx.isgm` | 16,0 MB | `1Qa1_Ird3gibphHlo6kDqunSd4nmeYoon` |
| `etiket-bul.onnx.isgm` | 4,8 MB | `1P7vui5JN-0Bdc1SoQFMODN9P4b2JVLL9` |
| `etiket-oku.onnx.isgm` | 8,0 MB | `14VbN6k1xJLgAcWzePM5vTg2xc7hbEH7-` |
| `etiket-oku.txt` | 2,6 KB | `1Ku3NXFD6mYfCpM1rs72QK_6iO28rJt88` |

Toplam yaklaşık 124 MB.

## Örnek videolar ve görseller

- `ornekler/videolar` altındaki dokuz klip yapay zekâ ile üretilmiştir; gerçek bir mağazadan alınmamıştır. `ornekler/urunler/gorsel` altındaki ürün görselleri bu kliplerden kırpılmıştır.

## Windows paketi

- FFmpeg 9.0.2 (Gyan Essentials, GPLv3), `imageio-ffmpeg` 0.8.1 üzerinden ayrı bir işlem olarak çalışır. [Derleme ve bağımlılık bilgileri](https://www.gyan.dev/ffmpeg/builds/) · [FFmpeg kaynak kodu](https://github.com/FFmpeg/FFmpeg/commit/946fcce07b) · [Lisans](https://www.gnu.org/licenses/gpl-3.0.html)
- Certifi 2026.10.23 (MPL-2.0), resmî Studio kurucusu ve modeller indirilirken TLS doğrulamasında kullanılır. [Kaynak paket ve lisans bilgisi](https://pypi.org/project/certifi/2026.10.23/)
- ONNX Runtime 1.31.1 (MIT), AugeLab Studio'da yoksa modelleri çalıştırmak için motorla birlikte gelir. [Kaynak kodu ve lisans](https://github.com/microsoft/onnxruntime)
- Model paketinin bileşeninde kullanılan Rust kitaplıklarının bildirimleri kurulumla gelen `RUST-NOTICES.txt` dosyasındadır.
