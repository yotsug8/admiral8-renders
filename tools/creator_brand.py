"""Small creator signature and outlined titles, using the repository's licensed fonts."""
import json
from itertools import groupby
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BRAND = json.loads((ROOT / 'assets/creator/brand.json').read_text(encoding='utf-8'))
SS = 3


def title(width, height, lines):
    """Lines are (text, font-size/width, palette-key); no wording is imposed."""
    image = Image.new('RGBA', (width * SS, height * SS))
    draw = ImageDraw.Draw(image)
    y = height * .085
    for text, fraction, color in lines:
        size = width * fraction
        fonts = {key: ImageFont.truetype(str(ROOT / 'fonts' /
                 f"{BRAND['title_font']}-{script}-900-normal.woff2"), round(size * SS))
                 for key, script in [(True, 'cyrillic'), (False, 'latin')]}
        runs = [(key, ''.join(chars)) for key, chars in
                groupby(text, key=lambda c: 0x400 <= ord(c) <= 0x52f)]
        advance = sum(fonts[key].getlength(chunk) for key, chunk in runs)
        if advance > width * SS * .9:
            raise ValueError('Title is too wide: shorten or reduce its font size')
        x = (width * SS - advance) / 2
        stroke = max(2, round(width * .0037 * SS))
        for key, chunk in runs:
            font = fonts[key]
            top = font.getbbox(chunk)[1]
            draw.text((x + SS, y * SS - top + 2 * SS), chunk, font=font,
                      fill=(17, 9, 29, 230), stroke_width=stroke + SS,
                      stroke_fill=(17, 9, 29, 210))
            draw.text((x, y * SS - top), chunk, font=font,
                      fill=tuple(BRAND['colors'][color]), stroke_width=stroke,
                      stroke_fill=tuple(BRAND['colors']['outline']))
            x += font.getlength(chunk)
        y += size * .92 + height * .009
    return image.resize((width, height), Image.Resampling.LANCZOS)


def signature(width, height):
    """Black-backed logo layer for screen compositing; opacity is applied by the editor."""
    if width <= 0 or height <= 0:
        raise ValueError('Canvas dimensions must be positive')
    image = Image.new('RGB', (width, height), 'black')
    with Image.open(ROOT / BRAND['logo']) as source:
        logo = source.convert('RGB')
        target_width = round(min(width, height) * BRAND['signature_width'])
        logo = logo.resize((target_width, round(target_width * logo.height / logo.width)),
                           Image.Resampling.LANCZOS)
    x = round(width * BRAND['signature_position'][0])
    y = round(height * BRAND['signature_position'][1])
    if x < 0 or y < 0 or x + logo.width > width or y + logo.height > height:
        raise ValueError('Logo does not fit this aspect ratio; adjust brand placement or size')
    image.paste(logo, (x, y))
    return image


def main():
    """Export the reusable layer without silently replacing another asset."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--height', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    layer = signature(args.width, args.height)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('xb') as target:
        layer.save(target, format='PNG')
    print(args.out.resolve())
    print(f"FFmpeg blend=all_mode={BRAND['signature_blend']}:all_opacity={BRAND['signature_opacity']}")
    print('This is a black-backed screen layer, not an RGBA overlay. Keep RGB until final video range conversion.')


if __name__ == '__main__':
    main()
