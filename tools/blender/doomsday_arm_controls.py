"""Минимальная нативная IK-проба одной руки Axe; не production-анимация.

create_controls(main) строит connected upper/lower по анатомическим rest heads.
IK Blender решает положения через target/pole без stretch; нижний сустав — hinge.
apply_controls(controls) переносит результат по постоянной rest-калибровке.
Control-space следует clavicle. Старая world-ориентация кисти не используется.

Для MCP: перемещать объекты из controls['target']/['pole'], менять свойства
controls['forearm_roll'] и ['hand_flex'] (радианы), затем apply_controls(controls).
При bake вызывать на каждом кадре с keyframe=True. Автоматического handler нет.
Это локальная проба: новый timeline, хват, кожа и одежда требуют проверки.
Игровые ресурсы не включены. Production solve_arm не вызывается и не меняется.
"""
import bpy
from mathutils import Matrix, Vector

from contact_reaction import _basis


def _snapshot(main):
    return {b.name: main.matrix_world @ b.matrix for b in main.pose.bones}


def _space(main, side):
    """Rest arm в текущем frame ключицы; потомки ключицы не создают feedback."""
    name = 'clavicle_' + side
    return main.matrix_world @ main.pose.bones[name].matrix @ main.data.bones[name].matrix_local.inverted()


def palm_axes(main, side):
    """Fixed wrist-local axes from rest palm landmarks, not the elbow plane."""
    rest = main.data.bones
    wrist = rest['wrist_' + side]
    index = rest['index_0_' + side].head_local
    middle = rest['mid_0_' + side].head_local
    forward = ((index + middle) * .5 - wrist.head_local).normalized()
    across = index - middle
    across -= forward * across.dot(forward)
    if across.length < 1e-6:
        raise ValueError('Palm landmarks do not define a transverse wrist axis.')
    across.normalize()
    normal = forward.cross(across).normalized()
    inverse = wrist.matrix_local.to_3x3().inverted()
    return (inverse @ across).normalized(), (inverse @ normal).normalized()


def create_controls(main, side='L'):
    if side != 'L':
        raise ValueError('Эта минимальная проба проверяется только на L, не универсальный rig.')
    name = 'DoomsdayArmControls_' + side
    if bpy.data.objects.get(name):
        raise ValueError('Controls уже существуют; используйте apply_controls без повторного создания.')
    rest = main.data.bones
    h, k, w = (rest[n + '_' + side].head_local.copy() for n in ('bicep', 'elbow', 'wrist'))
    normal = (k-h).cross(w-k)
    if normal.length < 1e-5:
        raise ValueError('Rest arm почти прямая: нужна явно заданная rest-плоскость.')
    normal.normalize()
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    control = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(control)
    control.matrix_world = _space(main, side)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    control.select_set(True)
    bpy.context.view_layer.objects.active = control
    bpy.ops.object.mode_set(mode='EDIT')
    upper = control.data.edit_bones.new('upper')
    upper.head, upper.tail = h, k
    upper.align_roll(normal)
    lower = control.data.edit_bones.new('lower')
    lower.head, lower.tail = k, w
    lower.parent, lower.use_connect = upper, True
    lower.align_roll(normal)
    hand = control.data.edit_bones.new('hand')
    hand.head = w
    hand.tail = w + rest['wrist_' + side].matrix_local.to_3x3() @ Vector((0, .2, 0))
    hand.align_roll(rest['wrist_' + side].matrix_local.to_3x3() @ Vector((0, 0, 1)))
    hand.parent, hand.use_connect = lower, True
    bpy.ops.object.mode_set(mode='OBJECT')
    control.show_in_front = True
    control.display_type = 'WIRE'
    control['main_armature'] = main.name
    control['side'] = side
    control['forearm_roll'] = 0.0
    control['hand_flex'] = 0.0
    control['hand_deviation'] = 0.0
    control['wrist_axis_mode'] = 'PALM'
    control.id_properties_ui('forearm_roll').update(min=-3.141593, max=3.141593,
                                                   description='Осевое вращение предплечья и наследуемой кисти, радианы')
    control.id_properties_ui('hand_flex').update(min=-.6, max=.6,
                                               description='Сгибание вокруг поперечной оси ладони, радианы')
    control.id_properties_ui('hand_deviation').update(min=-.45, max=.45,
                                                    description='Боковое отклонение кисти в плоскости ладони, радианы')
    pose = _snapshot(main)
    shoulder = control.matrix_world @ h
    total = (control.matrix_world.to_3x3() @ (k-h)).length + (control.matrix_world.to_3x3() @ (w-k)).length
    up = (pose['head'].translation-pose['root'].translation).normalized()
    lateral = shoulder-pose['bicep_R'].translation
    lateral -= up*lateral.dot(up)
    lateral.normalize()
    front = lateral.cross(up).normalized()
    points = {
        'target': shoulder + total*(-lateral*.15 + front*.48 - up*.30),
        'pole': shoulder + total*(lateral*.55 + front*.10 - up*.48),
    }
    for role, point in points.items():
        obj = bpy.data.objects.new(name + '_' + role, None)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = control
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.location = control.matrix_world.inverted() @ point
        obj.empty_display_type = 'SPHERE' if role == 'target' else 'PLAIN_AXES'
        obj.empty_display_size = .12
        obj.show_in_front = True
        control[role] = obj.name
    lower_pose = control.pose.bones['lower']
    lower_pose.lock_ik_x = True
    lower_pose.lock_ik_y = True
    lower_pose.lock_ik_z = False
    for bone in control.pose.bones:
        bone.ik_stretch = 0.0
    ik = lower_pose.constraints.new('IK')
    ik.name = 'Native two-bone arm'
    ik.target = bpy.data.objects[control['target']]
    ik.pole_target = bpy.data.objects[control['pole']]
    ik.chain_count = 2
    ik.use_stretch = False
    ik.use_tail = True
    ik.use_rotation = False
    ik.pole_angle = 0.0  # Rest local-Z is the hinge normal; local-X points to pole.
    ik.iterations = 128
    bpy.context.view_layer.update()
    return control


