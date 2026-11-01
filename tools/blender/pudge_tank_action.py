"""Acting and localized effects over the reviewed tank staging, in a new revision."""
import json
import math
import os
import random
import sys
from pathlib import Path
import bpy
from mathutils import Matrix,Vector

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/pudge_tank/action_v3'
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools/blender'))
from contact_reaction import _basis,_solve_leg
from face import unfold

s=bpy.context.scene
hero=bpy.data.objects['pudge_root']
arm=max((o for o in hero.children_recursive if o.type=='ARMATURE'),key=lambda o:len(o.pose.bones))
weapon=bpy.data.objects['heavy_launcher']
tank=bpy.data.objects['detailed_tank']
head=next(o for o in hero.children_recursive if o.type=='MESH' and o.data.shape_keys)
legs=[(f'thigh_{side}',f'knee_{side}',f'ankle_{side}') for side in ('L','R')]

def smooth(x):
    x=min(1.,max(0.,x));return x*x*(3-2*x)

def curve(t,points):
    for (a,x),(b,y) in zip(points,points[1:]):
        if t<=b:
            return x+(y-x)*smooth((t-a)/(b-a))
    return points[-1][1]

def rotate(desired,name,axis,degrees):
    bone=arm.pose.bones[name]
    pivot=desired[name].translation
    transform=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(degrees),4,axis)@Matrix.Translation(-pivot)
    for child in (bone,*bone.children_recursive):
        desired[child.name]=transform@desired[child.name]

# Snapshot the original action first: newly inserted channels must not contaminate
# later source samples. The torso carries both grips through the same transform.
source=[]
for f in range(300):
    s.frame_set(f)
    world=arm.matrix_world.copy()
    source.append((world,{b.name:world@b.matrix for b in arm.pose.bones}))
s.frame_set(0)
arm.animation_data_clear()
names={'root','spine1','clavicle_L','clavicle_R','neck1','head',*(n for leg in legs for n in leg)}
ordered=[b for b in arm.pose.bones if b.name in names]
acting=[]
face_track={n:[] for n in ('jawOpen','browLowerer','lipCornerPuller','lowerLipsPart')}
for f,(world,base) in enumerate(source):
    s.frame_set(f);t=f/30
    d={n:m.copy() for n,m in base.items()}
    prep=curve(t,[(0,0),(1.25,0),(1.72,1),(1.88,0),(10,0)])
    landing=curve(t,[(0,0),(2.75,0),(2.89,1),(3.1,-.18),(3.4,0),(10,0)])
    tuck=math.sin(math.pi*(t-1.8))**2 if 1.8<t<2.8 else 0
    drive=math.sin(math.pi*(t-3.6)/2.6) if 3.6<t<6.2 else 0
    kick=math.sin(math.pi*(t-6.6)/.28)*math.exp(-(t-6.6)*4) if 6.6<t<6.88 else 0
    drop=Vector((0,0,-.13*prep-.11*landing))
    for m in d.values():m.translation+=drop
    for i,leg in enumerate(legs):
        target=base[leg[2]].copy()
        target.translation+=Vector((0,-.06*tuck,(.15 if i==0 else .10)*tuck))
        _solve_leg(base,d,leg,drop,None,Vector((0,-1,0)),target)
    tilt=curve(t,[(0,-3),(.32,-8),(.72,2),(1.25,0),(1.73,12),(2.1,-8),(2.55,3),(2.8,0),(3.05,6),(3.4,0),(9,0),(9.35,-5),(9.8,0)])
    tilt+=3*landing-3*drive+4*kick
    turn=curve(t,[(0,6),(.55,-10),(1.15,0),(1.8,-5),(2.45,5),(2.8,0),(9,0),(9.45,8),(10,8)])
    rotate(d,'spine1','X',tilt)
    rotate(d,'spine1','Z',turn)
    # Both arms rotate as one supported weapon gesture, preserving the foregrip.
    lift=curve(t,[(0,0),(.45,-11),(.85,-7),(1.3,0),(1.75,0),(2.15,-7),(2.7,0),(3.1,-3),(3.5,0),(6.45,0),(6.72,-4),(7,0),(9,0),(9.5,-12),(10,-10)])
    pivot=(d['clavicle_L'].translation+d['clavicle_R'].translation)*.5
    tr=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(lift),4,'X')@Matrix.Translation(-pivot)
    for side in ('L','R'):
        bone=arm.pose.bones['clavicle_'+side]
        for child in (bone,*bone.children_recursive):d[child.name]=tr@d[child.name]
    glance=curve(t,[(0,-7),(.38,12),(.8,17),(1.3,0),(1.8,-8),(2.6,0),(3.6,0),(4.3,-9),(5.5,0),(9,0),(9.45,-12),(10,-12)])
    rotate(d,'neck1','Z',glance)
    rotate(d,'head','X',-tilt*.4+2*math.sin(t*3.1)-3*kick)
    inverse=world.inverted()
    for b in ordered:
        b.rotation_mode='QUATERNION'
        b.matrix_basis=_basis(b,inverse@d[b.name],inverse@d[b.parent.name] if b.parent else None)
        for channel in ('location','rotation_quaternion','scale'):b.keyframe_insert(channel,frame=f)
    face_track['jawOpen'].append(.08+.13*prep+.10*landing+.10*smooth((t-9.1)/.35))
    face_track['browLowerer'].append(.12+.18*prep+.12*drive)
    face_track['lipCornerPuller'].append(.10+.24*smooth((t-9.05)/.4))
    face_track['lowerLipsPart'].append(.16+.1*prep)
    acting.append({'frame':f,'body_pitch':tilt,'body_turn':turn,'arm_lift':lift,'head_turn':glance,'tuck':tuck})
