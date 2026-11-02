"""Restage the leap around a native full-body axe attack and a shared contact.

Modes: inspect, contact_scan, block, block_motion, motion, look.
These are internal asset, motion and lighting tests; none marks a delivery approved.
"""
import json
import hashlib
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils import noise as terrain_noise

sys.path.insert(0,str(Path(__file__).resolve().parent))
# Reuse only asset import, native bone merge and material utilities.
# Import initializes a clean scene; the rejected v1 staging is not called.
import doomsday_scene as assets
from contact_reaction import _basis, _solve_leg

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/doomsday/v2'
OUT.mkdir(parents=True,exist_ok=True)
MODE=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'inspect'
sc=bpy.context.scene
sc.render.fps=30
sc.cycles.samples=32


def terrain_height(x,y):
    fade=assets.smooth((math.hypot(x,y+1)-10)/18)
    return fade*(3.5+3*terrain_noise.noise(Vector((x*.035,y*.035,0)))+math.sin(x*.08+y*.06))


def simple_stage():
    sc.world.node_tree.nodes['Background'].inputs[0].default_value=(.055,.07,.09,1)
    sc.world.node_tree.nodes['Background'].inputs[1].default_value=.6
    bpy.ops.mesh.primitive_plane_add(size=200)
    ground=bpy.context.object
    ground.name='Contact ground'
    ground.data.materials.append(assets.flatmat('ground',(.065,.075,.09),.9))
    assets.area('Key',(0,-4,7),(.74,.84,1),1200,5)
    assets.area('Rim',(-3,3,6),(1,.54,.24),1700,3)


def inspect():
    simple_stage()
    h=assets.hero('axe',(0,0,0),0)
    arm=h['arm'];act=h['acts']['culling_blade']
    arm.animation_data.action=act
    sc.render.resolution_x=360;sc.render.resolution_y=480
    assets.camera((5,-10,4),(0,0,1.65),45)
    report={'clip':list(act.frame_range),'bones':{},'samples':[], 'morphs':{}}
    for o in h['objects']:
        if o.type=='MESH' and o.data.shape_keys:
            report['morphs'][o.name]=[k.name for k in o.data.shape_keys.key_blocks]
    for b in arm.pose.bones:
        report['bones'][b.name]={'parent':b.parent.name if b.parent else None}
    for i in range(11):
        f=act.frame_range[0]+(act.frame_range[1]-act.frame_range[0])*i/10
        sc.frame_set(int(f),subframe=f-int(f));bpy.context.view_layer.update()
        report['samples'].append({'frame':f,'world':{b.name:list(arm.matrix_world@b.head) for b in arm.pose.bones}})
        sc.render.filepath=str(OUT/f'axe_pose_{i:02d}.png')
        bpy.ops.render.render(write_still=True)
    (OUT/'axe_inspect.json').write_text(json.dumps(report,indent=2))
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'axe_source.blend'))


def sample(h,clip,frame):
    arm=h['arm'];arm.animation_data.action=h['acts'][clip]
    left=math.floor(frame);right=math.ceil(frame);t=frame-left
    sc.frame_set(left);bpy.context.view_layer.update()
    if left==right:return {b.name:arm.matrix_world@b.matrix for b in arm.pose.bones}
    first={b.name:b.matrix_basis.copy() for b in arm.pose.bones}
    sc.frame_set(right);bpy.context.view_layer.update()
    last={b.name:b.matrix_basis.copy() for b in arm.pose.bones}
    pose={}
    for b in sorted(arm.pose.bones,key=lambda b:len(b.parent_recursive)):
        p,q,s=first[b.name].decompose();p1,q1,s1=last[b.name].decompose()
        local=Matrix.LocRotScale(p.lerp(p1,t),q.slerp(q1,t),s.lerp(s1,t))
        kw={} if not b.parent else {'parent_matrix':pose[b.parent.name],'parent_matrix_local':b.parent.bone.matrix_local}
        pose[b.name]=b.bone.convert_local_to_pose(local,b.bone.matrix_local,**kw)
    return {n:arm.matrix_world@m for n,m in pose.items()}


def mixed(a,b,t):
    result={}
    for n,m in a.items():
        loc,q,s=m.decompose();loc2,q2,s2=b[n].decompose()
        result[n]=Matrix.LocRotScale(loc.lerp(loc2,t),q.slerp(q2,t),s.lerp(s2,t))
    return result


def shifted(pose,delta):
    T=Matrix.Translation(delta)
    return {n:T@m for n,m in pose.items()}


def rotate_branch(arm,pose,name,axis,angle):
    pivot=pose[name].translation.copy()
    T=Matrix.Translation(pivot)@Matrix.Rotation(angle,4,Vector(axis))@Matrix.Translation(-pivot)
    for b in [arm.pose.bones[name],*arm.pose.bones[name].children_recursive]:
        pose[b.name]=T@pose[b.name]


