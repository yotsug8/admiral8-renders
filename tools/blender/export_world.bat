@echo off
rem Мир карты доты → _game/world/world.gltf (для tools/map_crop.mjs). Пути — как в tools/paths.py: DOTA_ROOT, S2V.
if not defined DOTA_ROOT set DOTA_ROOT=D:\SteamLibrary\steamapps\common\dota 2 beta
if not defined S2V set S2V=C:\Users\kunkk\Desktop\ClaudeCode\s2v\Source2Viewer-CLI.exe
set DOTA=%DOTA_ROOT%\game\dota
set OUT=%~dp0..\..\_game
"%S2V%" -i "%DOTA%\maps\dota.vpk" --vpk_filepath "maps/dota/world.vwrld_c" -o "%OUT%\world\world.gltf" -d --gltf_export_format gltf --gltf_export_materials --gltf_export_extras --game "%DOTA%\gameinfo.gi"
echo DONE_EXIT=%ERRORLEVEL%
