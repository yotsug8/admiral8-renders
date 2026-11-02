"""CPU diagnostic projections of saved joint coordinates; no motion corrections."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def forward_axis(pose):
    direction = np.mean([np.array(pose[s+'ToeBase'][1], dtype=float) - pose[s+'Foot'][0]
                         for s in ('Left', 'Right')], axis=0)
    direction[2] = 0
    length = np.linalg.norm(direction)
    require(math.isfinite(length) and length > 1e-9, 'Initial foot heading is undefined')
    return direction / length


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('--poses', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--font', required=True, type=Path)
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    require(sha(args.poses) == recipe['poses_sha256'], 'Input coordinates changed')
    poses = json.loads(args.poses.read_text(encoding='utf-8'))
    require(len(poses) == recipe['source_samples'] == 180, 'Expected 180 source samples')
    names = list(poses[0])
    require(len(names) == 31 and all(list(p) == names for p in poses), 'Bone lists differ')
    require(all(np.asarray(ends).shape == (2, 3) and np.isfinite(np.asarray(ends, dtype=float)).all()
                for p in poses for ends in p.values()), 'Expected finite pairs of 3D endpoints')
    source_fps, fps = recipe['source_fps'], recipe['fps']
    require(source_fps == 60 and fps == 30, 'Expected 60 Hz source and 30 fps preview')
    frame_count = int(recipe['duration_seconds'] * fps)
    indices = list(range(0, len(poses), source_fps // fps))
    require(len(indices) == frame_count == 90, 'Expected 90 output frames')
    require(len(poses) / source_fps == frame_count / fps == 3, 'Expected three seconds')
    p0 = poses[0]
    forward = forward_axis(p0)
    args.out.mkdir(parents=True, exist_ok=False)
    frames = args.out / 'frames'
    frames.mkdir()
    screen_right = np.cross([0, 0, 1], forward)
    center = np.array(p0['Hips'][0])
    center[2] = 0
    roots = np.array([p['Hips'][0] for p in poses])
    delta = roots[-1] - roots[0]
    feet = {}
    for side in ('Left', 'Right'):
        points = np.array([[p[side+n][e] for n in ('Foot', 'ToeBase')
                            for e in (0, 1)] for p in poses])
        j, point = np.unravel_index(np.argmin(points[:, :, 2]), (180, 4))
        feet[side] = dict(min_z_m=float(points[j, point, 2]),
                          amc_sample=721+int(j), time_s=float(j/60),
                          bone=('Foot', 'ToeBase')[point//2],
                          endpoint=('head', 'tail')[point%2],
                          max_z_of_lowest_endpoint_m=float(points[:, :, 2].min(axis=1).max()))
    width, height = recipe['size']
    scale, ground_y = recipe['pixels_per_meter'], recipe['ground_pixel_y']
    fonts = {s: ImageFont.truetype(str(args.font), s) for s in (16, 18, 20, 25)}
    colors = {'Left': '#2777b6', 'Right': '#cf7125', 'Torso': '#273444'}
    projected_inside = True
    for out_frame, source_index in enumerate(indices):
        pose = poses[source_index]
        im = Image.new('RGB', (width, height), '#f4f6f8')
        draw = ImageDraw.Draw(im)
        draw.text((24, 12), 'ДИАГНОСТИЧЕСКИЙ СКЕЛЕТ — CMU 77_01', font=fonts[25], fill='#172331')
        draw.text((24, 46), 'Исходные суставы • не анимация героя • без коррекции движения', font=fonts[18], fill='#455568')
        draw.text((width-320, 18), f'{out_frame/fps:4.2f} / 3.00 с    AMC {721+source_index}', font=fonts[20], fill='#172331')
        for view, horizontal in enumerate((screen_right, forward)):
            left = view * width // 2
            cx = left + width // 4
            def project(point):
                q = np.array(point) - center
                return (cx + float(np.dot(q, horizontal))*scale,
                        ground_y - point[2]*scale)
            draw.rectangle((left+12, ground_y, left+width//2-12, 604), fill='#e1e5e9')
            draw.line((left+12, ground_y, left+width//2-12, ground_y), fill='#7d8996', width=2)
            for m in (-0.5, 0, 0.5):
                x = cx + m*scale
                draw.line((x, ground_y, x, ground_y+7), fill='#7d8996', width=1)
                draw.text((x-20, ground_y+10), f'{m:+.1f} м', font=fonts[16], fill='#5b6977')
            draw.text((left+25, 82), 'СПЕРЕДИ' if view == 0 else 'СБОКУ', font=fonts[20], fill='#172331')
            draw.text((left+25, 111), 'F — к зрителю' if view == 0 else 'F — вправо', font=fonts[18], fill='#5b6977')
            # Fixed reference-axis arrow; not a reconstructed head/gaze direction.
            if view == 0:
                draw.ellipse((left+30, 149, left+52, 171), outline='#677889', width=2)
                draw.ellipse((left+39, 158, left+43, 162), fill='#677889')
            else:
                draw.line((left+30, 160, left+87, 160), fill='#677889', width=2)
                draw.polygon([(left+87,160),(left+77,155),(left+77,165)], fill='#677889')
            draw.text((left+25, 535), 'Z=0 • исходный пол', font=fonts[16], fill='#5b6977')
            # Draw original bone segments only; no synthetic rig or smoothing.
            for name, ends in pose.items():
                a, b = map(project, ends)
                projected_inside &= all(left+15 < p[0] < left+width//2-15 and 75 < p[1] < ground_y+3 for p in (a,b))
                side = 'Left' if name.startswith(('Left', 'LHip', 'LThumb')) else 'Right' if name.startswith(('Right', 'RHip', 'RThumb')) else 'Torso'
                color = colors[side]
                draw.line((a,b), fill=color, width=4)
                draw.ellipse((a[0]-2,a[1]-2,a[0]+2,a[1]+2), fill=color)
            root = project(pose['Hips'][0])
            initial = project(p0['Hips'][0])
            draw.ellipse((initial[0]-6,initial[1]-6,initial[0]+6,initial[1]+6), outline='#a64186', width=1)
            draw.ellipse((root[0]-4,root[1]-4,root[0]+4,root[1]+4), fill='#a64186')
        require(projected_inside, 'Skeleton clipped by fixed view')
        lmin = min(pose[n][e][2] for n in ('LeftFoot','LeftToeBase') for e in (0,1))
        rmin = min(pose[n][e][2] for n in ('RightFoot','RightToeBase') for e in (0,1))
        draw.text((24, 617), f'Низ костей стоп: L {1000*lmin:.1f} мм • R {1000*rmin:.1f} мм над Z=0; подошвы отсутствуют', font=fonts[18], fill='#283c4f')
        draw.text((24, 646), f'F=({forward[0]:+.3f}, {forward[1]:+.3f}, 0), по стопам в t=0; Z вверх; масштаб {scale} пикс/м', font=fonts[18], fill='#455568')
        draw.text((24, 677), 'L — синий   R — оранжевый   корень — пурпурный; кольцо — его начальное положение', font=fonts[16], fill='#455568')
        im.save(frames/f'f{out_frame:04d}.png')
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    movie = args.out/'ready_motion_diagnostic.mp4'
    command = [ffmpeg, '-v','error','-framerate',str(fps),'-i',str(frames/'f%04d.png'),
               '-frames:v',str(frame_count),'-an','-c:v','libx264','-crf','18',
               '-preset','medium','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)]
    subprocess.run(command, check=True)
    reader = imageio_ffmpeg.read_frames(str(movie), pix_fmt='rgb24')
    metadata = next(reader)
    decoded = [np.frombuffer(raw,np.uint8).reshape((height,width,3)).copy() for raw in reader]
    require(len(decoded) == frame_count and metadata['fps'] == fps, 'Decoded cadence/count mismatch')
    require(abs(metadata['duration']-3) < 1/fps, 'Decoded duration mismatch')
    errors = [float(np.abs(frame.astype(np.int16)-np.array(Image.open(frames/f'f{i:04d}.png')).astype(np.int16)).mean()) for i,frame in enumerate(decoded)]
    require(max(errors) < 3, 'Unexpected encoded/source frame difference')
    body_diffs = [float(np.abs(a[180:565].astype(np.int16)-b[180:565].astype(np.int16)).mean()) for a,b in zip(decoded,decoded[1:])]
    require(min(body_diffs) > 0, 'Repeated body image')
    review = args.out/'review'
    review.mkdir()
    for start in range(0,frame_count,15):
        sheet = Image.new('RGB',(1800,1925),'#ffffff')
        sd = ImageDraw.Draw(sheet)
        for j,frame in enumerate(decoded[start:start+15]):
            x,y=(j%3)*600,(j//3)*385
            sheet.paste(Image.fromarray(frame).resize((600,360)),(x,y+25))
            sd.text((x+5,y+3),f'frame {start+j:02d} / {(start+j)/fps:.3f} s',font=fonts[18],fill='black')
        sheet.save(review/f'decoded_{start:02d}-{min(start+14,89):02d}.jpg',quality=94)
    metrics = dict(source_sha256=sha(args.poses),recipe_sha256=sha(args.recipe),
                   source_samples=180,measurement_fps=60,output_frames=90,output_fps=30,
                   duration_seconds=3,output_source_indices=indices,
                   sampling='Exact source samples 0,2,...,178. Each frame covers 1/30 s; whole [0,3) interval. Source sample 179 is included in measurements, not a distinct 30 fps picture.',
                   forward_fixed=forward.tolist(),front_screen_right=screen_right.tolist(),
                   view_center_ground=center.tolist(),pixels_per_meter=scale,ground_z_m=0,
                   feet=feet,root_start_m=roots[0].tolist(),root_end_m=roots[-1].tolist(),
                   root_displacement_m=delta.tolist(),root_net_distance_m=float(np.linalg.norm(delta)),
                   root_horizontal_displacement_m=float(np.linalg.norm(delta[:2])),
                   root_path_length_m=float(np.linalg.norm(np.diff(roots,axis=0),axis=1).sum()),
                   root_axis_ranges_m=np.ptp(roots,axis=0).tolist(),
                   decoded_metadata=metadata,decoded_source_mean_abs_error_max=max(errors),
                   minimum_adjacent_body_image_difference=min(body_diffs),all_projected_points_inside=bool(projected_inside),
                   ffmpeg_version=imageio_ffmpeg.get_ffmpeg_version(),python_version=sys.version.split()[0],
                   numpy_version=np.__version__,movie_sha256=sha(movie),
                   limitations='Joint endpoints, not soles/contact surfaces. No motion edit, interpolation, retarget, mesh, new rig or Blender render. Fixed front from initial foot direction; not a gaze axis.')
    (args.out/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(json.dumps({k:metrics[k] for k in ('feet','root_displacement_m','root_horizontal_displacement_m','root_path_length_m','movie_sha256','decoded_source_mean_abs_error_max')},indent=2))


if __name__ == '__main__':
    main()
