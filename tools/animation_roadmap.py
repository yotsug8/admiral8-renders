"""Render the evidence-based animation roadmap as an editable SVG and PNG.

Data: docs/animation_roadmap.json. No network or model resources needed.
Use --font/--bold-font or ROADMAP_FONT/ROADMAP_BOLD_FONT off Windows.
"""
import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
W, H, SCALE = 1800, 3200, 2
BG, PANEL, EDGE = '#101b25', '#192832', '#3a464b'
WHITE = '#f7efe2'


class Poster:
    def __init__(self, regular, bold):
        self.fonts = (regular, bold)
        self.image = Image.new('RGB', (W*SCALE, H*SCALE), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title description">',
                    '<title id="title">Дорожная карта обучения анимации</title>',
                    '<desc id="description">Проверенные пробы, текущая задача и шесть дальнейших этапов, охватывающих двенадцать направлений. Частичная проверка не означает освоение всего направления.</desc>']
        self.rect(0, 0, W, H, BG)

    def rect(self, x, y, w, h, color, radius=0, outline=None):
        box=tuple(v*SCALE for v in (x,y,x+w,y+h))
        self.draw.rounded_rectangle(box, radius=radius*SCALE, fill=color,
                                    outline=outline, width=SCALE)
        border=f' stroke="{outline}"' if outline else ''
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{color}"{border}/>')

    def line(self, x1, y1, x2, y2, color=EDGE, width=2):
        self.draw.line(tuple(v*SCALE for v in (x1,y1,x2,y2)), fill=color,width=width*SCALE)
        self.svg.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="{width}"/>')

    def polygon(self, points, color):
        self.draw.polygon([(x*SCALE, y*SCALE) for x,y in points], fill=color)
        coords=' '.join(f'{x},{y}' for x,y in points)
        self.svg.append(f'<polygon points="{coords}" fill="{color}"/>')

    def picture(self, path, x, y, w, h, top=False, contain=False):
        with Image.open(path) as opened:
            mime = Image.MIME.get(opened.format)
            source = opened.convert('RGB')
        if mime is None:
            raise ValueError('Unknown artwork MIME type: '+str(path))
        if contain:
            placed=ImageOps.pad(source,(w*SCALE,h*SCALE),Image.Resampling.LANCZOS,color=PANEL)
        else:
            placed=ImageOps.fit(source,(w*SCALE,h*SCALE),Image.Resampling.LANCZOS,
                                centering=(.5,0 if top else .5))
        self.image.paste(placed,(x*SCALE,y*SCALE))
        encoded=base64.b64encode(path.read_bytes()).decode()
        align='xMidYMin' if top else 'xMidYMid'
        fit='meet' if contain else 'slice'
        self.svg.append(f'<image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="{align} {fit}" href="data:{mime};base64,{encoded}"/>')

    def text(self, x, y, value, size=24, color=WHITE, bold=False):
        font=ImageFont.truetype(str(self.fonts[int(bold)]),size*SCALE)
        if x+font.getlength(value)/SCALE>W-32:
            raise ValueError('Text exceeds poster width: '+value)
        self.draw.text((x*SCALE,y*SCALE),value,font=font,fill=color,anchor='lt')
        family = html.escape(font.getname()[0], quote=True)
        self.svg.append(f'<text x="{x}" y="{y}" dominant-baseline="text-before-edge" font-family="{family},sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{html.escape(value)}</text>')

    def paragraph(self, x, y, value, width, size=23, color=WHITE, lines=2, bold=False):
        font=ImageFont.truetype(str(self.fonts[int(bold)]),size*SCALE)
        result=[];line=''
        for word in value.split():
            candidate=(line+' '+word).strip()
            if font.getlength(candidate)>width*SCALE:
                if not line:raise ValueError('Word exceeds available width: '+word)
                result.append(line);line=word
            else:line=candidate
        if line:result.append(line)
        if len(result)>lines:raise ValueError('Text exceeds reserved lines: '+value)
        for i,line in enumerate(result):self.text(x,y+i*(size+7),line,size,color,bold)


