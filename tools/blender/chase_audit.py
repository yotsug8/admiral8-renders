"""Diagnostic check for local forelimb/spine rotation spikes.

Run in Blender on the assembled chase. Does not render or save the scene.
This is a finite temporal sample, not a visual or collision quality verdict.
Local rotation failure alone does not prove a visible defect: parent motion
can compensate it. World metrics describe the same bone and sample interval.
"""
import json
import math
from pathlib import Path
import bpy


def audit():
    scene=bpy.context.scene
    arm=next(o for o in scene.objects if o.type=='ARMATURE' and
             o.parent and o.parent.name=='hoodwink_root')
    names=[b.name for b in arm.pose.bones if b.name.lower().startswith(
        ('arm_upper_', 'arm_lower_', 'hand_', 'spine_'))]
    spec=json.loads((Path(__file__).resolve().parents[2]/'skits/kunkka_chase.json').read_text(encoding='utf-8'))
    fps=scene.render.fps/scene.render.fps_base
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('Invalid effective FPS')
    cuts={round(s['start']*fps) for s in spec['shots'][1:]}
    previous={};worst=dict(angle_deg=0.,world_angle_deg=0.,head_speed_m_s=0.);samples=0
    for tick in range(round(2.2*fps*4),round(8*fps*4)):
        frame=tick/4;scene.frame_set(math.floor(frame),subframe=frame%1)
        ev=arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for name in names:
            bone=ev.pose.bones[name]
            q=bone.matrix_basis.to_quaternion()
            world_q=(ev.matrix_world@bone.matrix).to_quaternion()
            head=ev.matrix_world@bone.head
            if name in previous and frame not in cuts:
                prev_q,prev_world_q,prev_head,prev_frame=previous[name]
                angle=math.degrees(prev_q.rotation_difference(q).angle)
                angle=min(angle,360-angle)
                if angle>worst['angle_deg']:
                    world_angle=math.degrees(prev_world_q.rotation_difference(world_q).angle)
                    speed=(head-prev_head).length*scene.unit_settings.scale_length/((frame-prev_frame)/fps)
                    worst=dict(angle_deg=angle,bone=name,frame=frame,
                               world_angle_deg=min(world_angle,360-world_angle),head_speed_m_s=speed)
            previous[name]=(q.copy(),world_q.copy(),head.copy(),frame)
        samples+=1
    report=dict(samples=samples,fps=fps,maximum_forelimb_spine_rotation_per_quarter_frame=worst,
                excluded_camera_cuts=sorted(cuts),passed=worst['angle_deg']<=8,
                limitation='The legacy local-angle fail does not prove a visible defect; parent motion can compensate it. '
                'World angle (degrees per quarter frame) and world head speed (m/s, scene scale_length and fps/fps_base) '
                'refer to the same bone and interval as the local maximum, not independent world maxima. '
                'Does not test clothing, ground, grip, audio or perceptual pacing.')
    print('CHASE_REGRESSION',json.dumps(report),flush=True)
    if not report['passed']:raise ValueError('Local forelimb/spine rotation spike; not proof of a visible defect')


if __name__=='__main__':audit()
