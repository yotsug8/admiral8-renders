@echo off
if not defined DOTA set DOTA=D:\SteamLibrary\steamapps\common\dota 2 beta\game\dota
if not defined S2V set S2V=%USERPROFILE%\Desktop\ClaudeCode\s2v\Source2Viewer-CLI.exe
set OUT=%~dp0..\..\_game
"%S2V%" -i "%DOTA%\maps\dota.vpk" --vpk_filepath "maps/dota/world.vwrld_c" -o "%OUT%\world\world.gltf" -d --gltf_export_format gltf --gltf_export_materials --gltf_export_extras --game "%DOTA%\gameinfo.gi"
echo DONE_EXIT=%ERRORLEVEL%