def render(data, regular, bold, assets):
    p=Poster(regular,bold)
    ink, paper = '#172c30', '#f4efdf'
    green, pale_green = '#195c48', '#e2edcf'
    orange, rule = '#f2a548', '#c5c9ba'
    # Editorial composition: real frame, three distinct status zones, short copy.
    p.rect(0,0,W,H,paper)
    p.rect(0,0,W,720,ink)
    p.picture(assets/data['artwork'],860,0,940,720)
    p.polygon([(0,0),(950,0),(850,720),(0,720)],ink)
    p.rect(72,64,9,38,orange)
    p.text(103,66,'МАСТЕРСКАЯ АНИМАЦИИ',32,paper,True)
    p.text(72,164,'ОТ ПОЗЫ',112,paper,True)
    p.text(72,298,'ДО ИСТОРИИ',105,pale_green,True)
    p.text(79,461,'Дорожная карта',46,paper)
    p.text(79,532,'12 направлений · один готовый ролик',28,'#c4cfc4')
    p.line(79,610,755,610,'#576962',2)
    p.text(79,643,data['updated'],28,paper)
    p.text(455,643,f"РЕДАКЦИЯ {data['revision']:02d}",28,'#c4cfc4')
    # Section colors carry meaning; no miniature legend or repeated status badges.
    p.rect(0,720,W,670,pale_green)
    p.text(72,764,'01',64,green,True)
    p.text(193,765,'УЖЕ РАБОТАЕТ',64,green,True)
    p.text(75,855,'Проверено в коротких пробах. Весь навык этим ещё не закрыт.',32,green)
    for i,item in enumerate(data['previews']):
        x=72+560*i
        p.rect(x,927,536,286,ink)
        p.picture(assets/item['file'],x+5,932,526,276,contain=True)
        p.rect(x,927,94,42,green)
        p.text(x+16,934,'ЕСТЬ',24,'#ffffff',True)
        p.text(x,1240,item['poster_title'],36,green,True)
        p.paragraph(x,1294,item['poster_note'],520,28,ink,2)
    # Active work is visually separated from both passed studies and backlog.
    p.rect(0,1390,W,454,orange)
    p.text(72,1431,'02',64,ink,True)
    p.text(193,1432,'СЕЙЧАС В РАБОТЕ',64,ink,True)
    p.text(76,1541,data['poster']['active_title'],48,ink,True)
    p.text(76,1617,data['poster']['active_note'],32,ink)
    for i,label in enumerate(data['poster']['active_steps']):
        x=76+560*i
        p.line(x,1700,x+510,1700,ink,2)
        p.text(x,1727,f'{i+1:02d}',32,ink,True)
        p.text(x+66,1727,label,32,ink)
    # Six reader-facing milestones cover all twelve technical directions.
    p.text(72,1897,'03',64,ink,True)
    p.text(193,1898,'ЧТО ЕЩЁ ПРЕДСТОИТ',64,ink,True)
    p.text(76,1996,'До устойчивого качества — эти задачи. Часть уже начата.',32,'#54645b')
    for i,item in enumerate(data['poster']['milestones']):
        x=76+(i%2)*850; y=2090+(i//2)*218
        p.line(x,y,x+800,y,rule,2)
        p.text(x,y+27,f'{i+1:02d}',32,green,True)
        p.text(x+78,y+24,item['title'],40,ink,True)
        p.paragraph(x+78,y+88,item['text'],710,30,'#46594f',3)
    p.rect(0,2770,W,430,ink)
    p.rect(72,2822,205,43,pale_green)
    p.text(91,2829,'НАША ЦЕЛЬ',25,ink,True)
    p.text(72,2894,'ГОТОВЫЙ РОЛИК.',78,paper,True)
    p.text(76,3001,'Понятная история. Живые герои. Звук и законченный вид.',34,paper)
    p.text(76,3060,'Затем — повторить это качество на новой сцене.',32,'#bfcdc0')
    p.line(76,3121,1724,3121,'#576962',1)
    p.text(76,3146,'Статусы — по проверенным результатам. Без выдуманных процентов и сроков.',25,'#aebfb5')
    p.svg.append('</svg>')
    return p


def check_outputs(outputs, inputs):
    """Keep generated files distinct from one another and from their inputs."""
    def same(a, b):
        return a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b))
    for i, output in enumerate(outputs):
        if any(same(output, other) for other in outputs[:i] + inputs):
            raise ValueError('Roadmap outputs must not overwrite inputs or each other')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=ROOT/'docs/animation_roadmap.json')
    parser.add_argument('--svg',type=Path,default=ROOT/'_game/study/roadmap/animation-roadmap.svg')
    parser.add_argument('--png',type=Path,default=ROOT/'_game/study/roadmap/animation-roadmap.png')
    parser.add_argument('--assets',type=Path,default=ROOT/'_game/renders_wt')
    fontroot=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    parser.add_argument('--font',type=Path,default=Path(os.environ.get('ROADMAP_FONT',str(fontroot/'segoeui.ttf'))))
    parser.add_argument('--bold-font',type=Path,default=Path(os.environ.get('ROADMAP_BOLD_FONT',str(fontroot/'segoeuib.ttf'))))
    args=parser.parse_args()
    data=json.loads(args.data.read_text(encoding='utf-8'))
    inputs = [args.data, args.font, args.bold_font]
    if [b['id'] for b in data['blocks']]!=[f'{i:02d}' for i in range(1,13)]:
        raise ValueError('Expected twelve unique, ordered blocks')
    for block in data['blocks']:
        if block['status'] not in ('partial','active','target'):raise ValueError('Unknown status')
        for link in block['evidence']:
            path=(args.data.parent/link).resolve()
            if not path.is_relative_to(ROOT/'docs') or not path.is_file():raise ValueError('Missing evidence: '+link)
            inputs.append(path)
    covered=[key for item in data['poster']['milestones'] for key in item['blocks']]
    if sorted(covered)!=[b['id'] for b in data['blocks']]:
        raise ValueError('Poster milestones must cover each direction exactly once')
    if len(data['poster']['milestones'])!=6 or len(data['poster']['active_steps'])!=3:
        raise ValueError('Expected six milestones and three active steps')
    if len(data['previews'])!=3:
        raise ValueError('Expected three evidence images')
    for name in [data['artwork']]+[item['file'] for item in data['previews']]:
        path=(args.assets/name).resolve()
        if not path.is_relative_to(args.assets.resolve()) or not path.is_file():raise ValueError('Missing artwork: '+name)
        inputs.append(path)
    check_outputs([args.svg, args.png, args.png.with_suffix('.json')], inputs)
    p=render(data,args.font,args.bold_font,args.assets)
    args.svg.parent.mkdir(parents=True,exist_ok=True);args.png.parent.mkdir(parents=True,exist_ok=True)
    args.svg.write_text('\n'.join(p.svg)+'\n',encoding='utf-8')
    p.image.resize((W,H),Image.Resampling.LANCZOS).save(args.png)
    receipt={'data_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),'svg_sha256':hashlib.sha256(args.svg.read_bytes()).hexdigest(),'png_sha256':hashlib.sha256(args.png.read_bytes()).hexdigest(),'size':[W,H],'blocks':12,'revision':data['revision']}
    args.png.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