def bake_world(h,poses,times=None):
    arm=h['arm'];arm.animation_data.action=None
    inv=arm.matrix_world.inverted()
    previous={}
    for index,pose in enumerate(poses):
        f=index if times is None else times[index]
        for b in arm.pose.bones:
            local=_basis(b,inv@pose[b.name],inv@pose[b.parent.name] if b.parent else None)
            loc,q,scale=local.decompose()
            if b.name in previous and q.dot(previous[b.name])<0:q.negate()
            previous[b.name]=q.copy()
            b.location,b.rotation_quaternion,b.scale=loc,q,scale
            b.rotation_mode='QUATERNION'
            for key in ('location','rotation_quaternion','scale'):b.keyframe_insert(key,frame=f)
    for layer in arm.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:key.interpolation='LINEAR'


def support_feet(h,poses):
    """Correct the deformed soles on this flat stage without moving the held weapon."""
    arm=h['arm'];selection=[];history=[]
    for ob in h['objects']:
        if ob.type!='MESH':continue
        surface={i for poly in ob.data.polygons for i in poly.vertices}
        sides={}
        for side in ('L','R'):
            ankle=arm.pose.bones['ankle_'+side]
            names={b.name for b in [ankle,*ankle.children_recursive]}
            groups={g.index for g in ob.vertex_groups if g.name in names}
            sides[side]=[v.index for v in ob.data.vertices if v.index in surface and sum(g.weight for g in v.groups if g.group in groups)>.5]
        if any(sides.values()):selection.append((ob,sides))
    if not selection:raise ValueError('No foot surfaces for ground correction')
    for iteration in range(3):
        bake_world(h,poses);changed=0
        for f,p in enumerate(poses):
            sc.frame_set(f);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
            low={'L':float('inf'),'R':float('inf')}
            for ob,sides in selection:
                ev=ob.evaluated_get(dg)
                for side,ids in sides.items():
                    if ids:low[side]=min(low[side],min((ev.matrix_world@ev.data.vertices[i].co).z for i in ids))
            desired={n:m.copy() for n,m in p.items()}
            for side in ('L','R'):
                if not math.isfinite(low[side]):raise ValueError('Incomplete sole coverage')
                lift=.003-low[side]
                if f<60:lift=max(0,lift)
                if abs(lift)<.0003:continue
                chain=tuple(n+'_'+side for n in ('thigh','knee','ankle'))
                target=p[chain[-1]].copy();target.translation.z+=lift
                _solve_leg(p,desired,chain,Vector(),None,Vector((0,-1,0)),target)
                T=target@p[chain[-1]].inverted()
                for b in arm.pose.bones[chain[-1]].children_recursive:desired[b.name]=T@p[b.name]
                history.append({'iteration':iteration,'frame':f,'side':side,'before_z':low[side],'ankle_lift':lift});changed+=1
            poses[f]=desired
        if not changed:break
    bake_world(h,poses)
    (OUT/'foot_corrections.json').write_text(json.dumps(history,indent=2))


def stabilize_arm_roll(poses):
    """Transport the held arm's roll from the preceding pose through the bend.

    Re-aiming from the source clip can cross an antipodal direction and choose
    a different half-turn. Joint positions and fixed wrist frames stay intact.
    """
    for f in range(45,len(poses)):
        current,previous=poses[f],poses[f-1]
        for side in ('L','R'):
            for bone,child in (('bicep_'+side,'elbow_'+side),('elbow_'+side,'wrist_'+side)):
                before=previous[child].translation-previous[bone].translation
                after=current[child].translation-current[bone].translation
                rotation=before.rotation_difference(after).to_matrix().to_4x4()
                matrix=rotation@previous[bone];matrix.translation=current[bone].translation
                current[bone]=matrix


def pin_subframes(h):
    """Keep the stop coherent through the shutter, not just at integer frames."""
    arm=h['arm'];times=[*range(44),*[44+i/8 for i in range((sc.frame_end-44)*8+1)]]
    poses=[];fixed=None;poles=[Vector((0,0,-1)),Vector((0,0,-1))]
    for f in times:
        sc.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
        p={b.name:arm.matrix_world@b.matrix for b in arm.pose.bones}
        if f>=44:
            if fixed is None:fixed={side:p['wrist_'+side].copy() for side in ('L','R')}
            desired={n:m.copy() for n,m in p.items()}
            for i,side in enumerate(('L','R')):
                chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
                poles[i]=_solve_leg(p,desired,chain,Vector(),poles[i],Vector((0,-1,0)),fixed[side])
                T=fixed[side]@p[chain[-1]].inverted()
                for b in arm.pose.bones[chain[-1]].children_recursive:desired[b.name]=T@p[b.name]
            p=desired
        poses.append(p)
    stabilize_arm_roll(poses);bake_world(h,poses,times)


def contact_scan():
    simple_stage()
    a=assets.hero('axe',(0,0,0),0)
    weapon=next(o for o in a['objects'] if o.type=='MESH' and 'weapon' in o.name.lower())
    for i,f in enumerate((8.8,9.2,9.5,9.7,10.0)):
        p=sample(a,'culling_blade',f)
        p=shifted(p,Vector((0,0,1.5-p['root'].translation.z)))
        bake_world(a,[p]);sc.frame_set(0);bpy.context.view_layer.update()
        ev=weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
        points=[ev.matrix_world@v.co for v in ev.data.vertices]
        tip=min(points,key=lambda p:p.y)
        print('SCAN',f,'TIP',list(tip),'GRIPS',[list(p['wrist_'+s].translation) for s in ('L','R')],flush=True)
        assets.camera((6,-8,3),(0,-1,2),40)
        sc.render.resolution_x=600;sc.render.resolution_y=600
        assets.render(OUT/f'stop_scan_{i}.png',0)


