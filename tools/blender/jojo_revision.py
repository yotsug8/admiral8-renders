"""Revision 2: muscular original Pudge, spoken facial acting and stair ascent.

Run against the preserved first draft. Original scene/media remain untouched.
"""
import bpy
import json
import math
import sys
import wave
from pathlib import Path
from mathutils import Vector, Matrix, Quaternion
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'out/dota-jojo/v2'
OUT.mkdir(parents=True,exist_ok=True)
TMP=Path('D:/Admiral8-temp/dota-jojo')
s=bpy.context.scene
s.frame_set(1)
sys.path.insert(0,str(ROOT/'tools/blender'))
from face import _letter_marks


def actor(root):
    obs=list(root.children_recursive)
    arm=max((o for o in obs if o.type=='ARMATURE'),key=lambda o:len(o.pose.bones))
    return dict(root=root,obs=obs,arm=arm,
                base={b.name:b.matrix_basis.copy() for b in arm.pose.bones},
                origin=root.location.copy())


p=actor(bpy.data.objects['PUDGE_DOPPIO'])
n=actor(bpy.data.objects['SNIPER_POLNAREFF'])
old=bpy.data.objects['PUDGE_DIAVOLO']
for o in [old,*old.children_recursive]:
    o.animation_data_clear()
    o.hide_render=True
    o.hide_set(True)

# Independent copy of the recognizable base hero, including skinning and FACS.
mapping={}
for o in [p['root'],*p['obs']]:
    q=o.copy()
    if o.data is not None:q.data=o.data.copy()
    q.animation_data_clear()
    q.name='MUSCULAR / '+o.name
    s.collection.objects.link(q)
    mapping[o]=q
for src,q in mapping.items():
    q.parent=mapping.get(src.parent,src.parent)
    for mod in q.modifiers:
        if mod.type=='ARMATURE':mod.object=mapping.get(mod.object,mod.object)
    if q.type=='ARMATURE':
        for bone in q.pose.bones:
            for c in bone.constraints:
                if hasattr(c,'target'):c.target=mapping.get(c.target,c.target)
    if q.type=='MESH' and q.data.shape_keys:
        q.data.shape_keys.animation_data_clear()
        for k in q.data.shape_keys.key_blocks:k.value=0
a=actor(mapping[p['root']])
a['root'].name='PUDGE_MUSCULAR'
a['root'].location.x=2.0
a['root'].scale*=1.08
a['origin']=a['root'].location.copy()
for act in [p,a,n]:
    act['root'].animation_data_clear()
    act['arm'].animation_data_clear()
    for o in act['obs']:
        o.animation_data_clear()
        if o.type=='MESH' and o.data.shape_keys:o.data.shape_keys.animation_data_clear()

# Sculpt the existing skinned surface, not floating spheres over the body.
arm=a['arm']
for o in a['obs']:
    if o.type!='MESH' or 'head' in o.name or 'hair' in o.name:continue
    transform=arm.matrix_world.inverted()@o.matrix_world
    inverse=transform.inverted()
    for v in o.data.vertices:
        q=transform@v.co
        original=q.copy()
        weights={o.vertex_groups[g.group].name:g.weight for g in v.groups}
        wrist=max(weights.get('wrist_L',0),weights.get('wrist_R',0))
        for side in 'LR':
            start=arm.data.bones['bicep_'+side].head_local
            end=arm.data.bones['elbow_'+side].head_local
            axis=end-start
            t=max(0,min(1,(original-start).dot(axis)/axis.length_squared))
            center=start+axis*t
            w=weights.get('bicep_'+side,0)
            q+=(original-center)*(1.05*w*(.55+.45*math.sin(math.pi*t)))
            start=end
            end=arm.data.bones['wrist_'+side].head_local
            axis=end-start
            t=max(0,min(1,(original-start).dot(axis)/axis.length_squared))
            center=start+axis*t
            q+=(original-center)*(.38*weights.get('elbow_'+side,0)*math.sin(math.pi*t))
        waist=math.exp(-((q.z-2.15)/.62)**2)
        chest=math.exp(-((q.z-3.35)/.55)**2)
        q.x*=1+(1-wrist)*(.28*chest-.30*waist)
        q.y=.22+(q.y-.22)*(1-.38*waist*(1-wrist))
        # Paired chest volumes, limited to the torso in front of its spine.
        if abs(original.x)<1.1 and original.y<.1:
            pec=math.exp(-((abs(original.x)-.60)/.45)**2-((original.z-3.22)/.36)**2)
            q.y-=.25*pec
        v.co=inverse@q
    for poly in o.data.polygons:poly.use_smooth=True
    if any(x in o.name for x in ('upper_body','leftarm_model','lower_body')):
        mod=o.modifiers.new('Sculpt surface refinement','SUBSURF')
        mod.levels=1
        mod.render_levels=1