unfold(head,face_track,300,30,'pudge')
head.data.shape_keys.animation_data_clear()
for name,values in face_track.items():
    key=head.data.shape_keys.key_blocks[name]
    for f,value in enumerate(values):
        key.value=value;key.keyframe_insert('value',frame=f)

def cloud_material(name,color,density,emission=0):
    mat=bpy.data.materials.new(name);mat.use_nodes=True
    nt=mat.node_tree;nt.nodes.clear()
    out=nt.nodes.new('ShaderNodeOutputMaterial');vol=nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value=(*color,1)
    tex=nt.nodes.new('ShaderNodeTexCoord')
    noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=5;noise.inputs['Detail'].default_value=3
    nt.links.new(tex.outputs['Generated'],noise.inputs['Vector'])
    center=nt.nodes.new('ShaderNodeVectorMath');center.operation='DISTANCE';center.inputs[1].default_value=(.5,.5,.5)
    nt.links.new(tex.outputs['Generated'],center.inputs[0])
    fall=nt.nodes.new('ShaderNodeMapRange');fall.clamp=True
    fall.inputs['From Min'].default_value=.18;fall.inputs['From Max'].default_value=.5
    fall.inputs['To Min'].default_value=1;fall.inputs['To Max'].default_value=0
    nt.links.new(center.outputs['Value'],fall.inputs['Value'])
    mult=nt.nodes.new('ShaderNodeMath');mult.operation='MULTIPLY'
    nt.links.new(fall.outputs[0],mult.inputs[0]);nt.links.new(noise.outputs['Fac'],mult.inputs[1])
    gain=nt.nodes.new('ShaderNodeMath');gain.operation='MULTIPLY';gain.inputs[1].default_value=density
    nt.links.new(mult.outputs[0],gain.inputs[0]);nt.links.new(gain.outputs[0],vol.inputs['Density'])
    if emission:
        ramp=nt.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color=(.35,.008,.001,1)
        ramp.color_ramp.elements[1].color=(1,.68,.12,1)
        nt.links.new(noise.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs[0],vol.inputs['Emission Color'])
        power=nt.nodes.new('ShaderNodeMath');power.operation='MULTIPLY';power.inputs[1].default_value=emission
        nt.links.new(mult.outputs[0],power.inputs[0]);nt.links.new(power.outputs[0],vol.inputs['Emission Strength'])
    nt.links.new(vol.outputs[0],out.inputs['Volume'])
    return mat

fire=cloud_material('action hot flame',(.65,.06,.005),1.8,7)
smoke=cloud_material('action charcoal smoke',(.07,.075,.085),3.5)
dust=cloud_material('action track dust',(.21,.15,.08),1.5)
rng=random.Random(1918)
for o in list(s.objects):
    if o.name.startswith('blast volume') or o.name=='muzzle fire':
        o.hide_render=True;o.animation_data_clear()

effects=[]
def cloud(name,mat,start,life,origin,velocity,radius):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1)
    o=bpy.context.object;o.name=name;o.data.materials.append(mat)
    for f in range(300):
        dt=f/30-start;u=max(0,min(1,dt/life))
        o.hide_render=dt<0 or dt>life
        gain=smooth(u/.2)*(1-smooth((u-.55)/.45))
        o.scale=tuple(max(.001,r*(.5+u)*gain) for r in radius)
        o.location=Vector(origin)+Vector(velocity)*max(0,dt)
        for prop in ('hide_render','location','scale'):o.keyframe_insert(prop,frame=f)
    effects.append(name)
    return o

for i in range(11):
    x,y=rng.uniform(-2.3,2.3),rng.uniform(-1.5,1.5)
    cloud(f'action flame {i}',fire,6.9+i*.013,.72,(-83.5+x,62+y,5.3+rng.uniform(0,3)),(x*.4,y*.3,1.8),(1.15,.85,2.1))
for i in range(7):
    cloud(f'action smoke {i}',smoke,7.05+i*.05,2.6,(-83.5+rng.uniform(-2,2),62+rng.uniform(-1,1),5+rng.uniform(0,3)),(.4,0,2.0),(2.6,2.1,3.0))
