import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

size = 512
image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((28, 28, 484, 484), radius=96, fill="#1467D9")

windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
font_path = windows_fonts / "arialbd.ttf"
try:
    font = ImageFont.truetype(str(font_path), 150)
except OSError:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 150)

label = "PDF"
left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
text_width = right - left
text_height = bottom - top
draw.text(
    ((size - text_width) / 2 - left, (size - text_height) / 2 - top - 3),
    label,
    font=font,
    fill="#FFFFFF",
)

image.save(
    ASSETS / "vf-pdf-helper.ico",
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
image.save(ASSETS / "vf-pdf-helper.png")