def block():
    simple_stage()
    a=assets.hero('axe',(0,3,0),0)
    r=assets.hero('rubick',(.45,0,0),180)
    N=108;hit=44
    ap=[];rp=[]
    base=sample(a,'culling_blade',0)
    start_root=sample(a,'culling_blade',4.5)['root'].translation.copy()
    contact=sample(a,'culling_blade',10.0)
    # Remove the huge game root leap while preserving the authored full-body poses.
    contact=shifted(contact,Vector((0,-1.8,1.5-contact['root'].translation.z)))
    rubick_contact=sample(r,'rubick_cast_telekinesis',1.4)
    # Place the stop against an actual evaluated blade point, not a guessed wrist gap.
    bake_world(a,[contact])
    sc.frame_set(0);bpy.context.view_layer.update()
    weapon=next(o for o in a['objects'] if o.type=='MESH' and 'weapon' in o.name.lower())
    ev=weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
    verts=[ev.matrix_world@v.co for v in ev.data.vertices]
    point=min(verts,key=lambda p:p.y)
    print('CONTACT_CANDIDATE',list(point),'AXE_ROOT',list(contact['root'].translation),flush=True)
    finger=rubick_contact['index_1_R'].translation
    print('RUBICK_FINGER',list(finger),'WRIST',list(rubick_contact['wrist_R'].translation),flush=True)
    # Move the defender along the floor to meet the blade. Height is set by the attack.
    offset=point-finger
    r_offset=Vector((offset.x,offset.y,0))
    rubick_contact=shifted(rubick_contact,r_offset)
    height_delta=finger.z-point.z
    contact=shifted(contact,Vector((0,0,height_delta)))
    point.z+=height_delta
    # Close the supporting hand on the shaft before arresting the weapon.
    grip=contact['wrist_L'].copy()
    direction=(point-contact['wrist_R'].translation).normalized()
    grip.translation=contact['wrist_R'].translation+direction*.20+Vector((.20,0,0))
    original_contact=contact
    contact=shifted(contact,Vector((0,-.32,0)))
    desired={n:m.copy() for n,m in contact.items()}
    for side,target in [('L',grip),('R',original_contact['wrist_R'])]:
        chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
        _solve_leg(contact,desired,chain,Vector(),None,Vector((1,0,0)),target)
        T=target@contact['wrist_'+side].inverted()
        for b in a['arm'].pose.bones['wrist_'+side].children_recursive:desired[b.name]=T@contact[b.name]
    contact=desired
    stop_root=contact['root'].translation.copy()
    # Restore the imported native action after evaluating the contact pose.
    for f in range(N):
        if f<19:
            src=4.5*f/19
        elif f<40:
            src=4.5+(f-19)/21*3.1
        elif f<hit:
            src=7.6+(f-40)/4*2.4
        else:
            src=10.0
        p=sample(a,'culling_blade',src)
        if f<19:
            target=p['root'].translation.copy()
        elif f<hit:
            t=(f-19)/(hit-19)
            target=start_root.lerp(stop_root,t)
            target.z+=.55*math.sin(math.pi*t)
        else:
            t=assets.smooth((f-hit)/16)
            target=stop_root+Vector((-.30*t,-1.00*t,(1.10-stop_root.z)*t))
            target.y-=.10*math.sin(min(1,(f-hit)/14)*math.pi)
        p=shifted(p,target-p['root'].translation)
        if 19<=f<hit:
            tuck=math.sin(math.pi*(f-19)/(hit-19))**2
            desired={n:m.copy() for n,m in p.items()}
            for side,amount in (('L',.75),('R',1.0)):
                chain=tuple(n+'_'+side for n in ('thigh','knee','ankle'))
                foot=p[chain[-1]].copy();foot.translation+=Vector((0,.50*tuck*amount,.30*tuck*amount))
                _solve_leg(p,desired,chain,Vector(),None,Vector((0,-1,0)),foot)
                T=foot@p[chain[-1]].inverted()
                for b in a['arm'].pose.bones[chain[-1]].children_recursive:desired[b.name]=T@p[b.name]
            p=desired
        # The chest continues toward the stopped axe before returning into support.
        if f>=hit:
            angle=math.radians(3)*math.sin(min(1,(f-hit)/18)*math.pi)
            rotate_branch(a['arm'],p,'spine1',(1,0,0),angle)
            for joint in ('spine1','spine2','spine3','neck1','head'):
                turn=base[joint].to_quaternion()@p[joint].to_quaternion().inverted()
                weight=assets.smooth((f-hit)/16)*(1 if joint=='head' else .8)
                turn=Quaternion().slerp(turn,weight)
                pivot=p[joint].translation.copy()
                T=Matrix.Translation(pivot)@turn.to_matrix().to_4x4()@Matrix.Translation(-pivot)
                for b in [a['arm'].pose.bones[joint],*a['arm'].pose.bones[joint].children_recursive]:p[b.name]=T@p[b.name]
            rotate_branch(a['arm'],p,'head',(1,0,0),math.radians(-12)*assets.smooth((f-hit)/16))
            desired={n:m.copy() for n,m in p.items()}
            final_root=stop_root+Vector((-.30,-1,1.10-stop_root.z))
            for side in ('L','R'):
                chain=tuple(n+'_'+side for n in ('thigh','knee','ankle'))
                ankle=chain[-1];goal=base[ankle].copy()
                delta=final_root-base['root'].translation
                goal.translation+=Vector((delta.x,delta.y,.015))
                foot=mixed({'foot':contact[ankle]},{'foot':goal},assets.smooth((f-hit)/16))['foot']
                _solve_leg(p,desired,chain,Vector(),None,Vector((0,-1,0)),foot)
                T=foot@p[ankle].inverted()
                for b in a['arm'].pose.bones[ankle].children_recursive:desired[b.name]=T@p[b.name]
            p=desired
        ap.append(p)
        idle=sample(r,'rubick_idle',f%59)
        if f<31:q=idle
        elif f<hit:q=mixed(idle,sample(r,'rubick_cast_telekinesis',1.4),assets.smooth((f-31)/13))
        else:q=sample(r,'rubick_cast_telekinesis',1.4)
        q=shifted(q,r_offset)
        if f>76:rotate_branch(r['arm'],q,'Head_0',(0,1,0),math.radians(-7)*assets.smooth((f-76)/14))
        rp.append(q)
    # Match both wrists to one fixed weapon transform after impact. Body momentum remains.
    fixed={side:contact['wrist_'+side].copy() for side in ('L','R')}
    poles=[None,None]
    reachable=[]
    for f in range(40,hit):
        p=ap[f];desired={n:m.copy() for n,m in p.items()}
        t=assets.smooth((f-40)/(hit-40))
        right=p['wrist_R'].copy();right.translation.y+=.32*t
        left=right@fixed['R'].inverted()@fixed['L']
        left=mixed({'hand':p['wrist_L']},{'hand':left},t)['hand']
        for i,(side,target) in enumerate((('L',left),('R',right))):
            chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
            if side=='L':
                shoulder,elbow,wrist=(p[n].translation for n in chain)
                reach=(elbow-shoulder).length+(wrist-elbow).length
                delta=target.translation-shoulder
                if delta.length>reach*.99:
                    # The free hand approaches the moving handle; contact starts at hit.
                    target.translation=shoulder+delta.normalized()*reach*.99
            poles[i]=_solve_leg(p,desired,chain,Vector(),poles[i],Vector((0,-1,0)),target)
            T=target@p['wrist_'+side].inverted()
            for b in a['arm'].pose.bones['wrist_'+side].children_recursive:desired[b.name]=T@p[b.name]
        ap[f]=desired
    # After the swing the elbows fold below the shaft, not up across the face.
    poles=[Vector((0,0,-1)),Vector((0,0,-1))]
    for f in range(hit,N):
        p=ap[f];desired={n:m.copy() for n,m in p.items()}
        for i,side in enumerate(('L','R')):
            chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
            try:
                poles[i]=_solve_leg(p,desired,chain,Vector(),poles[i],Vector((0,-1,0)),fixed[side])
            except ValueError as exc:
                b,e,w=(p[n].translation for n in chain)
                raise ValueError(f'Arm reach failed at {f}/{side}: distance={(fixed[side].translation-b).length:.4f}, length={(e-b).length+(w-e).length:.4f}, shoulder={list(b)}, target={list(fixed[side].translation)}: {exc}')
        # Hands/fingers and the weapon inherit the fixed wrist frames exactly.
        for side in ('L','R'):
            wrist='wrist_'+side
            T=fixed[side]@p[wrist].inverted()
            for b in a['arm'].pose.bones[wrist].children_recursive:desired[b.name]=T@p[b.name]
        ap[f]=desired
        reachable.append(f)
    stabilize_arm_roll(ap)
    support_feet(a,ap);bake_world(r,rp)
    # Conservative expression changes; no exaggerated morph amplitudes.
    for ob in a['objects']:
        if ob.type!='MESH' or not ob.data.shape_keys:continue
        kb=ob.data.shape_keys.key_blocks
        for f in range(N):
            surprise=assets.smooth((f-90)/15)
            for name,value in [('browLowerer',.55*(1-surprise)),('jawOpen',.16+.12*surprise),('upperLidRaiser',.22*surprise)]:
                if name in kb:kb[name].value=value;kb[name].keyframe_insert('value',frame=f)
    # The attack is staged in depth, so the moving body fills the portrait frame.
    cam=assets.camera((4.5,-7,2.3),(0,1.2,2.1),45)
    for f in range(N):
        sc.frame_set(f)
        if f<19:
            pos=(3.6,-1.6,2.8);target=ap[f]['head'].translation+Vector((0,0,-.25));lens=57
        elif f<39:
            pos=(3.4,-5,2.1);target=(0,2.2,2.2);lens=55
        elif f<68:
            pos=(4,-9,1.2);target=(-.5,-1.3,2);lens=43
        elif f<76:
            pos=(4.6,-4.8,2.9);target=point+Vector((0,.3,-.35));lens=49
        elif f<90:
            target=rp[f]['Head_0'].translation;pos=target+Vector((2,3,.0));lens=55
        else:
            target=ap[f]['head'].translation+Vector((0,0,-.05));pos=target+Vector((.35,-1.8,1));lens=38
        assets.camera(pos,target,lens)
        for key in ('location','rotation_euler'):cam.keyframe_insert(key,frame=f)
        cam.data.keyframe_insert('lens',frame=f)
    sc.frame_start=0;sc.frame_end=N-1
    pin_subframes(a)
    sc.render.resolution_x=540;sc.render.resolution_y=960
    (OUT/'staging.json').write_text(json.dumps({'frames':N,'fps':30,'contact':list(point),'root_at_contact':list(stop_root),'defender_floor_offset':list(r_offset),'held_frames':reachable},indent=2))
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'block.blend'))
    for f in (0,17,26,37,43,44,56,66,72,84,102):
        assets.render(OUT/f'block_{f:03d}.png',f)
    cam.animation_data_clear();cam.data.animation_data_clear()
    assets.camera((6,-12,4.5),(-1,-1.1,2.25),40)
    assets.render(OUT/'landing_wide.png',66)