def aim(o,target):
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()


rock=bpy.data.materials['Dark weathered masonry']
coords=rock.node_tree.nodes.new('ShaderNodeTexCoord')
for noise in [node for node in rock.node_tree.nodes if node.type=='TEX_NOISE']:
    rock.node_tree.links.new(coords.outputs['Object'],noise.inputs['Vector'])


def block(name,loc,size):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
    o=bpy.context.object;o.name=name;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(rock)
    b=o.modifiers.new('Worn stone edges','BEVEL');b.width=.035;b.segments=3
    return o


# A continuous flight ending at Polnareff's landing, with solid risers.
STEP_START=-2.2
STEP_RUN=.65
STEP_RISE=.20
for i in range(6):
    y=STEP_START-(i+.5)*STEP_RUN
    h=(i+1)*STEP_RISE
    block('STAIR tread %02d'%i,(0,y,h/2-.02),(11,STEP_RUN+.025,h+.04))
block('Upper landing',(0,-8, .58),(13,3.8,1.24))
for x in [-5.65,5.65]:
    for i in range(6):
        block('Stair side masonry',(x,STEP_START-(i+.5)*STEP_RUN,(i+1)*STEP_RISE/2),(.4,STEP_RUN,(i+1)*STEP_RISE+.12))
column=bpy.data.objects['DOTA_RUIN_COLUMN']
block('Column capital',(0,-1.65,5.72),(1.9,1.9,.26))
block('Continuous architrave',(0,-1.65,6.0),(14,1.9,.55))
block('Ceiling slab',(0,-.3,6.45),(15,8,.4))
for x in [-6,6]:
    block('Outer structural pier',(x,-1.65,2.8),(1.3,1.5,5.6))
    block('Outer pier capital',(x,-1.65,5.72),(1.9,1.9,.26))

n['origin'].z+=1.2
n['root'].location=n['origin']
# Keep natural skin colour; the reference's violet costume is not a skin brief.
for name,color,energy in [('Moon key',(1,.84,.67),800),('Violet rim',(.35,.5,.75),500),
                          ('Face fill',(.75,.82,1),220),('Sniper key',(1,.86,.73),330)]:
    light=bpy.data.objects[name];light.data.color=color;light.data.energy=energy
bpy.data.objects['Sniper key'].location.z+=1.2
aim(bpy.data.objects['Sniper key'],(1,-6.5,2.7))


def camera(name,first,last,target0,target1,lens,start,end):
    o=bpy.data.objects[name];o.animation_data_clear();o.data.lens=lens
    for frame,pos,target in [(start,first,target0),(end,last,target1)]:
        o.location=pos;aim(o,target)
        o.keyframe_insert('location',frame=frame);o.keyframe_insert('rotation_euler',frame=frame)


camera('01_Shadow_identity',(-3,-6,2.6),(-2.7,-5.6,2.6),(-1.65,-.4,2.25),(-1.65,-.4,2.25),62,1,90)
camera('02_Time_erasure',(0,-11.6,5),(0,-11.2,4.9),(.6,-.5,2.6),(.6,-.5,2.6),40,91,222)
for f,lens in [(91,30),(155,40),(222,40)]:
    bpy.data.cameras['02_Time_erasure'].lens=lens
    bpy.data.cameras['02_Time_erasure'].keyframe_insert('lens',frame=f)
camera('03_Diavolo_glimpse',(2.4,-3.7,2.7),(2.4,-3.7,2.7),(2.2,-.5,2.5),(2.2,-.5,2.5),85,223,244)
camera('04_Polnareff_reaction',(.3,-3.7,3.15),(.4,-4,3.14),(1,-6.7,2.93),(1,-6.7,2.93),72,245,315)
camera('05_Column_reveal',(-2,-7.8,3.4),(3.3,-9.2,3.6),(2,0,1.8),(2,-3.1,2.15),43,316,407)
camera('06_Diavolo_eye',(2.3,-6.1,3.0),(2.3,-6.1,3.0),(2.2,-3.8,2.9),(2.2,-3.8,2.9),100,408,452)
camera('07_Diavolo_portrait',(2.7,-7.6,3.0),(2.5,-7.2,2.9),(2.2,-3.7,2.65),(2.2,-3.7,2.65),65,453,504)


