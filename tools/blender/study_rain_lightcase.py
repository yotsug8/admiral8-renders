"""Editable Rain acting study: expected weight, overshoot, recovery, composure.

Native keyed controls and a Child Of pickup; study_rain_partner supplies the
verified hand orientation and FK helpers. No source file is overwritten.
"""
import argparse, hashlib, json, math, sys
from pathlib import Path
import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from study_rain_partner import Performer, SOURCE, BATON_GRIP, skin_regions
import rain_grip

# Frame, pelvis Y/Z offset, spine lean, head pitch/yaw, right foot Y/Z,
# case handle centre, free hand target, right-hand reach, closed grip.
POSES=[
 (0,   0,-.018,  0,-8, 0, 0,0, (-.28,-.34,.85),(.22,-.06,.86),0,0),
 (18,  0,-.035,  9,18, 0, 0,0, (-.28,-.34,1.00),(.25, .02,1.02),.35,0),
 (26,-.01,-.055,18,14, 0, 0,0, (-.28,-.34,1.00),(.25, .03,1.01),.70,0),
 (38,-.02,-.085,27,10, 0, 0,0, (-.28,-.34,.85),(.24, .04,1.00),1,0),
 (53,-.03,-.105,33, 3, 0, 0,0, (-.28,-.34,.85),(.25, .05,.99),1,1),
 (64,-.02,-.135,38, 1, 0, 0,0, (-.28,-.34,.85),(.30, .01,1.01),1,1),
 (76, .09,-.025,-16,7, 0, .07,.075,(-.38,-.10,1.22),(.40, .05,1.22),1,1),
 (82, .16,-.018,-24,9, 0, .19,.09,(-.40,-.03,1.30),(.42, .08,1.29),1,1),
 (92, .19,-.055, -8,5, 0, .31,0,(-.39, .02,1.10),(.40, .08,1.10),1,1),
 (106,.19,-.025,  0,8, 0, .31,0,(-.35, .10,.94),(.28, .08,.94),1,1),
 (126,.19,-.025,  0,4,-35,.31,0,(-.35, .12,.92),(.25, .10,.94),1,1),
 (148,.19,-.018,  3,-8,18,.31,0,(-.35,.12,.92),(.33, .05,1.13),1,1),
 (178,.19,-.018,  3,-5,18,.31,0,(-.35,.12,.92),(.22, .10,.88),1,1),
 (209,.19,-.018,  3,-5,18,.31,0,(-.35,.12,.92),(.22, .10,.88),1,1),
]

def update():bpy.context.view_layer.update()