def motion():
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'block.blend'))
    scene=bpy.context.scene
    scene.render.resolution_x=360;scene.render.resolution_y=640
    scene.cycles.samples=16
    folder=OUT/'motion';folder.mkdir(exist_ok=True)
    for f in range(scene.frame_start,scene.frame_end+1):
        scene.frame_set(f);scene.render.filepath=str(folder/f'{f:04d}.png')
        bpy.ops.render.render(write_still=True)


def look():
    """A separate lighting test; this does not approve the motion block."""
    global sc
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'block.blend'))
    sc=bpy.context.scene
    assets.sc=sc
    arm=next(o for o in sc.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='axe_root')
    for f in range(90,sc.frame_end+1):
        sc.frame_set(f)
        target=arm.matrix_world@arm.pose.bones['head'].head+Vector((0,0,-.05))
        cam=assets.camera(target+Vector((.35,-1.8,1)),target,38)
        for key in ('location','rotation_euler'):cam.keyframe_insert(key,frame=f)
        cam.data.keyframe_insert('lens',frame=f)
    for ob in list(sc.objects):
        if ob.type=='LIGHT' or ob.name=='Contact ground':bpy.data.objects.remove(ob,do_unlink=True)
    for ob in sc.objects:
        if ob.type!='MESH':continue
        for mat in ob.data.materials:
            if not mat or not mat.use_nodes:continue
            p=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
            if p:
                metal=any(x in ob.name.lower() for x in ('weapon','armor','shoulder'))
                p.inputs['Metallic'].default_value=.65 if metal else 0
                p.inputs['Roughness'].default_value=.4 if metal else .65
                p.inputs['Specular IOR Level'].default_value=.35
    import dota_map
    dota_map.TEX=str(ROOT/'_game/world')
    imported,_=assets.imported(ROOT/'_game/maps/dire_tank_base_v2.glb')
    selected=sorted([o for o in imported if o.type=='MESH' and any(x in o.name for x in ('statue001','dire_tower002','ground_rock001','river_rocks001'))],key=lambda o:o.name)
    matrices={o:o.matrix_world.copy() for o in selected}
    for ob in imported:
        if ob not in selected:bpy.data.objects.remove(ob,do_unlink=True)
    positions={'tower':[(-7.5,10,0),(-8,-12,0)],'statue':[(4.3,5,0),(-4,-8,0)],'rock':[(-3,0,0),(3.8,1,0),(-3.5,4,0),(3,-6,0)]}
    counts={k:0 for k in positions}
    rocks=[]
    for ob in selected:
        kind='tower' if 'tower' in ob.name else 'statue' if 'statue' in ob.name else 'rock'
        index=counts[kind];counts[kind]+=1
        if index>=len(positions[kind]):bpy.data.objects.remove(ob,do_unlink=True);continue
        ob.parent=None;ob.data=ob.data.copy();ob.data.transform(matrices[ob]);ob.matrix_world=Matrix.Identity(4)
        lo=Vector(tuple(min(v.co[i] for v in ob.data.vertices) for i in range(3)))
        hi=Vector(tuple(max(v.co[i] for v in ob.data.vertices) for i in range(3)))
        center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z))
        extent=max(hi-lo) if kind=='rock' else hi.z-lo.z
        factor={'tower':8,'statue':5,'rock':2.2}[kind]/max(.01,extent)
        for v in ob.data.vertices:v.co=(v.co-center)*factor
        ob.location=positions[kind][index]
        ob.location.z=terrain_height(ob.location.x,ob.location.y)
        for mat in ob.data.materials:
            if mat and mat.get('vmat'):
                data=mat['vmat'];dota_map.fix_prop(mat,data.to_dict() if hasattr(data,'to_dict') else data)
            if mat and mat.use_nodes:
                p=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
                if p:
                    for key,value in [('Metallic',0),('Roughness',.8),('Alpha',1)]:
                        for link in list(p.inputs[key].links):mat.node_tree.links.remove(link)
                        p.inputs[key].default_value=value
                for node in mat.node_tree.nodes:
                    if node.type=='TEX_IMAGE' and node.image:node.image.alpha_mode='CHANNEL_PACKED'
        if kind=='rock':rocks.append(ob)
    rng=random.Random(571)
    for i in range(35):
        if not rocks:break
        x,y=rng.uniform(-7,7),rng.uniform(-10,10)
        if -2<x<1.7 and -6<y<4:continue
        ob=rocks[i%len(rocks)].copy();sc.collection.objects.link(ob)
        ob.location=(x,y,terrain_height(x,y));ob.scale=(rng.uniform(.08,.3),)*3;ob.rotation_euler.z=rng.uniform(-math.pi,math.pi)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=241,y_subdivisions=241,size=160)
    floor=bpy.context.object;floor.name='Stone court'
    for vertex in floor.data.vertices:vertex.co.z=terrain_height(vertex.co.x,vertex.co.y)
    for face in floor.data.polygons:face.use_smooth=True
    mat=assets.flatmat('Rocky ground',(.06,.08,.11),.85)
    floor.data.materials.append(mat);nt=mat.node_tree;p=nt.nodes.get('Principled BSDF')
    external=OUT/'external'
    def texture(name,color=True):
        node=nt.nodes.new('ShaderNodeTexImage');node.image=bpy.data.images.load(str(external/name),check_existing=True)
        node.image.colorspace_settings.name='sRGB' if color else 'Non-Color';return node
    tex=texture('rocks_ground_02_col_4k.jpg')
    coords=nt.nodes.new('ShaderNodeTexCoord');mapping=nt.nodes.new('ShaderNodeMapping');mapping.inputs['Scale'].default_value=(.5,)*3
    nt.links.new(coords.outputs['Object'],mapping.inputs['Vector']);nt.links.new(mapping.outputs[0],tex.inputs[0])
    macro=texture('rocky_terrain_02_diff_4k.jpg');macro_map=nt.nodes.new('ShaderNodeMapping');macro_map.inputs['Scale'].default_value=(1/90,)*3
    nt.links.new(coords.outputs['Object'],macro_map.inputs['Vector']);nt.links.new(macro_map.outputs[0],macro.inputs[0])
    gray=nt.nodes.new('ShaderNodeRGBToBW');nt.links.new(macro.outputs['Color'],gray.inputs[0])
    value=nt.nodes.new('ShaderNodeMapRange');value.inputs['To Min'].default_value=.65;value.inputs['To Max'].default_value=1.15
    nt.links.new(gray.outputs[0],value.inputs['Value'])
    tint=nt.nodes.new('ShaderNodeMixRGB');tint.blend_type='MULTIPLY';tint.inputs[0].default_value=1
    nt.links.new(value.outputs[0],tint.inputs[2]);nt.links.new(tex.outputs['Color'],tint.inputs[1]);nt.links.new(tint.outputs[0],p.inputs['Base Color'])
    normal=texture('rocks_ground_02_nor_gl_4k.jpg',False);rough=texture('rocks_ground_02_rough_4k.jpg',False)
    for node in (normal,rough):nt.links.new(mapping.outputs[0],node.inputs[0])
    normal_map=nt.nodes.new('ShaderNodeNormalMap');normal_map.inputs['Strength'].default_value=.8
    nt.links.new(normal.outputs['Color'],normal_map.inputs['Color']);nt.links.new(normal_map.outputs[0],p.inputs['Normal']);nt.links.new(rough.outputs['Color'],p.inputs['Roughness'])
    wn=sc.world.node_tree;bg=wn.nodes.get('Background')
    env=wn.nodes.new('ShaderNodeTexEnvironment');env.image=bpy.data.images.load(str(external/'kloppenheim_06_puresky_4k.hdr'),check_existing=True)
    coord=wn.nodes.new('ShaderNodeTexCoord');mapping=wn.nodes.new('ShaderNodeMapping');mapping.inputs['Rotation'].default_value[2]=math.radians(110)
    wn.links.new(coord.outputs['Generated'],mapping.inputs['Vector']);wn.links.new(mapping.outputs[0],env.inputs['Vector']);wn.links.new(env.outputs['Color'],bg.inputs[0]);bg.inputs[1].default_value=.35
    assets.area('Cold key',(3,-5,7),(.65,.8,1),1800,3,target=(0,-1,2))
    assets.area('Warm edge',(-4,4,6),(1,.31,.07),2200,2,target=(0,-1,2))
    assets.area('Reverse fill',(1,5,5),(.3,.58,1),800,4,target=(0,-3,2))
    sun=bpy.data.lights.new('Distant daylight','SUN');sun.energy=.8;sun.angle=.12
    sun.color=(.75,.85,1);obj=bpy.data.objects.new(sun.name,sun);sc.collection.objects.link(obj);obj.rotation_euler=(.5,-.4,-.6)
    bpy.ops.mesh.primitive_cube_add(size=2,location=(0,0,15))
    mist=bpy.context.object;mist.name='Distant air';mist.scale=(75,75,20)
    mat=bpy.data.materials.new('Thin aerial perspective');mat.use_nodes=True
    nt=mat.node_tree;nt.nodes.clear();volume=nt.nodes.new('ShaderNodeVolumePrincipled')
    volume.inputs['Density'].default_value=.002;volume.inputs['Color'].default_value=(.4,.55,.7,1)
    nt.links.new(volume.outputs['Volume'],nt.nodes.new('ShaderNodeOutputMaterial').inputs['Volume']);mist.data.materials.append(mat)
    sc.cycles.samples=48
    sc.view_settings.look='AgX - Medium High Contrast'
    bg.inputs[1].default_value=.18
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'look.blend'))
    for f in (0,26,44,66,72,84,102):assets.render(OUT/f'look_{f:03d}.png',f)