def ease(t):
    t=max(0,min(1,t));return t*t*(3-2*t)


def position(act,name):
    return (act['arm'].matrix_world@act['arm'].pose.bones[name].matrix).translation.copy()


def rotate(act,name,q):
    arm=act['arm'];b=arm.pose.bones[name];m=arm.matrix_world@b.matrix;p0=m.translation
    b.matrix=arm.matrix_world.inverted()@Matrix.Translation(p0)@q.to_matrix().to_4x4()@Matrix.Translation(-p0)@m
    bpy.context.view_layer.update()


def leg(act,side,target):
    upper,middle,end=['thigh_'+side,'knee_'+side,'ankle_'+side]
    p0,e,w=[position(act,b) for b in (upper,middle,end)]
    u,v=e-p0,w-e;ray=target-p0;d=min(ray.length,(u.length+v.length)*.985)
    forward=ray.normalized();pole=Vector((0,-1,0));pole=(pole-forward*pole.dot(forward)).normalized()
    x=(u.length_squared-v.length_squared+d*d)/(2*d)
    elbow=p0+forward*x+pole*math.sqrt(max(0,u.length_squared-x*x))
    rotate(act,upper,u.rotation_difference(elbow-p0))
    rotate(act,middle,(position(act,end)-position(act,middle)).rotation_difference(target-position(act,middle)))


def ground(y):
    if y>STEP_START:return 0
    return min(6,1+int((STEP_START-y)/STEP_RUN))*STEP_RISE


def travel(side,f):
    spans=[(320,345,0,1.6),(369,394,1.6,3.3)] if side=='R' else [(344,369,0,2.4),(394,417,2.4,3.3)]
    for start,end,src,dst in spans:
        if f<start:return src,0,src,dst,0
        if f<=end:
            t=(f-start)/(end-start)
            return src+(dst-src)*ease(t),math.sin(math.pi*t),src,dst,ease(t)
    return 3.3,0,3.3,3.3,1


bpy.context.view_layer.update()
feet={side:(arm.matrix_world@arm.pose.bones['ankle_'+side].matrix).copy() for side in 'LR'}

# Word-timed phonetic shapes, gated by the voice band, not a sine-wave mouth.
speech=json.loads((TMP/'speech.json').read_text(encoding='utf-8'))
marks=[]
for seg in speech['segments']:
    for word in seg['words']:
        marks.extend(_letter_marks(word['text'],word['start'],word['end']))
with wave.open(str(TMP/'reference.wav'),'rb') as wav:
    sr=wav.getframerate();sound=np.frombuffer(wav.readframes(wav.getnframes()),dtype=np.int16).astype(float)/32768
env=[]
for f in range(504):
    sample=sound[int(f*sr/30):int((f+1)*sr/30)]
    env.append(float(np.sqrt(np.mean(np.diff(sample)**2))) if len(sample)>1 else 0)
ceiling=float(np.percentile(env,90))


def face_values(f,act):
    t=(f-1)/30
    if act is n:
        r=ease((f-246)/12)-.4*ease((f-280)/30)
        return {'jawOpen':.28*r,'innerBrowRaiser':.4*r,'upperLidRaiser':.7*r}
    speaking=any(seg['start']-.02<=t<=seg['end']+.04 for seg in speech['segments'])
    result={'browLowerer':.45 if act is a else .3,'squint':.18 if act is a else .08,'jawOpen':.035}
    if speaking:
        near=sorted(marks,key=lambda item:abs(item[0]-t))[:2]
        weights=[math.exp(-((tt-t)/.07)**2) for tt,_ in near]
        total=sum(weights)
        if total>1e-6:
            amplitude=min(1,max(.35,env[f-1]/max(ceiling,1e-5)))
            for weight,(_,values) in zip(weights,near):
                for name,val in values.items():result[name]=result.get(name,0)+val*weight/total*amplitude
            result['jawOpen']=min(.55,result['jawOpen']*1.22)
    blink=max(math.exp(-((f-k)/2.1)**2) for k in [69,198,325,442])
    result['eyeClosed']=blink*.92
    result['eyeDown']=.1 if act is a else .18
    return result


