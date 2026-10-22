# Крупный план Пуджа основной камерой: blender -b scene006.blend -P zoom_who.py -- <кадр> <имя> <файл>
import bpy, sys
A = sys.argv[sys.argv.index("--") + 1:]; frame, who, name = int(A[0]), A[1], A[2]
sc = bpy.context.scene
a = next(o for o in sc.objects if o.type == "ARMATURE" and o.parent and o.parent.name == "Mover_" + who)
sc.frame_set(frame)
t = a.matrix_world @ a.pose.bones["spine3"].head
cam = sc.camera; loc = cam.matrix_world.translation.copy()
for c in list(cam.constraints): cam.constraints.remove(c)
cam.animation_data_clear(); cam.location = loc
cam.rotation_euler = (t - loc).to_track_quat("-Z", "Y").to_euler(); cam.data.angle_y = 0.2; cam.data.dof.use_dof = False
sc.render.resolution_percentage = 50; sc.eevee.taa_render_samples = 16; sc.render.use_motion_blur = False
sc.render.filepath = name; bpy.ops.render.render(write_still=True)
