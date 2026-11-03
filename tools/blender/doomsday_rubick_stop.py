"""Локальная постановка останавливающей руки Рубика в pressure study.

Поправку выбирают по evaluated коже кончика относительно наружной поверхности
лезвия и сохраняют в координатах axe_1. Основание index_1_R не является
контактной подушечкой. Функция меняет только правую руку и её дочерние кости,
сохраняет форму пальцев и исходную плоскость локтя, важную для рукава.

Пример в сборщике до bake:
    defender = correct_pose(rubick, defender, weapon_world, withdrawal_local)

Это не универсальный контактный solver. Передаваемый withdrawal_local должен
быть получен для этой пары ресурсов и исходного хвата. После переноса проверять
кончик/подушечку, рукав и силуэт с разных сторон и в темпе. Одно лишь отсутствие
inside-отсчётов не подтверждает естественную постановку пальца.
"""
from mathutils import Quaternion, Vector

from doomsday_performance import solve_arm

# Authored for the local v11 weapon/hand resources, with weapon shifted +0.8 X.
# Four evaluated poses (0/39/48/79) had no sampled finger penetration;
# tip clearance 0.0020..0.0037 world units. This is not a general rig preset.
WITHDRAWAL_LOCAL = (-0.04748235642910004, -0.017838377505540848, 0.18998904526233673)
INDEX_ROTATION_LOCAL = (0.9496061205863953, 0.011674538254737854,
                        -0.3022744357585907, 0.08211199939250946)


def correct_pose(arm, pose, weapon_world, withdrawal_local, index_rotation_local=None):
    """Передвинуть контакт от основания сустава к коже, не задавая случайный pole."""
    if index_rotation_local is not None:
        pose = {name: matrix.copy() for name, matrix in pose.items()}
        finger = pose['index_1_R']
        delta = finger @ Quaternion(index_rotation_local).to_matrix().to_4x4() @ finger.inverted()
        for bone in [arm.pose.bones['index_1_R'], *arm.pose.bones['index_1_R'].children_recursive]:
            pose[bone.name] = delta @ pose[bone.name]
    target = pose['wrist_R'].copy()
    target.translation += weapon_world.to_3x3() @ Vector(withdrawal_local)
    original_elbow_plane = (pose['elbow_R'].translation
                            - pose['bicep_R'].translation)
    return solve_arm(arm, pose, 'R', target, original_elbow_plane)
