"""Character-led revision: relaxed free arm, one impact, attentive defender."""
import json
import math
from pathlib import Path
import shutil
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
import doomsday_assembled as assembly
import doomsday_attack as attack
import doomsday_full_scene as film
import doomsday_performance as motion
from doomsday_native_pressure import hinge

OUT=film.OUT.parent/'revision_alive'


def phrase(frame,keys):
    """Bounded transitions without Hermite overshoot or repeated oscillation."""
    if frame<=keys[0][0]:return keys[0][1]
    for (a,x),(b,y) in zip(keys,keys[1:]):
        if frame<=b:return x+(y-x)*film.smooth((frame-a)/(b-a))
    return keys[-1][1]


def performance(state,frame,a,r):
    axe,rubick=state[1]['axe'],state[1]['rubick']
    if frame==0:
        voice=json.loads((OUT/'threat_ru_envelope.json').read_text(encoding='utf8'))
        original=state[5]['facial_values'].copy()
        start=voice['start_frame_exact'];new_length=voice['duration_s']*30
        old_length=(5.455854-2.48)*30
        for i,channel in enumerate(state[4]['facial_channels']):
            if 'axe' not in channel['object']:continue
            if not any(word in channel['shape'].lower() for word in ('lip','jaw','phoneme','chin')):continue
            for f in range(74,172):
                sample=start+(f-start)*old_length/new_length
                state[5]['facial_values'][f,i]=np.interp(sample,np.arange(420),original[:,i])
    if frame<247:
        release=1-film.smooth((frame-237)/10)
        # Lower the raised elbow and open its bend. Hand remains beside the
        # hip; the correction ends before the original grip closes.
        motion.branch(axe,a,'elbow_L',math.radians(-50*release),hinge(a,('bicep_L','elbow_L','wrist_L')))
        motion.branch(axe,a,'bicep_L',math.radians(40*release),'Y')
    if frame>=279:
        load=phrase(frame,((279,attack.IMPACT_LOAD),(286,-.08),(330,-.08),(419,-.30)))
        lag=1-film.smooth((frame-279)/12)
        a=attack.reaction(state,load,lag)
        realization=film.smooth((frame-354)/45)
        motion.branch(axe,a,'head',math.radians(-6*realization),'X')
        a=attack.grip(state,a)[0]
    # The defender notices the charging weapon, settles his stance and
    # presents the hand deliberately before the incoming blade reaches him.
    if frame<279:
        r=motion.mix(rubick,state[3]['rubick'][195],state[2]['rubick'][0],
                     film.smooth((frame-246)/32))
        turn=phrase(frame,((0,7),(38,0),(180,0),(211,-4),(216,-4),(237,-6),(278,0)))
        lean=phrase(frame,((0,-3),(38,0),(195,0),(237,-2),(278,0)))
        motion.branch(rubick,r,'Root_0',math.radians(turn),'Z')
        motion.branch(rubick,r,'Spine_3',math.radians(lean),'X')
        look=phrase(frame,((0,8),(38,0),(180,0),(211,-6),(216,-6),(246,0),(267,9),(278,0)))
        motion.branch(rubick,r,'Head_0',math.radians(look),'X')
        motion.branch(rubick,r,'Head_0',math.radians(-turn*.65),'Z')
        staff=phrase(frame,((0,-5),(35,0),(180,0),(211,-4),(216,-4),(246,0),(265,3),(278,0)))
    else:
        r=attack.copy_pose(state[2]['rubick'][0])
        look=phrase(frame,((279,0),(315,0),(345,-9),(366,-9),(397,-3),(419,-3)))
        motion.branch(rubick,r,'Head_0',math.radians(look),'Z')
        motion.branch(rubick,r,'Head_0',math.radians(phrase(frame,((279,0),(332,0),(354,-5),(419,-5)))),'X')
        staff=phrase(frame,((279,0),(301,0),(330,-6),(360,-6),(392,-3),(419,-3)))
    # The staff stays with its hand. Right wrist and fingers are untouched
    # after contact; the response is attention and a deliberate left-arm settle.
    motion.branch(rubick,r,'bicep_L',math.radians(staff),'X')
    cloth=phrase(frame,((0,0),(248,0),(274,2),(291,-1),(314,0),(419,0)))
    for bone in ('RTabord_R0C0','LTabord_R0C0','RBRobe_R0C0','LBRobe_R0C0'):
        motion.branch(rubick,r,bone,math.radians(cloth),'X')
    return a,r


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    source=film.OUT.parent/'assembled'
    shutil.copy2(source/'battle_cry_envelope.json',OUT/'battle_cry_envelope.json')
    assembly.OUT=OUT
    assembly.SHOTS=((0,'Establish'),(45,'Weapon'),(120,'Threat'),(180,'Assess'),
                    (217,'Charge'),(237,'Attack'),(281,'Contact'),(295,'Effort'),
                    (330,'Rubick'),(360,'Realization'))
    scene=assembly.build(adjust=performance)
    scene.render.resolution_x,scene.render.resolution_y=960,540
    (OUT/'intent.json').write_text(json.dumps({
        'free_arm':'elbow lowered, bend opened, hand beside hip; raised before two-hand pickup',
        'impact':'one load acceptance, no repeated pull/recoil cycles',
        'defender':'weapon attention, stance settling, earlier deliberate intercept, head/staff reaction',
        'contact_frame':279,'material_changes_pending':True},indent=2),encoding='utf8')
    return scene


def look():
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'assembly.blend'))
    assembly.OUT=OUT
    scene=assembly.finish_look(bpy.context.scene)
    from doomsday_ground_finish import apply as ground
    from doomsday_action_accents import apply as accents
    reports={'ground':ground(scene),'accents':accents(scene,impact_gain=.20)}
    scene.render.engine='BLENDER_EEVEE';scene.eevee.taa_render_samples=64
    scene.eevee.use_volume_custom_range=True
    scene.eevee.volumetric_start=.1;scene.eevee.volumetric_end=30
    scene.eevee.volumetric_samples=128;scene.eevee.volumetric_tile_size='4'
    scene.render.resolution_x,scene.render.resolution_y=1280,720
    scene.render.resolution_percentage=100
    scene.render.use_motion_blur=False
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'material.blend'),compress=True)
    (OUT/'look_recipe.json').write_text(json.dumps(reports,indent=2),encoding='utf8')
    intent_path=OUT/'intent.json'
    if intent_path.exists():
        intent=json.loads(intent_path.read_text(encoding='utf8'))
        intent['material_changes_pending']=False
        intent_path.write_text(json.dumps(intent,indent=2),encoding='utf8')
    return scene


if __name__=='__main__':
    if '--render' in sys.argv:
        assembly.OUT=OUT
        assembly.render_scene()
    elif '--look' in sys.argv:look()
    else:build()
