"""Two independent Rain actors: greeting or a light baton handoff.

Specific silent studies, not a gesture library. See RAIN_PARTNER/RAIN_HANDOFF.md.
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
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '_game/external/rain_v33/Rain v3.3/rain_v3.2.blend'
FPS, COUNT = 30, 180
APPROACH_FRAMES = 42
APPROACH_DISTANCE = .34
APPROACH_STEPS = {'R': (.12, .51), 'L': (.65, .54)}
# Authored for this 36 mm shaft on Rain, verified against evaluated skin.
# Per-finger lengths differ; one identical curl penetrates with the pinky.
BATON_GRIP = {f:tuple(a*s for a in (35,60,40)) for f,s in
              (('index',1.12),('middle',1.18),('ring',1.1125),('pinky',1.03))}
BATON_GRIP['thumb']=(-30.,47.5,-15.)


def ease(t, start, duration):
    x = min(1., max(0., (t-start)/duration))
    # Floating-point cancellation near x=1 can exceed 1 by a few ulps.
    # Slerp rejects even a tiny negative factor in the subsequent release.
    return min(1., max(0., x*x*x*(10+x*(-15+6*x))))


def update():
    bpy.context.view_layer.update()


def baton_center(t):
    offer = ease(t,.35,1.05)
    take = ease(t,3.90,1.0)
    return Vector((-.20+.20*offer+.20*take, -.23, 1.05+.10*ease(t,4.45,.65)))


def approach_foot(elapsed, side):
    start, duration = APPROACH_STEPS[side]
    phase = min(1., max(0., (elapsed-start)/duration))
    return Vector((APPROACH_DISTANCE*(1-ease(elapsed,start,duration)),
                   0, .095*math.sin(math.pi*phase)**2))


def approach_root(elapsed):
    return APPROACH_DISTANCE*(1-ease(elapsed,.13,1.10))


def skin_regions(ob, dg):
    """Disjoint weighted regions; upper arms/shoulder seams are not certified."""
    ev=ob.evaluated_get(dg);mesh=ev.to_mesh();mesh.calc_loop_triangles()
    points=[ev.matrix_world@v.co for v in mesh.vertices]
    triangles=[tuple(t.vertices) for t in mesh.loop_triangles]
    def tree(predicate=None):
        if predicate is None:faces=triangles
        else:
            groups={g.index for g in ob.vertex_groups if predicate(g.name)}
            vertices={v.index for v in mesh.vertices if sum(g.weight for g in v.groups if g.group in groups)>.7}
            faces=[t for t in triangles if all(i in vertices for i in t)]
        return BVHTree.FromPolygons(points,faces,all_triangles=True) if faces else None
    result={'full':tree(), 'torso':tree(lambda n:any(k in n for k in ('Spine','Chest','Pelvis')))}
    for side in ('L','R'):
        result[side]=tree(lambda n:n.endswith('.'+side) and any(k in n for k in ('Forearm','Hand','Index','Middle','Ring','Pinky','Thumb')))
    ev.to_mesh_clear()
    return result


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
        return {n:self.rig.matrix_world@self.p[n].matrix for n in self.tracked}

    def handoff_pose(self, t, giver, partner, grip_module, approach=None):
        for n,m in self.basis.items(): self.p[n].matrix_basis = m
        update()
        offer = ease(t,.35,1.05)
        arrival = ease(t,1.45,.80)
        take = ease(t,3.90,1.0)
        withdraw = ease(t,3.65,.85)
        lean = 6*offer*(1-withdraw) if giver else 8*arrival*(1-take)
        step_weight = 0. if approach is None else ease(approach,.05,.22)*(1-ease(approach,1.08,.32))
        self.move('MSTR-Pelvis',delta=(.015*offer if giver else -.015*arrival,-.025*lean/8,-.018-.012*lean/8-.036*step_weight))
        for side, offset in (('L',.025),('R',-.025)):
            delta = Vector((offset,0,0))
            if approach is not None:
                travel = approach_foot(approach, side)
                travel.x -= approach_root(approach)
                delta += self.rig.matrix_world.to_3x3().inverted()@travel
            self.move('MSTR-Foot.'+side,delta=delta)
        self.rotate('FK-Spine',(1,0,0),lean*.4);self.rotate('FK-Chest',(1,0,0),lean*.6)
        if step_weight:
            side_axis = self.rig.matrix_world.to_quaternion().inverted()@Vector((0,1,0))
            self.rotate('FK-Spine',side_axis,-5*step_weight)
        self.rotate('FK-Scarf1',(1,0,0),-max(0,lean)*.6)
        nod = math.sin(math.pi*ease(t,4.9,.7)) if giver else math.sin(math.pi*ease(t,5.15,.65))
        self.rotate('FK-Head',(1,0,0),12+5*nod)
        self.rotate('FK-Head',(0,0,1),(15 if giver else -15)*ease(t,.20,.65))
        self.move('MSTR-Eyebrow.L',delta=(0,0,.003*offer));self.move('MSTR-Eyebrow.R',delta=(0,0,.002*offer))
        head_delta=self.p['FK-Head'].matrix.to_quaternion()@self.rest['FK-Head'].to_quaternion().inverted()
        for i,droop in enumerate((10,25,20,10),1):self.rotate(f'FK-Hair_Ponytail{i}',head_delta@Vector((1,0,0)),-droop)
        active_side='R' if giver else 'L'
        sign=-1 if giver else 1
        inverse=self.rig.matrix_world.inverted()
        orient_inverse=self.rig.matrix_world.to_quaternion().inverted()
        progress=min(1.,max(0.,(t-(3.05 if giver else 2.25))/.55))
        grip=1-progress if giver else progress
        fitted=grip*grip*(3-2*grip)
        for side,s in (('L',1),('R',-1)):
            neutral=Vector((s*.23,-.10,.86));hand=neutral.copy();q=self.hands[side]
            if side==active_side:
                contact_world=baton_center(t)+Vector((sign*.046,.049,.08 if giver else -.04))
                contact=inverse@contact_world
                # Rain's positive-rest-Z hand normal is dorsal; curl faces
                # the opposite direction, toward the shaft.
                hold_q=self.hand_q(side,orient_inverse@Vector((0,-1,0)),orient_inverse@Vector((sign,0,0)))
                if giver:
                    hand=contact.lerp(neutral,withdraw)
                    # Release outward before going down, away from the shaft.
                    hand+=orient_inverse@Vector((-.09,0,0))*math.sin(math.pi*withdraw)
                    q=hold_q.slerp(q,withdraw)
                else:
                    hand=neutral.lerp(contact,arrival)
                    hand+=orient_inverse@Vector((.08,.015,0))*math.sin(math.pi*arrival)
                    q=q.slerp(hold_q,arrival)
                radial_x,radial_y=grip_module.ROUND_WRIST_RADIAL
                # Keep the open hand outside the shaft throughout its approach
                # or departure, then close the radial gap with the fingers.
                clearance=.040*math.sin(math.pi*min(.5,1-fitted))
                clearance*=1-withdraw if giver else arrival
                hand+=orient_inverse@Vector((sign*(clearance-radial_x*fitted),radial_y*fitted,0))
                axis=orient_inverse@Vector((0,0,1))
                q=Quaternion(axis,-sign*grip_module.ROUND_WRIST_ROLL*fitted)@q
            self.p['IK-Hand.'+side].matrix=Matrix.LocRotScale(hand,q,Vector((1,1,1)));update()
            self.move('IK-Pole-Forearm.'+side,target=(s*.60,-.07,1.0))
        # apply() already eases the curl. Applying smootherstep here as well
        # compresses most rotation into the middle and jerks distal phalanges.
        grip_module.apply(self.rig,self.grip,grip,angles=BATON_GRIP)
        grip_module.fit_round_fingers(self.p,active_side,fitted)
        update()
        target=baton_center(t)
        partner_face=partner.rig.matrix_world@Vector((0,-.05,1.38))
        look_at_partner = 1-ease(t,.23,.54) if approach is not None and t<1. else ease(t,4.90,.65)
        target=target.lerp(partner_face,look_at_partner)
        for side in ('L','R'):self.move('TGT-Eye.'+side,target=inverse@target)


def duplicate_rain(first):
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
    return second,originals,copies


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--handoff',action='store_true',help='Transfer a light vertical baton with overlapping hand support')
    parser.add_argument('--approach',action='store_true',help='Precede the handoff with a planted approach by the receiver')
    parser.add_argument('--check-only',action='store_true',help='Evaluate controls and skin without rendering; --render checks the whole clip')
    parser.add_argument('--save-scene',action='store_true',help='Check and bake the handoff to a packed scene and resumable render job')
    parser.add_argument('--frames',default='0,36,65,100,145,179')
    parser.add_argument('--view',choices=('front','reverse','contact'),default='front')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.approach and not args.handoff:
        parser.error('--approach requires --handoff')
    if args.save_scene and not args.handoff:
        parser.error('--save-scene requires --handoff')
    lead_in = APPROACH_FRAMES if args.approach else 0
    count = COUNT + lead_in
    out=Path(args.out).resolve()
    if not out.is_relative_to(ROOT/'_game/study'): raise ValueError('Output outside study folder')
    frames=list(range(count)) if args.render else [int(x) for x in args.frames.split(',')]
    if not frames or any(f<0 or f>=count for f in frames): raise ValueError('Frames outside scene')
    if args.save_scene and frames != list(range(frames[0],frames[-1]+1)):
        parser.error('--save-scene requires a contiguous frame range')
    if args.save_scene and out.exists():
        parser.error('--save-scene requires a new job output folder')
    out.mkdir(parents=True,exist_ok=not args.save_scene)
    if shutil.disk_usage(out).free<256*1024**2: raise RuntimeError('Less than 256 MiB free')
    check_frames = list(range(count)) if args.render else sorted({f for k in frames for f in (max(0,k-1),k,min(count-1,k+1))})
    source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
    if bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    scene=bpy.context.scene; first=bpy.data.objects['RIG-rain']
    second,originals,copies=duplicate_rain(first)
    a=Performer(first,-.31 if args.handoff else -.62,65 if args.handoff else 50)
    b=Performer(second,.31 if args.handoff else .62,-65 if args.handoff else -50)
    receiver_x = b.rig.location.x

    def position_receiver(f):
        if args.approach:
            b.rig.location.x = receiver_x+approach_root(f/FPS)
            update()
    if args.handoff:
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        import rain_grip
        for actor,side in ((a,'R'),(b,'L')):
            actor.grip=rain_grip.capture(actor.rig,side)
            actor.names+=actor.grip['names']
            actor.basis.update(actor.grip['basis'])
            actor.tracked+=actor.grip['names']
        bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=.018,depth=.34,location=baton_center(0))
        baton=bpy.context.object;baton.name='Light baton'
        metal=bpy.data.materials.new('Warm brass');metal.diffuse_color=(.6,.25,.045,1);metal.use_nodes=True
        bsdf=metal.node_tree.nodes['Principled BSDF'];bsdf.inputs['Base Color'].default_value=metal.diffuse_color;bsdf.inputs['Metallic'].default_value=.55;bsdf.inputs['Roughness'].default_value=.3
        baton.data.materials.append(metal)
        bevel=baton.modifiers.new('Soft ends','BEVEL');bevel.width=.003;bevel.segments=3
    # Readable actor identity without changing skin or face materials.
    top=next(ob for ob in copies if ob.name.startswith('GEO-rain-top'))
    mat=bpy.data.materials.new('Listener teal shirt');mat.diffuse_color=(.06,.23,.22,1);mat.use_nodes=True
    shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Base Color'].default_value=mat.diffuse_color;shader.inputs['Roughness'].default_value=.6
    top.data.materials.clear();top.data.materials.append(mat)
    def aim(ob,target): ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
    for ob in list(scene.objects):
        if ob.type in ('LIGHT','CAMERA'): bpy.data.objects.remove(ob,do_unlink=True)
    bpy.ops.object.camera_add(location={'front':(0,-6,2.3),'reverse':(0,6,2.3),'contact':(.7,-4,1.55)}[args.view])
    scene.camera=bpy.context.object;scene.camera.data.type='ORTHO';scene.camera.data.ortho_scale=.72 if args.view=='contact' else (2.25 if args.handoff and not args.approach else 2.8)
    aim(scene.camera,(0,-.23,1.05) if args.view=='contact' else (0,0,.88))
    if args.approach and args.view == 'contact':
        # Keep both faces and the two grip heights on the same side of the axis as the wide shot.
        scene.camera.location = (.76,-4,1.57)
        scene.camera.data.ortho_scale = 1.15
        aim(scene.camera,(0,-.19,1.24))
    for location,power,size in [((-3,-4,5),650,4),((3,-2,3),350,3),((0,3,4),600,3)]:
        bpy.ops.object.light_add(type='AREA',location=location);light=bpy.context.object;light.data.energy=power;light.data.shape='DISK';light.data.size=size;aim(light,(0,0,1))
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,.00115))
    floor=bpy.data.materials.new('Neutral floor');floor.diffuse_color=(.09,.115,.13,1);floor.use_nodes=True;floor.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=floor.diffuse_color
    bpy.context.object.data.materials.append(floor)
    scene.world=bpy.data.worlds.new('Partner world');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.18,.22,.28,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.35
    scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=640;scene.render.resolution_percentage=100
    if args.approach:
        scene.render.resolution_percentage = 80
        scene.eevee.taa_render_samples = 12
    scene.render.image_settings.file_format='PNG';scene.render.fps=FPS;scene.view_settings.view_transform='AgX'
    scene.render.threads_mode='FIXED';scene.render.threads=4
    report={'source_sha256':source_hash,'credit':'Rain Rig (CC) Blender Foundation | studio.blender.org | CC BY 4.0',
            'frames':count,'fps':FPS,'max_wrist_error_m':0.,'max_ankle_error_m':0.,'max_sole_error_m':0.,
            'max_step_m':0.,'max_angle_deg':0.,'source_unchanged':False,
            'known_invalid_driver':'Source Spine3 driver references absent STR-Spine4; not repaired',
            'scope':'Controller continuity and native IK, not a full mesh-collision or artistic certificate','rendered':[]}
    if args.handoff:
        report['shaft_contact_samples']=[]
        report['surface_intersections']=[]
        report['max_closed_wrist_to_shaft_error_m']=0.
        report['dual_support_frames']=[]
    if args.approach:
        report.update(approach_frames=lead_in, max_planted_foot_drift_m=0., min_swing_clearance_m=None)
    planted = {}
    mesh_flags={ob:ob.hide_viewport for ob in scene.objects if ob.type=='MESH'}
    for ob in mesh_flags:ob.hide_viewport=True
    update();cache={};checks={};previous=None;previous_frame=None
    report['checked_frames']=len(check_frames)
    for f in check_frames:
        t = (f-lead_in)/FPS
        position_receiver(f)
        if args.handoff:
            a.handoff_pose(t,True,b,rain_grip)
            b.handoff_pose(t,False,a,rain_grip,f/FPS if args.approach else None)
        else:
            a.pose(f/FPS,True,b);b.pose(f/FPS,False,a)
        current=[actor.snapshot() for actor in (a,b)]
        for actor in (a,b):
            for side in ('L','R'):
                error=(actor.p['FK-Hand.'+side].matrix.translation-actor.p['IK-Hand.'+side].matrix.translation).length
                report['max_wrist_error_m']=max(report['max_wrist_error_m'],error)
                if error>.002: raise RuntimeError(f'Unreachable hand at {f}: {actor.rig.name} {side}, {error}')
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
    for f in frames:
        t = (f-lead_in)/FPS
        position_receiver(f)
        for actor,basis in zip((a,b),cache[f]):
            for n,m in basis.items():actor.p[n].matrix_basis=m
        update()
        if args.handoff:
            baton.location=baton_center(t)
            update()
        for actor,expected in zip((a,b),checks[f]):
            for n,m in expected.items():
                actual = actor.rig.matrix_world@actor.p[n].matrix
                error=max(abs(actual[i][j]-m[i][j]) for i in range(4) for j in range(4))
                if error>1e-5:raise RuntimeError(f'Cache differs at {f}: {n}')
        dg=bpy.context.evaluated_depsgraph_get()
        if args.handoff:
            center=baton_center(t)
            giver_closed=t<=3.05;receiver_closed=t>=2.80
            if not (giver_closed or receiver_closed):raise RuntimeError('Object has no supporting hand')
            if giver_closed and receiver_closed:report['dual_support_frames'].append(f)
            for actor,side,sign,height,closed in ((a,'R',-1,.08,giver_closed),(b,'L',1,-.04,receiver_closed)):
                if closed:
                    actual=actor.rig.matrix_world@actor.p['FK-Hand.'+side].matrix.translation
                    radial_x,radial_y=rain_grip.ROUND_WRIST_RADIAL
                    error=(actual-center-Vector((sign*(.046-radial_x),.049+radial_y,height))).length
                    report['max_closed_wrist_to_shaft_error_m']=max(report['max_closed_wrist_to_shaft_error_m'],error)
                    if error>.002:raise RuntimeError(f'Holding hand slides against shaft at {f}: {error}')
            surfaces=[skin_regions(next(ob for ob in objects if ob.name.startswith('GEO-rain-body')),dg) for objects in (originals,copies)]
            shaft=skin_regions(baton,dg)['full']
            tops=[skin_regions(next(ob for ob in objects if ob.name.startswith('GEO-rain-top')),dg)['full'] for objects in (originals,copies)]
            intersections={}
            if args.approach:
                intersections['partner_bodies']=len(surfaces[0]['full'].overlap(surfaces[1]['full']))
            for i,skin in enumerate(surfaces):
                for name,tree in (('shaft',shaft),):
                    intersections[f'{i}_{name}_body']=len(tree.overlap(skin['full']))
                for side in ('L','R'):
                    arm=skin[side]
                    if not arm or not skin['torso']:raise RuntimeError('Missing weighted arm/torso region')
                    intersections[f'{i}_{side}_torso']=len(arm.overlap(skin['torso']))
                    intersections[f'{i}_{side}_shirt']=len(arm.overlap(tops[i]))
                    intersections[f'{i}_{side}_partner']=len(arm.overlap(surfaces[1-i]['full']))
            report['surface_intersections'].append({'frame':f,'pairs':intersections})
            for objects,side,label,closed in ((originals,'R','giver',giver_closed),(copies,'L','receiver',receiver_closed)):
                body=next(ob for ob in objects if ob.name.startswith('GEO-rain-body'))
                groups={g.index for g in body.vertex_groups if g.name.endswith('.'+side) and any(k in g.name for k in ('Hand','Index','Middle','Ring','Pinky','Thumb'))}
                ev=body.evaluated_get(dg);mesh=ev.to_mesh()
                vertices=[v for v in mesh.vertices if sum(g.weight for g in v.groups if g.group in groups)>.65]
                points=[ev.matrix_world@v.co for v in vertices]
                labels=[body.vertex_groups[max(v.groups,key=lambda g:g.weight).group].name for v in vertices]
                radial=[]
                for p in points:
                    dr=math.hypot(p.x-center.x,p.y-center.y)-.018
                    dz=abs(p.z-center.z)-.17
                    radial.append(math.hypot(max(dr,0),max(dz,0))+min(max(dr,dz),0))
                ev.to_mesh_clear()
                if not radial:raise RuntimeError('No weighted hand vertices')
                minimum=min(radial)
                nearest=radial.index(minimum)
                report['shaft_contact_samples'].append({'frame':f,'actor':label,'closed':closed,'minimum_vertex_clearance_m':minimum,'sample_count':len(radial),'nearest_group':labels[nearest], 'nearest_offset_m':list(points[nearest]-center)})
                if args.view=='contact' and not args.render:
                    (out/f'hand_{label}_{f:04d}.json').write_text(json.dumps([{'offset':list(p-center),'group':g} for p,g in zip(points,labels)]))
                if (args.render or args.save_scene) and (minimum<-.003 or (closed and minimum>.008)):
                    (out/'contact_failed.json').write_text(json.dumps(report['shaft_contact_samples'][-1],indent=2))
                    raise RuntimeError(f'Hand/shaft contact failed at {f}: {label}, {minimum}')
        for actor,objects in ((a,originals),(b,copies)):
            shoe=next(ob for ob in objects if ob.name.startswith('GEO-rain-shoes'))
            ev=shoe.evaluated_get(dg);mesh=ev.to_mesh()
            for side in ('L','R'):
                groups={g.index for g in shoe.vertex_groups if g.name.endswith('.'+side)}
                sole=min((ev.matrix_world@v.co).z for v in mesh.vertices if any(g.group in groups and g.weight>.5 for g in v.groups))
                expected_lift = 0.
                if args.approach and actor is b:
                    start,duration = APPROACH_STEPS[side]
                    elapsed = f/FPS
                    expected_lift = approach_foot(elapsed,side).z
                    if start < elapsed < start+duration:
                        clearance = sole-.00115
                        minimum = report['min_swing_clearance_m']
                        report['min_swing_clearance_m'] = clearance if minimum is None else min(minimum,clearance)
                    else:
                        phase = (side,elapsed>=start+duration)
                        foot = actor.rig.matrix_world@actor.p['MSTR-Foot.'+side].matrix.translation
                        drift = (foot-planted.setdefault(phase,foot)).length
                        report['max_planted_foot_drift_m']=max(report['max_planted_foot_drift_m'],drift)
                        if drift>.0005:raise RuntimeError(f'Planted foot moved at {f}: {side}, {drift}')
                error=abs(sole-.00115-expected_lift);report['max_sole_error_m']=max(report['max_sole_error_m'],error)
                if error>.002:raise RuntimeError(f'Sole support at {f}: {side}, {error}')
            ev.to_mesh_clear()
    if args.handoff:
        failures=[r for r in report['surface_intersections'] if any(r['pairs'].values())]
        if failures:
            (out/'geometry_failed.json').write_text(json.dumps(report,indent=2))
            if args.render or args.save_scene:raise RuntimeError(f'Surface intersections at {len(failures)} frames; see geometry_failed.json')
    if args.save_scene:
        from contact_reaction import _action, _curves
        from prepare_study_scene import localize_widget_meshes

        for index, actor in enumerate((a,b)):
            samples = [dict(frame=f,basis=cache[f][index]) for f in frames]
            action = _action(actor.rig, [actor.p[n] for n in actor.names], samples,
                             f'Handoff {index+1}', scene)
            animation = actor.rig.animation_data_create()
            animation.action = action
            animation.action_slot = action.slots[0]
            animation.use_nla = False
        for f in frames:
            position_receiver(f)
            if args.approach:
                b.rig.keyframe_insert('location',index=0,frame=f)
            baton.location = baton_center((f-lead_in)/FPS)
            baton.keyframe_insert('location',frame=f)
        for obj in (b.rig,baton):
            for curve in _curves(obj.animation_data.action):
                for key in curve.keyframe_points:
                    key.interpolation = 'LINEAR'
        scene.frame_start, scene.frame_end = frames[0],frames[-1]
        scene.frame_set(scene.frame_start)
        localize_widget_meshes()
        bpy.ops.file.pack_all()
        external = bpy.utils.blend_paths(absolute=True, packed=False)
        if external:
            raise RuntimeError(f'Scene still references an external file: {external[0]}')
        if bpy.ops.wm.save_as_mainfile(filepath=str(out/'handoff.blend'),copy=True) != {'FINISHED'}:
            raise RuntimeError('Blender did not save the checked scene')
        size = [side*scene.render.resolution_percentage//100
                for side in (scene.render.resolution_x,scene.render.resolution_y)]
        job = dict(schema_version=1,scene='handoff.blend',out='draft',
                   frames=[frames[0],frames[-1]+1],size=size,fps=FPS)
        (out/'job.json').write_text(json.dumps(job,indent=2)+'\n',encoding='utf-8')
    # Complete all requested geometry checks before spending time on images.
    for f in ([] if args.check_only or args.save_scene else frames):
        position_receiver(f)
        for actor,basis in zip((a,b),cache[f]):
            for n,m in basis.items():actor.p[n].matrix_basis=m
        if args.handoff:baton.location=baton_center((f-lead_in)/FPS)
        update()
        scene.render.filepath=str(out/f'{f:04d}.png');bpy.ops.render.render(write_still=True);report['rendered'].append(f)
    report['source_unchanged']=hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash
    report['geometry_checked_frames']=len(frames)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PARTNER_DONE',len(report['rendered']),'rendered;',len(frames),'geometry checked',flush=True)


if __name__=='__main__': main()