contact=[]
for f in range(1,505):
    s.frame_set(f)
    for act in [p,a,n]:
        act['root'].location=act['origin']
        for b in act['arm'].pose.bones:b.matrix_basis=act['base'][b.name]
    bpy.context.view_layer.update()
    rotate(p,'head',Quaternion((1,0,0),.12*(1-ease((f-28)/55))))
    rotate(a,'head',Quaternion((0,0,1),-.05+.08*ease((f-430)/50)))
    rotate(a,'spine2',Quaternion((1,0,0),.018*math.sin(f/18)))
    rotate(a,'bicep_R',Quaternion((0,1,0),-.60))
    rotate(a,'bicep_L',Quaternion((0,1,0),.60))
    if f>=316:
        moves={side:travel(side,f) for side in 'LR'}
        level={side:ground(feet[side].translation.y-v[2])*(1-v[4])+ground(feet[side].translation.y-v[3])*v[4] for side,v in moves.items()}
        a['root'].location.y-=(moves['L'][0]+moves['R'][0])/2
        a['root'].location.z+=(level['L']+level['R'])/2-.035*max(v[1] for v in moves.values())
        bpy.context.view_layer.update()
        rotate(a,'spine1',Quaternion((1,0,0),.055*max(v[1] for v in moves.values())))
        targets={side:feet[side].translation+Vector((0,-v[0],level[side]+.24*v[1])) for side,v in moves.items()}
        drop=0
        for side,target in targets.items():
            hip,knee,ankle=[position(a,b+'_'+side) for b in ('thigh','knee','ankle')]
            reach=((hip-knee).length+(knee-ankle).length)*.975
            horizontal=(hip.x-target.x)**2+(hip.y-target.y)**2
            drop=max(drop,hip.z-target.z-math.sqrt(max(.01,reach*reach-horizontal)))
        a['root'].location.z-=max(0,drop)
        bpy.context.view_layer.update()
        for side,v in moves.items():
            target=targets[side]
            leg(a,side,target)
            m=feet[side].copy();m.translation=position(a,'ankle_'+side)
            arm.pose.bones['ankle_'+side].matrix=arm.matrix_world.inverted()@m
            contact.append({'frame':f,'side':side,'swing':v[1],'target':list(target),'actual':list(position(a,'ankle_'+side))})
        swing=(moves['R'][1]-moves['L'][1])*.09
        rotate(a,'bicep_R',Quaternion((1,0,0),swing))
        rotate(a,'bicep_L',Quaternion((1,0,0),-swing))
    reaction=ease((f-246)/12)-.45*ease((f-274)/37)
    rotate(n,'Spine_1',Quaternion((1,0,0),-.09*reaction))
    rotate(n,'head',Quaternion((1,0,0),-.08*reaction))
    for act in [p,a,n]:
        act['root'].keyframe_insert('location',frame=f)
        for b in act['arm'].pose.bones:
            b.rotation_mode='QUATERNION'
            for prop in ['location','rotation_quaternion','scale']:b.keyframe_insert(prop,frame=f)
        visible=f<155 if act is p else f>=155 if act is a else f<316
        expressions=face_values(f,act)
        for o in act['obs']:
            o.hide_render=not visible;o.keyframe_insert('hide_render',frame=f)
            if o.type=='MESH' and o.data.shape_keys:
                for key in o.data.shape_keys.key_blocks:
                    if key.name=='Basis':continue
                    key.value=expressions.get(key.name,0)
                    key.keyframe_insert('value',frame=f)

s.render.engine='BLENDER_EEVEE';s.eevee.taa_render_samples=64
s.render.resolution_x=540;s.render.resolution_y=960
s.render.filepath=str(OUT/'frames/frame_')
s.frame_start=1;s.frame_end=504;s.frame_set(1)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'jojo-v2.blend'))
(OUT/'contacts.json').write_text(json.dumps(contact,indent=2))
(OUT/'speech-alignment.json').write_text(json.dumps(speech,ensure_ascii=False,indent=2),encoding='utf-8')
print('REVISION_2_READY',flush=True)
