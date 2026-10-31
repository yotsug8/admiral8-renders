"""CPU guard against accidentally rendering the unchanged baseline twice.

Matching filenames and sizes are required. Pixel differences prove neither
pose differences nor quality: camera, lighting, noise and compression can also
change pixels. Use this only for explicitly paired controlled probes.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def compare(before, after, pattern='f*.png', maximum=600):
    left={p.name:p for p in before.glob(pattern) if p.is_file()}
    right={p.name:p for p in after.glob(pattern) if p.is_file()}
    if not left or left.keys()!=right.keys():
        raise ValueError('Empty or mismatched frame sets; incomplete renders are not comparable')
    if not 1<=len(left)<=maximum:
        raise ValueError('Frame budget exceeded')
    rows=[]
    for name in sorted(left):
        with Image.open(left[name]) as im:a=np.asarray(im.convert('RGBA'),dtype=np.int16)
        with Image.open(right[name]) as im:b=np.asarray(im.convert('RGBA'),dtype=np.int16)
        if a.shape!=b.shape:raise ValueError('Image size mismatch: '+name)
        diff=np.abs(a-b)
        rows.append(dict(frame=name,identical=not bool(diff.any()),
                         changed_pixel_fraction=float(np.any(diff!=0,axis=2).mean()),
                         mean_channel_difference=float(diff.mean())))
    identical=sum(r['identical'] for r in rows)
    return dict(frames=len(rows),identical=identical,changed=len(rows)-identical,
                all_identical=identical==len(rows),samples=rows,
                limits='Pixel changes do not prove pose changes or animation quality. '
                       'Control camera, lighting and sampling independently.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--after',type=Path,required=True)
    parser.add_argument('--json',type=Path,required=True)
    parser.add_argument('--expect-change',action='store_true')
    args=parser.parse_args()
    try:
        report=compare(args.before,args.after)
        code=int(args.expect_change and report['all_identical'])
        report['status']='unchanged_when_change_expected' if code else 'compared'
    except (ValueError,OSError) as exc:
        report,code=dict(status='error',error=str(exc)),2
    args.json.parent.mkdir(parents=True,exist_ok=True)
    args.json.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('samples','limits')}))
    return code


if __name__=='__main__':
    raise SystemExit(main())
