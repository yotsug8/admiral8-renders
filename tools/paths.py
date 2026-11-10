# Пути к программам и игре — в одном месте. Свой ПК — переменными окружения, без правки кода:
#   DOTA_ROOT  — папка «dota 2 beta» (в ней game\dota и content\)
#   S2V        — Source2Viewer-CLI.exe
#   BLENDER    — blender.exe
import os
from pathlib import Path
import re
import shutil

REPO = str(Path(__file__).resolve().parents[1])


def steam_libraries():
    steam = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Steam'
    if os.name == 'nt':
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                steam = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
        except OSError:
            pass
    try:
        config = (steam / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        config = ''
    return list(dict.fromkeys([steam, *(Path(value.replace('\\\\', '\\')) for value in
                                       re.findall(r'"path"\s+"([^"\r\n]+)"', config))]))


LIBRARIES = steam_libraries()
DOTA_INSTALLS = [library / 'steamapps/common/dota 2 beta' for library in LIBRARIES]
DOTA_ROOT = os.environ.get('DOTA_ROOT') or str(next(
    (path for path in DOTA_INSTALLS if (path / 'game/dota/pak01_dir.vpk').is_file()), DOTA_INSTALLS[0]))
GAME = os.path.join(DOTA_ROOT, "game", "dota")                         # игра: pak01_dir.vpk, console.log, screenshots
ADDON = os.path.join(DOTA_ROOT, "game", "dota_addons", "admiral8")      # мод-режиссёр
CONTENT = os.environ.get("DOTA_ADDON_CONTENT", os.path.join(DOTA_ROOT, "content", "dota_addons", "admiral8"))
VPK = os.path.join(GAME, "pak01_dir.vpk")
RC = os.path.join(DOTA_ROOT, "game", "bin", "win64", "resourcecompiler.exe")
SCENE_TXT = os.path.join(ADDON, "scripts", "a8_scene.txt")             # сцена, которую читает мод
_STUDIO_S2V = Path(REPO) / "out/studio/resources/source2viewer/Source2Viewer-CLI.exe"
S2V = (os.environ.get("S2V") or os.environ.get("S2V_CLI") or shutil.which("Source2Viewer-CLI")
       or (str(_STUDIO_S2V) if _STUDIO_S2V.is_file() else os.path.join(os.path.dirname(REPO), "s2v", "Source2Viewer-CLI.exe")))
BLENDER_INSTALLS = [library / 'steamapps/common/Blender/blender.exe' for library in LIBRARIES]
BLENDER_INSTALLS += sorted((Path(os.environ.get('ProgramFiles', r'C:\Program Files')) /
                           'Blender Foundation').glob('Blender */blender.exe'), reverse=True)
BLENDER = os.environ.get('BLENDER') or shutil.which('blender') or str(next(
    (path for path in BLENDER_INSTALLS if path.is_file()), 'blender'))