def preflight(scene,rig,case,frames):
    """Check the evaluated timeline, including native interpolation and pickup."""
    body=bpy.data.objects['GEO-rain-body'];top=bpy.data.objects['GEO-rain-top']
    shoe=next(ob for ob in scene.objects if ob.name.startswith('GEO-rain-shoes'))
    parts=list(case.children);p=rig.pose.bones
    tracked=[b for b in p if b.name.startswith(('FK-Hand','FK-Head','FK-Chest','MSTR-Pelvis','MSTR-Foot','FK-Index','FK-Middle','FK-Ring','FK-Pinky','FK-Thumb'))]
    rows=[];failures=[];previous=None;grip_reference=None
    scene.frame_set(53);update()
    grip_reference=(rig.matrix_world@p['FK-Hand.R'].matrix).inverted()@case.matrix_world
    for f in frames:
        scene.frame_set(f);update();dg=bpy.context.evaluated_depsgraph_get()
        errors={s:(p['FK-Hand.'+s].matrix.translation-p['IK-Hand.'+s].matrix.translation).length for s in ('L','R')}
        skin=skin_regions(body,dg);shirt=skin_regions(top,dg)['full'];pairs={}
        for side in ('L','R'):
            pairs[side+'_torso']=len(skin[side].overlap(skin['torso']))
            pairs[side+'_shirt']=len(skin[side].overlap(shirt))
        floor=10.
        for part in parts:
            tree=skin_regions(part,dg)['full']
            pairs[part.name+'_body']=len(tree.overlap(skin['full']))
            pairs[part.name+'_shirt']=len(tree.overlap(shirt))
            ev=part.evaluated_get(dg);mesh=ev.to_mesh()
            floor=min(floor,min((ev.matrix_world@v.co).z for v in mesh.vertices));ev.to_mesh_clear()
        ev=shoe.evaluated_get(dg);mesh=ev.to_mesh();soles={}
        for side in ('L','R'):
            groups={g.index for g in shoe.vertex_groups if g.name.endswith('.'+side)}
            soles[side]=min((ev.matrix_world@v.co).z for v in mesh.vertices if any(g.group in groups and g.weight>.5 for g in v.groups))
        ev.to_mesh_clear()
        attached=(rig.matrix_world@p['FK-Hand.R'].matrix).inverted()@case.matrix_world
        anchor=max(abs(attached[i][j]-grip_reference[i][j]) for i in range(4) for j in range(4)) if f>=53 else 0.
        matrices={b.name:b.matrix.copy() for b in tracked};step=angle=0.
        if previous and previous[0]==f-1:
            step=max((m.translation-previous[1][n].translation).length for n,m in matrices.items())
            angle=max(math.degrees(2*math.acos(min(1.,abs(m.to_quaternion().dot(previous[1][n].to_quaternion()))))) for n,m in matrices.items())
        previous=(f,matrices)
        row={'frame':f,'wrist_error_m':errors,'sole_z_m':soles,'case_bottom_z_m':floor,'attachment_matrix_error':anchor,'surface_pairs':pairs,'max_step_m':step,'max_angle_deg':angle}
        rows.append(row);bad=[]
        if max(errors.values())>.002:bad.append('unreachable wrist')
        if any(pairs.values()):bad.append('surface intersection')
        if floor<-.002:bad.append('case below floor')
        if abs(soles['L']-.00115)>.002:bad.append('left support')
        if (f<=64 or f>=92) and abs(soles['R']-.00115)>.002:bad.append('right support')
        if min(soles.values())<-.002:bad.append('foot below floor')
        if anchor>1e-4:bad.append('sliding grip')
        if step>.08 or angle>20:bad.append('abrupt pose transition')
        if bad:failures.append({'frame':f,'reasons':bad})
    return {'frames':rows,'failures':failures,'passed':not failures,'scope':'Weighted forearms/hands against torso and shirt; all case parts against body/shirt; supports and native timeline. Hair, finger self-contact and artistic quality require visual review.'}

def material(name,color):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
    n=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    n.inputs['Base Color'].default_value=m.diffuse_color;n.inputs['Roughness'].default_value=.45
    return m

def box(name,location,size,mat,parent=None,bevel=.015):
    bpy.ops.mesh.primitive_cube_add(size=1,location=location)
    ob=bpy.context.object;ob.name=name;ob.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    ob.data.materials.append(mat)
    if bevel:
        mod=ob.modifiers.new('Rounded edges','BEVEL');mod.width=bevel;mod.segments=3
    if parent:ob.parent=parent
    return ob