def effects():
    """Local weapon charge and one contact burst, with no full-frame flash."""
    global sc
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'look.blend'))
    sc=bpy.context.scene;assets.sc=sc
    arm=next(o for o in sc.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='axe_root')
    rubick=next(o for o in sc.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='rubick_root')
    weapon=next(o for o in sc.objects if o.type=='MESH' and 'axe_weapon' in o.name)
    point=Vector(json.loads((OUT/'staging.json').read_text())['contact'])
    sc.frame_set(44);bpy.context.view_layer.update()
    bone=arm.matrix_world@arm.pose.bones['axe_1'].matrix
    wrist=arm.matrix_world@arm.pose.bones['wrist_R'].head
    evaluated=weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
    vertices=[evaluated.matrix_world@v.co for v in evaluated.data.vertices]
    axis=(point-wrist).normalized();extent=max((v-wrist).dot(axis) for v in vertices)
    blade=[v for v in vertices if (v-wrist).dot(axis)>extent-.85]
    if not blade:raise ValueError('No blade vertices for local charge')
    local=[bone.inverted()@v for v in blade]
    center=sum(local,Vector())/len(local)
    poses=[]
    for f in range(sc.frame_end+1):
        sc.frame_set(f);poses.append(arm.matrix_world@arm.pose.bones['axe_1'].matrix)
    rng=random.Random(83)
    for event,start in enumerate((8,14,20,26,32,38,42,48,56,64,92,100)):
        for strand in range(2):
            a=rng.choice(local);c=max(local,key=lambda p:(p-a).length)
            points=[]
            for j in range(11):
                t=j/10
                jitter=Vector((rng.uniform(-.07,.07),rng.uniform(-.07,.07),rng.uniform(-.07,.07)))
                points.append(a.lerp(c,t)+jitter*math.sin(math.pi*t))
            ob=assets.beam(f'Charge {event} {strand}',points,(.12,.46,1),.017)
            for j,p in enumerate(ob.data.splines[0].points):p.radius=.15+.85*math.sin(math.pi*j/10)
            follow=ob.constraints.new('COPY_TRANSFORMS');follow.target=arm;follow.subtarget='axe_1'
            follow.owner_space='WORLD';follow.target_space='WORLD'
            for f,hidden in ((0,True),(start-1,True),(start,False),(start+3,False),(start+4,True),(sc.frame_end,True)):
                ob.hide_render=hidden;ob.keyframe_insert('hide_render',frame=f)
    blue=bpy.data.lights.new('Weapon charge light','POINT');blue.color=(.08,.35,1);blue.shadow_soft_size=.18
    ob=bpy.data.objects.new(blue.name,blue);sc.collection.objects.link(ob)
    for f,matrix in enumerate(poses):ob.location=matrix@center;ob.keyframe_insert('location',frame=f)
    for f,power in ((0,0),(8,0),(16,35),(30,80),(43,140),(46,45),(70,25),(107,25)):
        blue.energy=power;blue.keyframe_insert('energy',frame=f)
    green=bpy.data.lights.new('Arrest light','POINT');green.color=(.16,1,.2);green.shadow_soft_size=.2
    ob=bpy.data.objects.new(green.name,green);sc.collection.objects.link(ob);ob.location=point+Vector((0,.05,.05))
    for f,power in ((0,0),(43,0),(44,100),(46,160),(51,35),(67,20),(107,20)):
        green.energy=power;green.keyframe_insert('energy',frame=f)
    for i in range(14):
        ob=assets.beam(f'Contact spark {i}',[(0,0,0),(0,0,.09)],(.25,1,.4),.008)
        ob.data.splines[0].points[-1].radius=.05
        velocity=Vector((rng.uniform(-1,1),rng.uniform(-1,1),rng.uniform(.2,1.6)))*rng.uniform(1,2)
        start=44+i%3;end=start+rng.randint(8,14)
        for f in range(start,end+1):
            t=(f-start)/30;v=velocity+Vector((0,0,-4*t))
            ob.location=point+velocity*t+Vector((0,0,-2*t*t))
            ob.rotation_euler=v.to_track_quat('Z','Y').to_euler();ob.scale=(max(.02,1-(f-start)/(end-start)),)*3
            for key in ('location','rotation_euler','scale'):ob.keyframe_insert(key,frame=f)
        for f,hidden in ((0,True),(start-1,True),(start,False),(end,False),(end+1,True),(107,True)):
            ob.hide_render=hidden;ob.keyframe_insert('hide_render',frame=f)
    cam=sc.camera;cam.data.dof.use_dof=True
    for f in range(sc.frame_end+1):
        sc.frame_set(f)
        if f<39 or f>=90:target=arm.matrix_world@arm.pose.bones['head'].head
        elif f<76:target=point
        else:target=rubick.matrix_world@rubick.pose.bones['Head_0'].head
        cam.data.dof.focus_distance=(cam.location-target).length
        cam.data.dof.aperture_fstop=8 if 39<=f<68 else 4
        for key in ('focus_distance','aperture_fstop'):cam.data.dof.keyframe_insert(key,frame=f)
    # Hold each camera sample through the shutter interval, including at cuts.
    for owner in (cam,cam.data):
        if not owner.animation_data or not owner.animation_data.action:continue
        for layer in owner.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:key.interpolation='CONSTANT'
    sc.render.use_motion_blur=False
    for settings in (sc.cycles,sc.render):
        if hasattr(settings,'motion_blur_position'):
            settings.motion_blur_position='START';sc.render.use_motion_blur=True;break
    sc.render.motion_blur_shutter=.3
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'effects.blend'))
    for f in (42,46):assets.render(OUT/f'effects_{f:03d}.png',f)


