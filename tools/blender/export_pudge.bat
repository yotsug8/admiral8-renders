@echo off
if not defined DOTA set DOTA=D:\SteamLibrary\steamapps\common\dota 2 beta\game\dota
if not defined S2V set S2V=C:\Users\kunkk\Desktop\ClaudeCode\s2v\Source2Viewer-CLI.exe
set OUT=%~dp0..\..\_game\models\pudge
set ANIMS=pudge_idle,pudge_idle_alt,pudge_flail,pudge_taunt_money_maker,pudge_clown_taunt,victory,pudge_stun,pudge_rot,pudge_attack1,pudge_attack2,ftp_dendi_idle_stomp,ftp_dendi_idle_look,pudge_idle_injured,pudge_loadout,pudge_spawn,pudge_teleport_end,pudge_dismember_start,pudge_meathook_start
"%S2V%" -i "%DOTA%\pak01_dir.vpk" --vpk_filepath "models/heroes/pudge/pudge.vmdl_c" -o "%OUT%\pudge.glb" -d --gltf_export_format glb --gltf_export_materials --gltf_textures_adapt --gltf_export_animations --gltf_animation_list "%ANIMS%" --game "%DOTA%\gameinfo.gi"
echo PUDGE_EXIT=%ERRORLEVEL%
for %%P in (back belt bracer hair leftarm leftweapon righthook weapon) do (
  "%S2V%" -i "%DOTA%\pak01_dir.vpk" --vpk_filepath "models/heroes/pudge/%%P.vmdl_c" -o "%OUT%\%%P.glb" -d --gltf_export_format glb --gltf_export_materials --gltf_textures_adapt --gltf_export_animations --game "%DOTA%\gameinfo.gi"
  echo PART_%%P_EXIT=!ERRORLEVEL!
)
echo ALL_DONE
