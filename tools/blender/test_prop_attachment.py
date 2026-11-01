"""Asset-free attachment regression checks; run in background factory Blender."""
from pathlib import Path
import sys
import unittest

import bpy
from mathutils import Matrix, Quaternion

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prop_attachment import bake_pickup


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sc = bpy.context.scene
        data = bpy.data.armatures.new('fixture')
        self.arm = bpy.data.objects.new('fixture', data)
        sc.collection.objects.link(self.arm)
        bpy.context.view_layer.objects.active = self.arm
        self.arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        b = data.edit_bones.new('hand')
        b.head, b.tail = (0, 0, 0), (0, 0, 1)
        bpy.ops.object.mode_set(mode='OBJECT')
        bone = self.arm.pose.bones['hand']
        bone.rotation_mode = 'QUATERNION'
        for frame in range(41):
            bone.rotation_quaternion = Quaternion((0, 1, 0), .01*frame)
            bone.keyframe_insert('rotation_quaternion', frame=frame)
            self.arm.location = (.01*frame, 0, 0)
            self.arm.keyframe_insert('location', frame=frame)
        self.prop = bpy.data.objects.new('prop', None)
        sc.collection.objects.link(self.prop)
        self.prop.matrix_world = Matrix.Translation((1, 2, 3))
        sc.frame_set(0)

    def test_translation_and_rotation_transfer(self):
        action = self.arm.animation_data.action
        r = bake_pickup(self.prop, self.arm, 'hand', 15, 40)
        self.assertLess(r['switch_matrix_error'], 1e-5)
        self.assertLess(r['max_grip_matrix_error'], 2e-4)
        self.assertIs(self.arm.animation_data.action, action)

    def test_repeated_application_rejected(self):
        bake_pickup(self.prop, self.arm, 'hand', 15, 40)
        with self.assertRaises(ValueError):
            bake_pickup(self.prop, self.arm, 'hand', 15, 40)

    def test_invalid_window_rejected(self):
        with self.assertRaises(ValueError):
            bake_pickup(self.prop, self.arm, 'hand', 40, 15)
        self.assertIsNone(self.prop.animation_data)

    def test_parent_rejected_without_animation(self):
        self.prop.parent = self.arm
        with self.assertRaises(ValueError):
            bake_pickup(self.prop, self.arm, 'hand', 15, 40)
        self.assertIsNone(self.prop.animation_data)

    def test_nonuniform_rig_rotation_shear_rejected(self):
        self.arm.scale = (2, 1, 1)
        bpy.context.view_layer.update()
        original = self.prop.matrix_world.copy()
        with self.assertRaises(ValueError):
            bake_pickup(self.prop, self.arm, 'hand', 15, 40)
        self.assertIsNone(self.prop.animation_data)
        self.assertLess(max(abs(self.prop.matrix_world[r][c]-original[r][c])
                            for r in range(4) for c in range(4)), 1e-6)

    def test_missing_bone_rejected(self):
        with self.assertRaises(ValueError):
            bake_pickup(self.prop, self.arm, 'absent', 15, 40)
        self.assertIsNone(self.prop.animation_data)


if __name__ == '__main__':
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(AttachmentTests))
    if not result.wasSuccessful():
        raise RuntimeError('Attachment regression checks failed')