def map_probe():
    """Test the coherent native location before committing to a film-set layout."""
    global sc
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'look.blend'))
    sc=bpy.context.scene;assets.sc=sc
    for ob in list(sc.objects):
        if ob.type!='MESH' or ob.name=='Distant air':continue
        parents=[];parent=ob.parent
        while parent:parents.append(parent.name);parent=parent.parent
        if not any(name in ('axe_root','rubick_root') for name in parents):bpy.data.objects.remove(ob,do_unlink=True)
    import dota_map
    obs=dota_map.load(str(ROOT/'_game/maps/dire_tank_base_v2.glb'),str(ROOT/'_game/world'),ground_z=6.3)
    origin=Vector((4999.998047/39.37,-5527.997070/39.37,248/39.37))
    for ob in obs:
        if not ob.parent:ob.location-=origin
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'map_probe.blend'))
    for f in (26,44,66,84,102):assets.render(OUT/f'map_probe_{f:03d}.png',f)


def draft():
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'effects.blend'))
    scene=bpy.context.scene
    folder=OUT/'frames';folder.mkdir(exist_ok=True)
    manifest=folder/'manifest.json'
    manifest.unlink(missing_ok=True)
    hashes=[]
    source_frames=list(range(scene.frame_start,scene.frame_end+1))
    for f in source_frames:
        scene.frame_set(f);scene.render.filepath=str(folder/f'{f:04d}.png')
        bpy.ops.render.render(write_still=True)
        hashes.append(hashlib.sha256(Path(scene.render.filepath).read_bytes()).hexdigest())
    manifest.write_text(json.dumps({'blend_sha256':hashlib.sha256((OUT/'effects.blend').read_bytes()).hexdigest(),
        'frames':len(hashes),'fps':scene.render.fps,'source_frames':source_frames,'frame_sha256':hashes},indent=2))


