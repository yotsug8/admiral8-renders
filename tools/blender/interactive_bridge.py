"""Explicit, process-only MCP for Blender bridge; run with GUI Blender -P.
No preferences saved, no automatic future startups, no remote assets enabled.
Stop: bpy.ops.blendermcp.stop_server(), or close this owned Blender process.
"""
import os,sys,hashlib,zipfile,importlib.util
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[2]
import json
sys.path.insert(0,str(ROOT/'tools'))
from resource_paths import RESOURCES
spec_data=json.loads((ROOT/'docs/OPTIONAL_RESOURCES.json').read_text(encoding='utf-8'))['blender_addons']['mcp-for-blender']
BASE=RESOURCES/('blender-addons/mcp-for-blender-'+spec_data['version'])
WHEEL=BASE/spec_data['filename']
SHA=spec_data['sha256']
if bpy.app.background: raise RuntimeError('Interactive bridge requires GUI Blender; background jobs use ordinary bpy scripts.')
if hashlib.sha256(WHEEL.read_bytes()).hexdigest()!=SHA: raise RuntimeError('Bridge wheel checksum mismatch')
entry='blender_mcp/bundled/addon.py';source=BASE/'source'/entry
with zipfile.ZipFile(WHEEL) as z:
 if source.read_bytes()!=z.read(entry):raise RuntimeError('Bridge addon differs from pinned wheel')
os.environ['BLENDERMCP_NO_UPDATE_CHECK']='1'
os.environ['BLENDER_MCP_DISABLE_TELEMETRY']='1'
os.environ['BLENDER_MCP_SAFE_MODE']='1'
# Import only the audited addon, without running its setup/config writers.
spec=importlib.util.spec_from_file_location('admiral8_mcp_bridge',source)
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
addon.register()
bpy.context.scene.blendermcp_auto_start_server=False
addon._blendermcp_unregister_auto_start()
port=int(os.environ.get('A8_BLENDER_BRIDGE_PORT','19876'))
if not 1024<=port<=65535:raise ValueError('Port outside allowed range')
server=addon.BlenderMCPServer(host='127.0.0.1',port=port)
bpy.types.blendermcp_server=server
bpy.context.scene.blendermcp_port=port
server.start()
bpy.context.scene.blendermcp_server_running=server.running
if not server.running:raise RuntimeError('Bridge failed to start; see Blender log')
print('Admiral8 interactive bridge enabled for this process only on 127.0.0.1:'+str(port),flush=True)
