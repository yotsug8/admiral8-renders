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
    image = Image.new('RGB', (width, height), 'black')
    with Image.open(ROOT / BRAND['logo']) as source:
        logo = source.convert('RGB')
        target_width = round(width * BRAND['signature_width'])
        logo = logo.resize((target_width, round(target_width * logo.height / logo.width)),
                           Image.Resampling.LANCZOS)
    image.paste(logo, (round(width * BRAND['signature_position'][0]), round(height * BRAND['signature_position'][1])))
    return image