def repair_roll():
    """Update this production's cached scenes without reimporting or rendering."""
    global sc
    for name in ('block.blend','look.blend','effects.blend'):
        bpy.ops.wm.open_mainfile(filepath=str(OUT/name));sc=bpy.context.scene;assets.sc=sc
        arm=next(o for o in sc.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='axe_root')
        poses=[]
        for f in range(sc.frame_end+1):
            sc.frame_set(f);bpy.context.view_layer.update()
            poses.append({b.name:arm.matrix_world@b.matrix for b in arm.pose.bones})
        stabilize_arm_roll(poses);bake_world({'arm':arm},poses);pin_subframes({'arm':arm})
        for ob in sc.objects:
            if ob.type=='CURVE' and ob.name.startswith('Charge ') and not ob.constraints:
                follow=ob.constraints.new('COPY_TRANSFORMS');follow.target=arm;follow.subtarget='axe_1'
                follow.owner_space='WORLD';follow.target_space='WORLD'
        bpy.ops.wm.save_as_mainfile(filepath=str(OUT/name))


if MODE=='inspect':
    inspect()
elif MODE=='block':
    block()
elif MODE=='block_motion':
    block()
    motion()
elif MODE=='contact_scan':
    contact_scan()
elif MODE=='motion':
    motion()
elif MODE=='look':
    look()
elif MODE=='probe_v2':
    block()
    look()
elif MODE=='effects':
    effects()
elif MODE=='draft':
    draft()
elif MODE=='map_probe':
    map_probe()
elif MODE=='repair_roll':
    repair_roll()
