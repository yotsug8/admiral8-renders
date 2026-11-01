"""One isolated Corrective Smooth candidate; never changes source or thresholds."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import bpy
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study_retarget_character as character

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);folder=a.out.resolve()
if folder.exists() and any(folder.iterdir()):raise ValueError('An empty output folder is required')
folder.mkdir(parents=True,exist_ok=True)
source=a.source.resolve()/'character.blend';before=character.digest(source)
bpy.ops.wm.open_mainfile(filepath=str(source));sc=bpy.context.scene
sc.frame_set(1);bpy.context.view_layer.update();base=character.surfaces()
changed=[]
for ob in character.meshes():
    if not any(n in ob.name for n in ('.head','upper_body','hitbox_fix','back_model','belt_model','leftarm_model')):
        continue
    character.api.select_only(ob)
    mod=ob.modifiers.new('StudyCorrective','CORRECTIVE_SMOOTH')
    mod.factor=.5;mod.iterations=5;mod.scale=1.
    mod.smooth_type='LENGTH_WEIGHTED';mod.use_pin_boundary=True;mod.rest_source='BIND'
    bpy.ops.object.correctivesmooth_bind(modifier=mod.name)
    if not mod.is_bind:raise ValueError('Modifier was not bound')
    changed.append(ob.name)
bpy.context.view_layer.update();after=character.surfaces()
error=max(float(np.abs(after[n]-b).max()) for n,b in base.items())
if error>2e-5:raise ValueError('Correction changed bound pose')
bpy.context.preferences.filepaths.file_preview_type='NONE'
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(folder/'character.blend'))
shutil.copyfile(a.source/'live_matrices.json',folder/'live_matrices.json')
report={'source_sha256':before,'source_unchanged':character.digest(source)==before,
 'bound_pose_error_m':error,'meshes':changed,'preset':{'factor':.5,'iterations':5,'scale':1,
 'type':'LENGTH_WEIGHTED','pin_boundaries':True,'rest':'BIND'},'limits':'One preset only; target acceptance still requires unchanged mesh audit and visual checks.'}
(folder/'corrective.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
assert report['source_unchanged']
print('CORRECTIVE_CANDIDATE_SAVED')
