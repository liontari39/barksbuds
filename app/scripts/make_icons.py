#!/usr/bin/env python3
"""Build Capacitor icon + splash sources from the Jack logo (public/img/icon-512.png)."""
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: python3 -m pip install Pillow")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "public/img/icon-512.png"
OUT = Path(__file__).resolve().parents[1] / "resources"
WWW = Path(__file__).resolve().parents[1] / "www"
CREAM = (255, 248, 234, 255)


def fit(im, size, pad=0):
    canvas = Image.new("RGBA", (size, size), CREAM)
    inner = size - pad * 2
    logo = im.convert("RGBA")
    logo.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    canvas.alpha_composite(logo, (x, y))
    return canvas


def main():
    im = Image.open(SRC)
    OUT.mkdir(parents=True, exist_ok=True)
    WWW.mkdir(parents=True, exist_ok=True)
    icon = fit(im, 1024, pad=80)
    icon.save(OUT / "icon.png", "PNG")
    (WWW / "icon.png").write_bytes((OUT / "icon.png").read_bytes())
    # 2732 splash (iPad Pro 12.9 @2x), logo centered
    splash = Image.new("RGBA", (2732, 2732), CREAM)
    logo = fit(im, 1024, pad=80)
    x = (2732 - logo.width) // 2
    y = (2732 - logo.height) // 2
    splash.alpha_composite(logo, (x, y))
    splash.save(OUT / "splash.png", "PNG")
    print(f"wrote {OUT/'icon.png'} and {OUT/'splash.png'}")


if __name__ == "__main__":
    main()
