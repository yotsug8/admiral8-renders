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
W, H, SCALE = 1600, 3760, 2
BG, PANEL, EDGE = '#101b25', '#192832', '#3a464b'
WHITE, MUTED, MINT, GOLD = '#f7efe2', '#a9b9bf', '#9fcdbb', '#efae69'


class Poster:
    def __init__(self, regular, bold):
        self.fonts = (regular, bold)
        self.image = Image.new('RGB', (W*SCALE, H*SCALE), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title description">',
                    '<title id="title">Дорожная карта обучения анимации</title>',
                    '<desc id="description">Двенадцать направлений. В каждом: проверенные результаты и следующий шаг. Частичная проверка не означает освоение всего направления.</desc>']
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

    def check(self, x, y):
        self.line(x,y+10,x+7,y+17,MINT,3)
        self.line(x+7,y+17,x+20,y,MINT,3)

    def picture(self, path, x, y, w, h, top=False, contain=False):
        source=Image.open(path).convert('RGB')
        if contain:
            placed=ImageOps.pad(source,(w*SCALE,h*SCALE),Image.Resampling.LANCZOS,color=PANEL)
        else:
            placed=ImageOps.fit(source,(w*SCALE,h*SCALE),Image.Resampling.LANCZOS,
                                centering=(.5,0 if top else .5))
        self.image.paste(placed,(x*SCALE,y*SCALE))
        mime='image/png' if path.suffix.lower()=='.png' else 'image/jpeg'
        encoded=base64.b64encode(path.read_bytes()).decode()
        align='xMidYMin' if top else 'xMidYMid'
        fit='meet' if contain else 'slice'
        self.svg.append(f'<image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="{align} {fit}" href="data:{mime};base64,{encoded}"/>')

    def text(self, x, y, value, size=24, color=WHITE, bold=False):
        font=ImageFont.truetype(str(self.fonts[int(bold)]),size*SCALE)
        self.draw.text((x*SCALE,y*SCALE),value,font=font,fill=color,anchor='lt')
        self.svg.append(f'<text x="{x}" y="{y}" dominant-baseline="text-before-edge" font-family="Segoe UI,DejaVu Sans,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{html.escape(value)}</text>')

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
    # Film-strip edges, not the reference game's grid or branding.
    for y in range(830,3400,56):
        p.rect(17,y,12,25,'#2a363c',3);p.rect(1571,y,12,25,'#2a363c',3)
    p.picture(assets/data['artwork'],0,0,W,795,top=True)
    p.rect(64,65,40,5,GOLD,2)
    p.text(125,54,'МАСТЕРСКАЯ АНИМАЦИИ',24,WHITE,True)
    p.text(62,164,'ОТ ПОЗЫ',92,WHITE,True)
    p.text(62,270,'ДО СЦЕНЫ',92,GOLD,True)
    p.text(66,403,'ДОРОЖНАЯ КАРТА',32,WHITE,True)
    p.text(66,465,'Движение. Характер.',27,WHITE)
    p.text(66,505,'Свет. Звук. Готовый фильм.',27,WHITE)
    p.text(66,625,'12 НАПРАВЛЕНИЙ',23,GOLD,True)
    p.text(66,665,f"{data['updated']}  /  ВЕРСИЯ {data['revision']:02d}",22,MUTED)
    p.rect(1060,744,474,37,BG,3)
    p.text(1074,752,'ОБЛОЖКА — ОТДЕЛЬНАЯ ИЛЛЮСТРАЦИЯ',17,MUTED)
    p.line(64,799,1536,799,GOLD,3)
    p.text(64,830,'УЖЕ ЕСТЬ РЕЗУЛЬТАТЫ',39,WHITE,True)
    p.text(64,886,'Настоящие кадры проверенных проб. Не готовые художественные сценки.',23,MUTED)
    for i,item in enumerate(data['previews']):
        x=64+498*i
        p.rect(x,936,476,308,PANEL,0,EDGE)
        p.picture(assets/item['file'],x+1,937,474,222,contain=True)
        p.text(x+16,1177,item['title'],25,WHITE,True)
        p.text(x+16,1214,item['note'],18,MUTED)
    p.rect(64,1290,1472,167,'#2d302c',7)
    p.rect(64,1290,8,167,GOLD)
    p.text(94,1315,'СЕЙЧАС / ГОТОВЫЙ ЖЕСТ → ИГРОВОЙ ГЕРОЙ',32,GOLD,True)
    p.text(94,1370,data['milestone'],25,WHITE)
    p.text(94,1414,data['next_action'],23,MUTED)
    chapters=['ДВИЖЕНИЕ СО СМЫСЛОМ','ТЕЛО, КОНТАКТ И ИНСТРУМЕНТЫ',
              'ХАРАКТЕР И ПОСТАНОВКА','ДОВЕСТИ ДО ВЫПУСКА']
    labels=['I','II','III','IV']
    for row,chapter in enumerate(chapters):
        y=1510+480*row
        p.text(64,y,labels[row],40,GOLD,True)
        p.text(150,y,chapter,35,WHITE,True)
        p.line(64,y+55,1536,y+55,GOLD,1)
        for col in range(3):
            block=data['blocks'][row*3+col]
            x=64+498*col;cy=y+78;w=476;h=350
            p.rect(x,cy,w,h,PANEL,5,EDGE)
            if block['status']=='active':p.rect(x,cy,w,5,GOLD)
            p.text(x+18,cy+18,block['id'],29,GOLD if block['status']=='active' else MINT,True)
            p.paragraph(x+72,cy+18,block['title'],w-92,27,WHITE,2,True)
            p.paragraph(x+18,cy+94,block['scope'],w-36,19,MUTED,2)
            p.line(x+18,cy+153,x+w-18,cy+153)
            p.check(x+18,cy+172)
            p.paragraph(x+53,cy+168,block['done'],w-73,21,WHITE,3)
            p.text(x+18,cy+261,'→',23,GOLD,True)
            p.paragraph(x+53,cy+257,block['next'],w-73,21,WHITE,3)
    p.rect(64,3450,1472,231,'#25332f',8)
    p.text(94,3475,'ФИНИШ / ГОТОВЫЙ РОЛИК, КОТОРЫЙ МОЖНО ПОВТОРИТЬ',32,WHITE,True)
    for i,step in enumerate(data['finish']):
        x=94+(i%2)*730;y=3540+(i//2)*47
        p.text(x,y,f'{i+1:02d}',23,GOLD,True);p.text(x+48,y,step,24,WHITE)
    p.text(94,3640,'Проверенный результат → повтор на новой задаче → устойчивая практика.',21,MUTED)
    p.text(64,3710,'Карта обновляется по результатам. Пробы не закрывают навык целиком; направления идут параллельно.',20,MUTED)
    p.svg.append('</svg>')
    return p


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
    if [b['id'] for b in data['blocks']]!=[f'{i:02d}' for i in range(1,13)]:
        raise ValueError('Expected twelve unique, ordered blocks')
    for block in data['blocks']:
        if block['status'] not in ('partial','active','target'):raise ValueError('Unknown status')
        for link in block['evidence']:
            path=(args.data.parent/link).resolve()
            if not path.is_relative_to(ROOT/'docs') or not path.is_file():raise ValueError('Missing evidence: '+link)
    for name in [data['artwork']]+[item['file'] for item in data['previews']]:
        path=(args.assets/name).resolve()
        if not path.is_relative_to(args.assets.resolve()) or not path.is_file():raise ValueError('Missing artwork: '+name)
    p=render(data,args.font,args.bold_font,args.assets)
    args.svg.parent.mkdir(parents=True,exist_ok=True);args.png.parent.mkdir(parents=True,exist_ok=True)
    args.svg.write_text('\n'.join(p.svg)+'\n',encoding='utf-8')
    p.image.resize((W,H),Image.Resampling.LANCZOS).save(args.png)
    receipt={'data_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),'svg_sha256':hashlib.sha256(args.svg.read_bytes()).hexdigest(),'png_sha256':hashlib.sha256(args.png.read_bytes()).hexdigest(),'size':[W,H],'blocks':12,'revision':data['revision']}
    args.png.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
