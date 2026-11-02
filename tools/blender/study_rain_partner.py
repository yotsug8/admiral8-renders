"""Two independent Rain actors: an offered high-five becomes a quieter greeting.

A specific silent acting study, not a general gesture library. See RAIN_PARTNER.md.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '_game/external/rain_v33/Rain v3.3/rain_v3.2.blend'
FPS, COUNT = 30, 180


def ease(t, start, duration):
    x = min(1., max(0., (t-start)/duration))
    # Floating-point cancellation near x=1 can exceed 1 by a few ulps.
    # Slerp rejects even a tiny negative factor in the subsequent release.
    return min(1., max(0., x*x*x*(10+x*(-15+6*x))))


def update():
    bpy.context.view_layer.update()


class Performer:
    def __init__(self, rig, x, yaw):
        self.rig = rig
        self.p = rig.pose.bones
        for key, value in {'ik_arm_left':1, 'ik_arm_right':1, 'ik_leg_left':1,
                           'ik_leg_right':1, 'ik_spine':0, 'ik_fingers_left':0,
                           'ik_fingers_right':0, 'ik_stretch_arms':0, 'ik_stretch_legs':0}.items():
            self.p['Properties_IKFK'][key] = value
        rig.update_tag()
        rig.location.x = x
        rig.rotation_euler.z = math.radians(yaw)
        update()
        self.names = ['MSTR-Pelvis','MSTR-Foot.L','MSTR-Foot.R','FK-Spine','FK-Chest','FK-Head',
                      'FK-Scarf1','MSTR-Jaw','MSTR-Eyebrow.L','MSTR-Eyebrow.R']
        for side in ('L','R'):
            self.names += ['IK-Hand.'+side,'IK-Pole-Forearm.'+side,'TGT-Eye.'+side]
        self.names += [f'FK-Hair_Ponytail{i}' for i in range(1,5)]
        self.basis = {n:self.p[n].matrix_basis.copy() for n in self.names}
        self.rest = {b.name:b.matrix.copy() for b in self.p}
        self.hands = {s:self.hand_q(s,(0,0,-1),(-1 if s=='L' else 1,0,0)) for s in ('L','R')}
        self.tracked = ['FK-Head','FK-Hand.L','FK-Hand.R','FK-Forearm.L','FK-Forearm.R','MSTR-Pelvis','MSTR-Foot.L','MSTR-Foot.R']

    def hand_q(self, side, direction, normal):
        wrist = self.rest['FK-Hand.'+side].translation
        finger = (self.rest['FK-Middle3.'+side].translation-wrist).normalized()
        old = (self.rest['FK-Index1.'+side].translation-wrist).cross(self.rest['FK-Pinky1.'+side].translation-wrist).normalized()
        if old.z < 0: old = -old
        direction = Vector(direction).normalized()
        normal = Vector(normal); normal = (normal-direction*normal.dot(direction)).normalized()
        q = finger.rotation_difference(direction); current = q@old
        angle = math.atan2(direction.dot(current.cross(normal)), current.dot(normal))
        return Quaternion(direction,angle)@q@self.rest['FK-Hand.'+side].to_quaternion()

    def move(self, name, delta=None, target=None):
        matrix = self.p[name].matrix.copy()
        matrix.translation = Vector(target) if target is not None else matrix.translation+Vector(delta)
        self.p[name].matrix = matrix
        update()

    def rotate(self, name, axis, degrees):
        matrix = self.p[name].matrix.copy(); pivot = matrix.translation
        self.p[name].matrix = Matrix.Translation(pivot)@Quaternion(Vector(axis), math.radians(degrees)).to_matrix().to_4x4()@Matrix.Translation(-pivot)@matrix
        update()

    def pose(self, t, initiator, partner):
        for n,m in self.basis.items(): self.p[n].matrix_basis = m
        update()
        # Different temporal structure: proposal, observation, answer, understanding.
        invite = ease(t,.25,.85)*(1-ease(t,4.20,.95)) if initiator else 0.
        notice = ease(t,1.35,.65) if not initiator else ease(t,.10,.50)
        answer = ease(t,2.65,.65)*(1-ease(t,4.45,.65)) if not initiator else 0.
        understand = ease(t,4.00,.65) if initiator else ease(t,3.80,.70)
        nod = math.sin(math.pi*ease(t,4.55,.75)) if initiator else math.sin(math.pi*ease(t,3.40,.65))
        lean = 7*invite if initiator else -3*notice+2*answer
        shift = .025*invite if initiator else -.018*notice
        self.move('MSTR-Pelvis',delta=(shift,-.025*invite,-.018-.02*invite))
        self.move('MSTR-Foot.L',delta=(.025,0,0))
        self.move('MSTR-Foot.R',delta=(-.025,0,0))
        self.rotate('FK-Spine',(1,0,0),lean*.4)
        self.rotate('FK-Chest',(1,0,0),lean*.6)
        self.rotate('FK-Chest',(0,0,1),(6 if initiator else -4)*notice)
        self.rotate('FK-Scarf1',(1,0,0),-max(0,lean)*.6)
        self.rotate('FK-Head',(1,0,0),6+8*nod+3*understand)
        self.rotate('FK-Head',(0,0,1),(16 if initiator else -20)*notice)
        self.move('MSTR-Eyebrow.L',delta=(0,0,.008*invite+.006*answer+.003*understand))
        self.move('MSTR-Eyebrow.R',delta=(0,0,.005*invite+.003*answer))
        self.rotate('MSTR-Jaw',(1,0,0),2.5*invite)
        head_delta = self.p['FK-Head'].matrix.to_quaternion()@self.rest['FK-Head'].to_quaternion().inverted()
        for i,droop in enumerate((10,25,20,10),1):
            lag = 3*math.sin(math.pi*ease(t,.35+.045*i,.85)) if initiator else 2*math.sin(math.pi*ease(t,1.45+.045*i,.65))
            self.rotate(f'FK-Hair_Ponytail{i}',head_delta@Vector((1,0,0)),-droop+lag)
        active_side = 'L' if initiator else 'R'
        amount = invite if initiator else answer
        for side,sign in (('L',1),('R',-1)):
            neutral = Vector((sign*.23,-.10,.86))
            hand = neutral.copy(); q = self.hands[side]
            if side==active_side:
                raised = Vector((sign*.28,-.23,1.41 if initiator else 1.22))
                hand = neutral.lerp(raised,amount)
                hand += Vector((sign*.10,-.07,0))*math.sin(math.pi*amount)
                wave = 12*math.sin(2*math.pi*ease(t,3.15,.70)) if not initiator else 0.
                # Choose the raise path once. Re-solving a moving endpoint near
                # a half-turn can flip the shortest slerp arc between frames.
                target_q = self.hand_q(side,(0,0,1),(0,1,0))
                q = q.slerp(target_q,amount)
                q = Quaternion(Vector((0,1,0)),math.radians(wave)*amount)@q
            self.p['IK-Hand.'+side].matrix = Matrix.LocRotScale(hand,q,Vector((1,1,1)))
            update()
            self.move('IK-Pole-Forearm.'+side,target=(sign*.60,-.04,1.0))
        face = partner.rig.matrix_world@Vector((0,-.05,1.38))
        # Listener looks first at the offered hand, then at the partner's face.
        if not initiator:
            offer = partner.rig.matrix_world@Vector((.28,-.23,1.41))
            face = offer.lerp(face,ease(t,2.05,.45))
        local_target = self.rig.matrix_world.inverted()@face
        gaze = Vector((0,-2,1.40)).lerp(local_target,notice)
        for side in ('L','R'): self.move('TGT-Eye.'+side,target=gaze)

    def snapshot(self):
        return {n:self.p[n].matrix.copy() for n in self.tracked}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--check-only',action='store_true',help='Evaluate controls without rendering; --render checks the whole clip')
    parser.add_argument('--frames',default='0,36,65,100,145,179')
    parser.add_argument('--view',choices=('front','reverse'),default='front')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out=Path(args.out).resolve()
    if not out.is_relative_to(ROOT/'_game/study'): raise ValueError('Output outside study folder')
    out.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(out).free<256*1024**2: raise RuntimeError('Less than 256 MiB free')
    frames=list(range(COUNT)) if args.render else [int(x) for x in args.frames.split(',')]
    if not frames or any(f<0 or f>=COUNT for f in frames): raise ValueError('Frames outside scene')
    check_frames = list(range(COUNT)) if args.render else sorted({f for k in frames for f in (max(0,k-1),k,min(COUNT-1,k+1))})
    source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
    if bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    scene=bpy.context.scene; first=bpy.data.objects['RIG-rain']
    originals=[first]+list(first.children_recursive)
    bpy.ops.object.select_all(action='DESELECT')
    for ob in originals: ob.hide_set(False); ob.hide_select=False; ob.select_set(True)
    bpy.context.view_layer.objects.active=first
    bpy.ops.object.duplicate(linked=False)
    copies=list(bpy.context.selected_objects)
    second=next(ob for ob in copies if ob.type=='ARMATURE')
    for ob in copies:
        for modifier in ob.modifiers:
            if modifier.type=='ARMATURE' and modifier.object!=second:
                raise RuntimeError('Duplicate still bound to first rig')
    a=Performer(first,-.62,50); b=Performer(second,.62,-50)
    # Readable actor identity without changing skin or face materials.
    top=next(ob for ob in copies if ob.name.startswith('GEO-rain-top'))
    mat=bpy.data.materials.new('Listener teal shirt');mat.diffuse_color=(.06,.23,.22,1);mat.use_nodes=True
    shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Base Color'].default_value=mat.diffuse_color;shader.inputs['Roughness'].default_value=.6
    top.data.materials.clear();top.data.materials.append(mat)
    def aim(ob,target): ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
    for ob in list(scene.objects):
        if ob.type in ('LIGHT','CAMERA'): bpy.data.objects.remove(ob,do_unlink=True)
    bpy.ops.object.camera_add(location=(0,-6,2.3) if args.view=='front' else (0,6,2.3))
    scene.camera=bpy.context.object;scene.camera.data.type='ORTHO';scene.camera.data.ortho_scale=2.8;aim(scene.camera,(0,0,.88))
    for location,power,size in [((-3,-4,5),650,4),((3,-2,3),350,3),((0,3,4),600,3)]:
        bpy.ops.object.light_add(type='AREA',location=location);light=bpy.context.object;light.data.energy=power;light.data.shape='DISK';light.data.size=size;aim(light,(0,0,1))
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,.00115))
    floor=bpy.data.materials.new('Neutral floor');floor.diffuse_color=(.09,.115,.13,1);floor.use_nodes=True;floor.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=floor.diffuse_color
    bpy.context.object.data.materials.append(floor)
    scene.world=bpy.data.worlds.new('Partner world');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.18,.22,.28,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.35
    scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=640;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.fps=FPS;scene.view_settings.view_transform='AgX'
    scene.render.threads_mode='FIXED';scene.render.threads=4
    report={'source_sha256':source_hash,'credit':'Rain Rig (CC) Blender Foundation | studio.blender.org | CC BY 4.0',
            'frames':COUNT,'fps':FPS,'max_wrist_error_m':0.,'max_ankle_error_m':0.,'max_sole_error_m':0.,
            'max_step_m':0.,'max_angle_deg':0.,'source_unchanged':False,
            'known_invalid_driver':'Source Spine3 driver references absent STR-Spine4; not repaired',
            'scope':'Controller continuity and native IK, not a full mesh-collision or artistic certificate','rendered':[]}
    mesh_flags={ob:ob.hide_viewport for ob in scene.objects if ob.type=='MESH'}
    for ob in mesh_flags:ob.hide_viewport=True
    update();cache={};checks={};previous=None;previous_frame=None
    report['checked_frames']=len(check_frames)
    for f in check_frames:
        a.pose(f/FPS,True,b);b.pose(f/FPS,False,a)
        current=[actor.snapshot() for actor in (a,b)]
        for actor in (a,b):
            for side in ('L','R'):
                error=(actor.p['FK-Hand.'+side].matrix.translation-actor.p['IK-Hand.'+side].matrix.translation).length
                report['max_wrist_error_m']=max(report['max_wrist_error_m'],error)
                if error>.002: raise RuntimeError(f'Unreachable hand at {f}: {error}')
                ankle=(actor.p['IK-Shin.'+side].tail-actor.p['IK-Foot.'+side].matrix.translation).length
                report['max_ankle_error_m']=max(report['max_ankle_error_m'],ankle)
                if ankle>.002:raise RuntimeError(f'Unreachable foot at {f}: {ankle}')
        if previous and f==previous_frame+1:
            for old,new in zip(previous,current):
                for n in old:
                    distance=(old[n].translation-new[n].translation).length
                    angle=math.degrees(old[n].to_quaternion().rotation_difference(new[n].to_quaternion()).angle);angle=min(angle,360-angle)
                    report['max_step_m']=max(report['max_step_m'],distance);report['max_angle_deg']=max(report['max_angle_deg'],angle)
                    if distance>.06 or angle>20: raise RuntimeError(f'Discontinuity at {f}, {n}: {distance}, {angle}')
        cache[f]=[{n:actor.p[n].matrix_basis.copy() for n in actor.names} for actor in (a,b)];checks[f]=current;previous=current;previous_frame=f
        if f%30==0: print('PREFLIGHT',f,flush=True)
    for ob,flag in mesh_flags.items():ob.hide_viewport=flag
    update()
    (out/'preflight.json').write_text(json.dumps(report,indent=2))
    for f in ([] if args.check_only else frames):
        for actor,basis in zip((a,b),cache[f]):
            for n,m in basis.items():actor.p[n].matrix_basis=m
        update()
        for actor,expected in zip((a,b),checks[f]):
            for n,m in expected.items():
                error=max(abs(actor.p[n].matrix[i][j]-m[i][j]) for i in range(4) for j in range(4))
                if error>1e-5:raise RuntimeError(f'Cache differs at {f}: {n}')
        dg=bpy.context.evaluated_depsgraph_get()
        for objects in (originals,copies):
            shoe=next(ob for ob in objects if ob.name.startswith('GEO-rain-shoes'))
            ev=shoe.evaluated_get(dg);mesh=ev.to_mesh()
            for side in ('L','R'):
                groups={g.index for g in shoe.vertex_groups if g.name.endswith('.'+side)}
                sole=min((ev.matrix_world@v.co).z for v in mesh.vertices if any(g.group in groups and g.weight>.5 for g in v.groups))
                error=abs(sole-.00115);report['max_sole_error_m']=max(report['max_sole_error_m'],error)
                if error>.002:raise RuntimeError(f'Sole support at {f}: {side}, {error}')
            ev.to_mesh_clear()
        scene.render.filepath=str(out/f'{f:04d}.png');bpy.ops.render.render(write_still=True);report['rendered'].append(f)
    report['source_unchanged']=hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PARTNER_DONE',len(frames),flush=True)


if __name__=='__main__': main()
