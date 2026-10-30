# Пути к программам и игре — в одном месте. Свой ПК — переменными окружения, без правки кода:
#   DOTA_ROOT  — папка «dota 2 beta» (в ней game\dota и content\)
#   S2V        — Source2Viewer-CLI.exe
#   BLENDER    — blender.exe
import os

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DOTA_ROOT = os.environ.get("DOTA_ROOT", r"D:\SteamLibrary\steamapps\common\dota 2 beta")
GAME = os.path.join(DOTA_ROOT, "game", "dota")                         # игра: pak01_dir.vpk, console.log, screenshots
ADDON = os.path.join(DOTA_ROOT, "game", "dota_addons", "admiral8")      # мод-режиссёр
CONTENT = os.path.join(DOTA_ROOT, "content", "dota_addons", "admiral8")
VPK = os.path.join(GAME, "pak01_dir.vpk")
RC = os.path.join(DOTA_ROOT, "game", "bin", "win64", "resourcecompiler.exe")
SCENE_TXT = os.path.join(ADDON, "scripts", "a8_scene.txt")             # сцена, которую читает мод
S2V = os.environ.get("S2V", os.environ.get("S2V_CLI", os.path.join(os.path.dirname(REPO), "s2v", "Source2Viewer-CLI.exe")))
BLENDER = os.environ.get("BLENDER", r"D:\SteamLibrary\steamapps\common\Blender\blender.exe")