for i in range(20):
    at=3.65+i*.12;s.frame_set(round(at*30))
    origin=tank.matrix_world.translation+Vector(((-1 if i%2 else 1)*2.1,3.5,.12))
    cloud(f'action tread dust {i}',dust,at,.78,origin,((-.35 if i%2 else .35),.4,.35),(.65,.9,.45))
s.frame_set(198)
muzzle=tank.matrix_world@Vector((0,-7.4,2.52))
cloud('action muzzle flame',fire,6.6,.13,muzzle,(0,-4,0),(.55,1.3,.55))
cloud('action muzzle smoke',smoke,6.68,.55,muzzle,(0,-1,.35),(.7,.95,.7))

ember=bpy.data.materials.new('action glowing embers');ember.use_nodes=True
pr=ember.node_tree.nodes.get('Principled BSDF');pr.inputs['Base Color'].default_value=(1,.15,.01,1)
pr.inputs['Emission Color'].default_value=(1,.24,.015,1);pr.inputs['Emission Strength'].default_value=9
for i in range(55):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=1)
    o=bpy.context.object;o.name=f'action ember {i}';o.data.materials.append(ember)
    at=6.91+rng.random()*.15;life=rng.uniform(.55,1.4)
    initial=Vector((-83.5+rng.uniform(-1,1),62+rng.uniform(-1,1),6+rng.uniform(0,3)))
    angle=rng.uniform(0,math.tau);speed=rng.uniform(3,8)
    velocity=Vector((math.cos(angle)*speed,math.sin(angle)*speed,rng.uniform(2,6)))
    for f in range(300):
        dt=max(0,f/30-at);v=velocity+Vector((0,0,-6*dt))
        o.location=initial+velocity*dt+Vector((0,0,-3*dt*dt))
        o.rotation_euler=v.to_track_quat('Z','Y').to_euler()
        o.scale=(.015,.015,max(.03,v.length*.025))
        o.hide_render=f/30<at or dt>life or o.location.z<3.3
        for prop in ('location','rotation_euler','scale','hide_render'):o.keyframe_insert(prop,frame=f)

# Light belongs to the local explosion, never a full-screen exposure flash.
for name,location,start,power in [('action blast light',(-83.5,62,7),6.9,900),('action cannon light',muzzle,6.6,250)]:
    light=bpy.data.lights.new(name,'POINT');light.color=(1,.29,.045);light.shadow_soft_size=2
    ob=bpy.data.objects.new(name,light);s.collection.objects.link(ob);ob.location=location
    for f in range(300):
        dt=f/30-start;light.energy=power*max(0,1-dt/.42) if 0<=dt<.42 else 0
        light.keyframe_insert('energy',frame=f)

# Leave room for the preparation pose's feet as well as the airborne head.
for f in (39,107):
    s.frame_set(f)
    s.camera.rotation_euler=(Vector((-81.7,87.8,5.95))-s.camera.location).to_track_quat('-Z','Y').to_euler()
    s.camera.data.lens=24
    s.camera.keyframe_insert('rotation_euler',frame=f)
    s.camera.data.keyframe_insert('lens',frame=f)
for f in (108,140):
    s.frame_set(f)
    s.camera.location=(-79.2,81,9)
    target=Vector((-83.4,86.1,7.4))
    s.camera.rotation_euler=(target-s.camera.location).to_track_quat('-Z','Y').to_euler()
    s.camera.data.lens=26
    s.camera.data.dof.focus_distance=(target-s.camera.location).length
    s.camera.keyframe_insert('location',frame=f);s.camera.keyframe_insert('rotation_euler',frame=f)
    s.camera.data.keyframe_insert('lens',frame=f);s.camera.data.keyframe_insert('dof.focus_distance',frame=f)
s.frame_set(179)
for prop in ('location','rotation_euler'):s.camera.keyframe_insert(prop,frame=141)
for prop in ('lens','dof.focus_distance'):s.camera.data.keyframe_insert(prop,frame=141)
for owner in (s.camera,s.camera.data):
    for layer in owner.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points:key.interpolation='CONSTANT'
s.frame_set(0)
s.eevee.taa_render_samples=64
s.render.filepath=str(OUT/'final_layers/f#####')
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'layers.blend'),compress=True)
(OUT/'action.json').write_text(json.dumps({'acting':acting,'clouds':effects,'embers':55,
    'limits':['Staging retained; localized volume effects and additive acting require visual and contact review.']},indent=2),encoding='utf-8')
(OUT/'build.json').write_text(json.dumps({'frames':300,'fps':30,
    'cuts':[0,39,108,141,180,198,207,270,300],
    'plate_sources':[0,1,6,2,3,4,5,6]},indent=2),encoding='utf-8')
for f in (16,50,66,88,135,199,215,286):
    s.frame_set(f);s.render.filepath=str(OUT/f'probe_{f:05d}.png');bpy.ops.render.render(write_still=True)
if os.environ.get('PT_RENDER_ACTION'):
    s.render.filepath=str(OUT/'final_layers/f#####');bpy.ops.render.render(animation=True)
