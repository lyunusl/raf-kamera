"""kurulum/raf-kamera.ico dosyasını çizer (depoda ikili çizim tutulmasın diye): koyu camgöbeği zemin üstünde üç raf
çizgisi ve raflarda camgöbeği / yeşil ürün kutuları. Panelin renkleriyle aynıdır (--ray #0d2523, --vurgu #0f8b7d,
--isik #7ed957).

  python kurulum/simge.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024  # büyük çizilip küçültülür: kenarlar yumuşak olsun
ZEMIN, CAMGOBEGI, YESIL, RAF = (13, 37, 35), (51, 179, 163), (126, 217, 87), (207, 238, 230)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((32, 32, S - 32, S - 32), radius=224, fill=ZEMIN)
# raflardaki ürünler: (sol, üst, sağ, alt, renk) 32'lik ızgarada; favicon ile aynı yerleşim
kutular = [(8, 6.5, 13, 11, CAMGOBEGI), (14.5, 6.5, 18.5, 11, YESIL),
           (8, 14, 11.5, 18.5, YESIL), (13, 14, 18.5, 18.5, CAMGOBEGI), (20, 14, 24, 18.5, CAMGOBEGI),
           (17, 21.5, 24, 26, YESIL)]
k = S / 32
for x1, y1, x2, y2, renk in kutular:
    d.rounded_rectangle((x1 * k, y1 * k, x2 * k, y2 * k), radius=int(1.1 * k), fill=renk)
for y in (11.5, 19, 26.5):  # raf çizgileri
    d.rounded_rectangle((5.6 * k, (y - 0.85) * k, 26.4 * k, (y + 0.85) * k), radius=int(0.85 * k), fill=RAF)

out = Path(__file__).with_name("raf-kamera.ico")
img.resize((256, 256), Image.LANCZOS).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out.name)
