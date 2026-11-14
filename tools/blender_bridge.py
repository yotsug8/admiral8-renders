"""Prepare the opt-in Blender bridge, or print its reviewed MCP config.

Usage: py -3.11 tools/blender_bridge.py install
       py -3.11 tools/blender_bridge.py config
Launch Blender GUI with -P tools/blender/interactive_bridge.py explicitly.
This command never edits Codex config or Blender preferences.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
import zipfile

if __package__:
    from .optional_addons import install, CATALOG
    from .resource_paths import RESOURCES
else:
    from optional_addons import install, CATALOG
    from resource_paths import RESOURCES

NAME = 'mcp-for-blender'


def specification():
    spec = json.loads(CATALOG.read_text(encoding='utf-8'))['blender_addons'][NAME]
    return spec, RESOURCES / 'blender-addons' / (NAME + '-' + spec['version'])


def verify(spec, folder):
    wheel = folder / spec['filename']
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != spec['sha256']:
        raise ValueError('Bridge archive checksum mismatch')
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            if not entry.is_dir() and (folder / 'source' / entry.filename).read_bytes() != archive.read(entry):
                raise ValueError('Modified bridge source: ' + entry.filename)


def prepare():
    if os.name != 'nt' or sys.version_info[:2] != (3, 11):
        raise ValueError('This pinned runtime is verified for Windows Python 3.11 only')
    spec, folder = specification()
    if not folder.exists():
        install(NAME)
    verify(spec, folder)
    lock = folder / 'requirements.lock.txt'
    lock.write_text('\n'.join(spec['runtime_requirements']) + '\n', encoding='utf-8')
    runtime = folder / 'venv'
    if not runtime.exists():
        venv.EnvBuilder(with_pip=True).create(runtime)
    python = runtime / 'Scripts/python.exe'
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--require-hashes', '--only-binary=:all:', '-r', str(lock)], check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    return folder


def config():
    spec, folder = specification()
    verify(spec, folder)
    exe = folder / 'venv/Scripts/mcp-for-blender.exe'
    if not exe.exists():
        raise ValueError('Runtime absent; run install first')
    # Printing this is not registering it. Registration/restart remains explicit.
    print('[mcp_servers.blender]')
    print('command = ' + json.dumps(exe.as_posix()))
    print('args = ["--host", "127.0.0.1", "--port", "19876"]')
    print('env = { BLENDER_MCP_DISABLE_TELEMETRY = "1", BLENDER_MCP_SAFE_MODE = "1", BLENDERMCP_NO_UPDATE_CHECK = "1" }')


async def call_tool(args):
    # Official MCP SDK and stdio transport; no custom bridge protocol.
    import asyncio
    import base64
    import time
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    spec, folder = specification()
    verify(spec, folder)
    values = json.loads(Path(args.args_file).read_text(encoding='utf-8-sig')) if args.args_file else {}
    if args.script:
        if args.tool != 'execute_blender_code':
            raise ValueError('--script is only for execute_blender_code')
        values['code'] = Path(args.script).read_text(encoding='utf-8-sig')
    if not isinstance(values, dict):
        raise ValueError('Tool arguments must be a JSON object')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, BLENDER_MCP_DISABLE_TELEMETRY='1', BLENDER_MCP_SAFE_MODE='1', BLENDERMCP_NO_UPDATE_CHECK='1')
    params = StdioServerParameters(command=str(folder/'venv/Scripts/mcp-for-blender.exe'), args=['--host','127.0.0.1','--port',str(args.port)], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            started = time.perf_counter()
            result = await asyncio.wait_for(session.call_tool(args.tool, values), timeout=args.timeout)
            report = {'tool': args.tool, 'seconds': time.perf_counter()-started, 'isError': result.isError, 'content': []}
            for i, item in enumerate(result.content):
                if item.type == 'image':
                    extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}.get(item.mimeType)
                    if not extension:
                        raise ValueError('Unsupported image MIME: '+item.mimeType)
                    path = output/('image-'+str(i)+extension)
                    path.write_bytes(base64.b64decode(item.data, validate=True))
                    report['content'].append({'type':'image','path':str(path)})
                    print(path)
                elif item.type == 'text':
                    report['content'].append({'type':'text','text':item.text})
                    print(item.text)
                else:
                    report['content'].append(item.model_dump(mode='json'))
            (output/'response.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            return 1 if result.isError else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('install')
    commands.add_parser('config')
    call = commands.add_parser('call', help='Use the official MCP SDK without editing Codex config')
    call.add_argument('tool', help='For example get_scene_info, look, execute_blender_code')
    call.add_argument('--args-file', help='UTF-8 JSON tool parameters')
    call.add_argument('--script', help='Python source for execute_blender_code, subject to upstream safe mode')
    call.add_argument('--output', required=True, help='Local QA directory for response and returned images')
    call.add_argument('--port', type=int, default=19876)
    call.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    try:
        if args.action == 'install':
            print(prepare())
        elif args.action == 'config':
            config()
        else:
            spec, folder = specification()
            python = folder/'venv/Scripts/python.exe'
            if not python.exists():
                raise ValueError('Runtime absent; run install first')
            if Path(sys.executable).resolve() != python.resolve():
                return subprocess.run([str(python), str(Path(__file__).resolve()), *sys.argv[1:]], check=False).returncode
            import asyncio
            return asyncio.run(call_tool(args))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
