"""Preview how CoH two-color weapon tinting lands on a base + mask texture pair.

usage: python tools/mask_preview.py <out.png> <base.png> <mask.png> [<base.png> <mask.png> ...]

Approximates the game's blend: color = lerp(primary, secondary, mask) * base.
Which slot black vs white maps to is unconfirmed; the sheet shows both colorways.
"""
import sys

from PIL import Image, ImageDraw

PALETTES = [((200, 40, 40), (230, 200, 60)), ((40, 90, 200), (220, 220, 230))]
CELL_H = 160


def tint(base, mask, c1, c2):
    base = base.convert("RGB")
    mask = mask.convert("L").resize(base.size, Image.BILINEAR)
    solid1 = Image.new("RGB", base.size, c1)
    solid2 = Image.new("RGB", base.size, c2)
    color = Image.composite(solid2, solid1, mask)
    return Image.fromarray(__import__("numpy").uint8(
        __import__("numpy").asarray(color, dtype="float32") * __import__("numpy").asarray(base, dtype="float32") / 255))


def fit(img, h):
    w = max(1, round(img.width * h / img.height))
    return img.resize((w, h), Image.NEAREST if img.width < 200 else Image.BILINEAR)


def main():
    out, pairs = sys.argv[1], sys.argv[2:]
    rows = []
    for base_p, mask_p in zip(pairs[0::2], pairs[1::2]):
        base, mask = Image.open(base_p), Image.open(mask_p)
        cells = [("base", base.convert("RGB")), ("mask", mask.convert("RGB"))]
        for c1, c2 in PALETTES:
            cells.append((f"tint {c1}/{c2}", tint(base, mask, c1, c2)))
        rows.append((base_p.replace("\\", "/").split("/")[-1], [(t, fit(i, CELL_H)) for t, i in cells]))
    width = max(sum(i.width + 12 for _, i in cells) for _, cells in rows) + 12
    height = sum(CELL_H + 44 for _ in rows) + 12
    sheet = Image.new("RGB", (width, height), (24, 26, 30))
    draw = ImageDraw.Draw(sheet)
    y = 12
    for name, cells in rows:
        draw.text((12, y), name, fill=(230, 230, 230))
        x = 12
        for label, img in cells:
            sheet.paste(img, (x, y + 16))
            draw.text((x, y + 18 + CELL_H), label, fill=(150, 160, 170))
            x += img.width + 12
        y += CELL_H + 44
    sheet.save(out)
    print(out, sheet.size)


if __name__ == "__main__":
    main()
