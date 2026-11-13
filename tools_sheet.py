import sys, glob, os
os.makedirs("out", exist_ok=True)
from PIL import Image, ImageDraw
ver, cols = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4
fs = sorted(glob.glob(f"out/stills/{ver}-*.png"))
w, h = 640, 360
rows = (len(fs) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w, rows * h), "black")
for i, f in enumerate(fs):
    im = Image.open(f).convert("RGB").resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(im); d.text((8, 6), os.path.basename(f)[len(ver)+1:-4], fill=(255, 255, 0))
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
sheet.save(f"out/{ver}-sheet.png")
print(len(fs))