def build(out):
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
    if bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    scene=bpy.context.scene;rig=bpy.data.objects['RIG-rain'];actor=Performer(rig,0,0)
    actor.grip=rain_grip.capture(rig,'R');actor.names+=actor.grip['names'];actor.basis.update(actor.grip['basis'])
    actor.free_grip=rain_grip.capture(rig,'L');actor.names+=actor.free_grip['names'];actor.basis.update(actor.free_grip['basis'])
    # Clear actions only in this disposable scene, so the new editable timeline
    # cannot accidentally mix with the source rig's demonstration action.
    for ob in bpy.data.objects:
        if ob.animation_data and ob.animation_data.action:ob.animation_data.action=None
    p=actor.p;rest=actor.rest
    for name in actor.names:
        # Rain drives several control modes from this native custom property.
        # Writing rotation_mode alone is reverted at the next depsgraph update.
        if 'rot_mode' in p[name]:p[name]['rot_mode']=0
        p[name].rotation_mode='QUATERNION'
    rig.update_tag();update()
    if any(p[n].rotation_mode!='QUATERNION' for n in actor.names):raise RuntimeError('Rig overrides authored rotation mode')
    holding=actor.hand_q('R',(0,-1,0),(0,0,1))
    neutral=actor.hands['R']; previous={};authored={}
    mesh_flags={ob:ob.hide_viewport for ob in scene.objects if ob.type=='MESH'}
    for ob in mesh_flags:ob.hide_viewport=True
    for f,hip_y,hip_z,lean,pitch,yaw,step,lift,handle,left,reach,grip in POSES:
        for n,m in actor.basis.items():p[n].matrix_basis=m
        update()
        actor.move('MSTR-Pelvis',delta=(0,hip_y,hip_z))
        actor.move('MSTR-Foot.L',delta=(.025,0,0));actor.move('MSTR-Foot.R',delta=(-.025,step,lift))
        actor.rotate('FK-Spine',(1,0,0),lean*.45);actor.rotate('FK-Chest',(1,0,0),lean*.55)
        actor.rotate('FK-Scarf1',(1,0,0),-lean*.55)
        actor.rotate('FK-Head',(1,0,0),pitch-lean*.45);actor.rotate('FK-Head',(0,0,1),yaw)
        startled=1 if f in (76,82) else (.35 if f==92 else 0)
        actor.rotate('MSTR-Jaw',(1,0,0),9*startled)
        actor.move('MSTR-Eyebrow.L',delta=(0,0,.008*startled+.004*(f>=126)))
        actor.move('MSTR-Eyebrow.R',delta=(0,0,.008*startled))
        for i,droop in enumerate((10,25,20,10),1):actor.rotate(f'FK-Hair_Ponytail{i}',(1,0,0),-droop-lean*.15)
        wrist=Vector((-.24,-.08,.97)).lerp(Vector(handle)+Vector((0,.049,.046)),reach)
        q=neutral.slerp(holding,reach)
        p['IK-Hand.R'].matrix=Matrix.LocRotScale(wrist,q,Vector((1,1,1)));update()
        free_q=actor.hands['L']
        if f in (76,82,92):free_q=actor.hand_q('L',(1,-.2,.35),(0,1,0))
        elif f==148:free_q=actor.hand_q('L',(1,-.4,0),(0,0,-1))
        p['IK-Hand.L'].matrix=Matrix.LocRotScale(Vector(left),free_q,Vector((1,1,1)));update()
        for side,sign in (('L',1),('R',-1)):
            actor.move('IK-Pole-Forearm.'+side,target=(sign*.30,hip_y+.22,.85))
        # A low nearby world target rolled both irises behind the eyelids.
        # Head aim carries the acting beat; keep gaze within its forward cone.
        head=p['FK-Head']
        forward=(head.matrix.to_3x3()@head.bone.matrix_local.to_3x3().inverted()@Vector((0,-1,0))).normalized()
        eye_center=(p['DEF-Eye.L'].matrix.translation+p['DEF-Eye.R'].matrix.translation)*.5
        for side in ('L','R'):actor.move('TGT-Eye.'+side,target=eye_center+2*forward)
        rain_grip.apply(rig,actor.grip,grip,angles=BATON_GRIP)
        rain_grip.apply(rig,actor.free_grip,.20 if f in (76,82) else .50);update()
        authored[f]={n:p[n].matrix.copy() for n in actor.names}
        for n in actor.names:
            bone=p[n]
            if n in previous and bone.rotation_quaternion.dot(previous[n])<0:bone.rotation_quaternion.negate()
            previous[n]=bone.rotation_quaternion.copy()
            for channel in ('location','rotation_quaternion','scale'):bone.keyframe_insert(channel,frame=f,group=n)
        print('POSE',f,flush=True)
    for ob,hidden in mesh_flags.items():ob.hide_viewport=hidden
    for layer in rig.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:key.handle_left_type=key.handle_right_type='AUTO_CLAMPED'
    playback_error=0.
    for f,expected in authored.items():
        scene.frame_set(f);update()
        for n,m in expected.items():
            error=max(abs(p[n].matrix[i][j]-m[i][j]) for i in range(4) for j in range(4))
            playback_error=max(playback_error,error)
            if error>1e-4:raise RuntimeError(f'Native playback differs from authored pose: {f}, {n}, {error}')
    scene['authored_playback_max_matrix_error']=playback_error
    case_mat=material('Warm ochre case',(.48,.17,.035));trim=material('Dark handle',(.045,.055,.065));seat_mat=material('Bench',(.12,.17,.19))
    bpy.ops.object.empty_add(location=POSES[0][8]);case=bpy.context.object;case.name='Light case'
    box('Case shell',(0,0,-.225),(.30,.16,.27),case_mat,case,.025)
    for x in (-.105,.105):box('Handle support',(x,0,-.045),(.025,.03,.09),trim,case,.008)
    bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=.018,depth=.21,location=(0,0,0),rotation=(0,math.pi/2,0))
    handle=bpy.context.object;handle.name='Case handle';handle.data.materials.append(trim);handle.parent=case
    box('Bench top',(-.28,-.34,.465),(.38,.24,.05),seat_mat)
    for x in (-.42,-.14):
        for y in (-.42,-.26):box('Bench leg',(x,y,.22),(.035,.035,.44),seat_mat,bevel=.003)
    # Keep the case in world space until the grip is closed. Preserve its
    # world transform at the switch, then let the evaluated native hand carry it.
    scene.frame_set(53);update();hand_world=rig.matrix_world@p['FK-Hand.R'].matrix
    con=case.constraints.new('CHILD_OF');con.name='Closed grip';con.target=rig;con.subtarget='FK-Hand.R';con.inverse_matrix=hand_world.inverted()
    for frame,value in ((0,0),(52,0),(53,1),(209,1)):
        con.influence=value;con.keyframe_insert('influence',frame=frame)
    for layer in case.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:key.interpolation='CONSTANT'
    for ob in list(scene.objects):
        if ob.type in ('LIGHT','CAMERA'):bpy.data.objects.remove(ob,do_unlink=True)
    bpy.ops.object.camera_add(location=(3,-6,2.5));cam=bpy.context.object;cam.name='Study camera';cam.data.type='ORTHO';cam.data.ortho_scale=2.35
    cam.rotation_euler=(Vector((-.08,0,.92))-cam.location).to_track_quat('-Z','Y').to_euler();scene.camera=cam
    for loc,power in (((-3,-4,5),750),((3,-2,3),400),((0,3,4),600)):
        bpy.ops.object.light_add(type='AREA',location=loc);ob=bpy.context.object;ob.data.energy=power;ob.data.size=4;ob.rotation_euler=(Vector((0,0,1))-ob.location).to_track_quat('-Z','Y').to_euler()
    floor_mat=material('Floor',(.11,.14,.16));box('Floor',(0,0,-.025), (200,200,.05),floor_mat,bevel=0)
    scene.frame_start=0;scene.frame_end=209;scene.render.fps=30;scene.render.resolution_x=640;scene.render.resolution_y=720;scene.render.resolution_percentage=100
    scene.render.engine='BLENDER_EEVEE';scene.view_settings.view_transform='AgX'
    scene.world=bpy.data.worlds.new('Study world');scene.world.use_nodes=True;next(n for n in scene.world.node_tree.nodes if n.type=='BACKGROUND').inputs['Strength'].default_value=.4
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_perspective='CAMERA';area.spaces.active.overlay.show_overlays=False;area.spaces.active.shading.type='MATERIAL'
    scene.frame_set(0);bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'lightcase.blend'))
    return scene,rig,case

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--frames',default='0,38,64,82,106,148,209');ap.add_argument('--render',action='store_true');ap.add_argument('--load',action='store_true');ap.add_argument('--check-only',action='store_true');ap.add_argument('--preview',action='store_true');args=ap.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out=Path(args.out).resolve()
    if not out.is_relative_to(ROOT/'_game/study'):raise ValueError('Output outside study directory')
    out.mkdir(parents=True,exist_ok=True)
    if args.load:
        bpy.ops.wm.open_mainfile(filepath=str(out/'lightcase.blend'),use_scripts=False);scene=bpy.context.scene;rig=bpy.data.objects['RIG-rain'];case=bpy.data.objects['Light case']
    else:scene,rig,case=build(out)
    frames=list(range(210)) if args.render or args.check_only else [int(x) for x in args.frames.split(',')]
    if not frames or any(f<0 or f>209 for f in frames):raise ValueError('Frames outside the study timeline')
    report=preflight(scene,rig,case,frames)
    report['source_sha256']=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report['authored_playback_max_matrix_error']=scene.get('authored_playback_max_matrix_error')
    report['credit']='Rain Rig (CC) Blender Foundation | studio.blender.org | CC BY 4.0'
    (out/'preflight.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.check_only:
        if not report['passed']:raise RuntimeError('Preflight failed; see preflight.json')
        return
    if args.render and not report['passed']:raise RuntimeError('Preflight failed; see preflight.json')
    if args.preview:scene.render.resolution_percentage=50
    report={'source_sha256':report['source_sha256'],'frames':[],'scope':'Blocking poses, not yet accepted as a finished animation'}
    for f in frames:
        scene.frame_set(f);update();errors={side:(rig.pose.bones['FK-Hand.'+side].matrix.translation-rig.pose.bones['IK-Hand.'+side].matrix.translation).length for side in ('L','R')}
        report['frames'].append({'frame':f,'wrist_error_m':errors,'case_center':list(case.matrix_world.translation)})
        if not args.check_only:
            scene.render.filepath=str(out/f'{f:04d}.png');bpy.ops.render.render(write_still=True)
    (out/'blocking-report.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