def apply_controls(control, keyframe=False):
    """Evaluate native IK, then explicit pronation and small hand flex; no custom IK solve."""
    main = bpy.data.objects[control['main_armature']]
    side = control['side']
    before = _snapshot(main)
    control.matrix_world = _space(main, side)
    bpy.context.view_layer.update()
    evaluated = control.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = {}
    for ctrl_name, main_name in (('upper', 'bicep'), ('lower', 'elbow'), ('hand', 'wrist')):
        name = main_name + '_' + side
        # Equivalent to controlPoseWorld @ inverse(controlRestWorld) @ referenceMainWorld,
        # with the two fixed rest transforms expressed in shared object coordinates.
        result[name] = (evaluated.matrix_world @ evaluated.pose.bones[ctrl_name].matrix
                        @ control.data.bones[ctrl_name].matrix_local.inverted()
                        @ main.data.bones[name].matrix_local)
    elbow = result['elbow_' + side].translation.copy()
    wrist = result['wrist_' + side].translation.copy()
    axis = (wrist-elbow).normalized()
    roll = Matrix.Rotation(float(control['forearm_roll']), 4, axis)
    roll_transform = Matrix.Translation(elbow) @ roll @ Matrix.Translation(-elbow)
    result['elbow_' + side] = roll_transform @ result['elbow_' + side]
    result['wrist_' + side] = roll_transform @ result['wrist_' + side]
    if control.get('wrist_axis_mode', 'LEGACY_ELBOW') == 'PALM':
        across, normal = palm_axes(main, side)
        wrist_rotation = result['wrist_' + side].to_3x3()
        flex_axis = (wrist_rotation @ across).normalized()
        deviation_axis = (wrist_rotation @ normal).normalized()
        deviation = Matrix.Rotation(float(control.get('hand_deviation', 0.0)), 4, deviation_axis)
    else:
        # Preserve old negative trials: their hand_flex meant elbow-plane rotation.
        hinge_normal = evaluated.matrix_world.to_3x3() @ evaluated.pose.bones['lower'].z_axis
        flex_axis = roll.to_3x3() @ hinge_normal.normalized()
        deviation = Matrix.Identity(4)
    flex = (Matrix.Translation(wrist)
            @ Matrix.Rotation(float(control['hand_flex']), 4, flex_axis) @ deviation
            @ Matrix.Translation(-wrist))
    result['wrist_' + side] = flex @ result['wrist_' + side]
    # Preserve local finger pose, not the old world orientation of the hand.
    hand_delta = result['wrist_' + side] @ before['wrist_' + side].inverted()
    for bone in main.pose.bones['wrist_' + side].children_recursive:
        result[bone.name] = hand_delta @ before[bone.name]
    desired = {**before, **result}
    inverse = main.matrix_world.inverted()
    for name in result:
        bone = main.pose.bones[name]
        local = _basis(bone, inverse @ desired[name],
                       inverse @ desired[bone.parent.name] if bone.parent else None)
        bone.location, bone.rotation_quaternion, bone.scale = local.decompose()
        bone.rotation_mode = 'QUATERNION'
        if keyframe:
            for channel in ('location', 'rotation_quaternion', 'scale'):
                bone.keyframe_insert(channel, frame=bpy.context.scene.frame_current)
    bpy.context.view_layer.update()
    return result
