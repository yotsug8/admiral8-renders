"""Small synthetic VPK/DMX fixtures; no game resources or exporter required."""
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent
sys.path[:0] = [str(TOOLS), str(TOOLS / 'dota_engine')]
import datamodel as dm
import dota_export
import vpk_tool


class BinaryTests(unittest.TestCase):
    def test_vpk_valid_and_truncated_tree(self):
        entry = b'txt\0 \0hello\0' + struct.pack('<IHHIIH', 0, 2, 0x7fff, 0, 3, 0xffff) + b'hi' + b'\0\0\0'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pak01_dir.vpk'
            with patch.object(vpk_tool, 'DIR', str(path)):
                for version in (1, 2):
                    header = struct.pack('<III', 0x55aa1234, version, len(entry)) + bytes(16 if version == 2 else 0)
                    path.write_bytes(header + entry + b'bye')
                    self.assertEqual(vpk_tool.data(vpk_tool.read_dir()['hello.txt']), b'hibye')
                for bad in (b'txt', b'txt\0path', b'txt\0path\0name', entry[:-1]):
                    # Trailing archive data must not supply a missing tree NUL.
                    path.write_bytes(struct.pack('<III', 0x55aa1234, 1, len(bad)) + bad + b'\0')
                    with self.assertRaises(EOFError):
                        vpk_tool.read_dir()
                path.write_bytes(header + entry[:-5])
                with self.assertRaises(EOFError):
                    vpk_tool.read_dir()

    def test_dmx_eof(self):
        for data in (b'', b'no nul'):
            with self.assertRaises(EOFError):
                dm.get_str(io.BytesIO(data))
        self.assertIsNone(dm.get_str(io.BytesIO(b'\0')))
        self.assertEqual(dm.get_str(io.BytesIO(b'abc\0')), 'abc')
        for stream in (io.BytesIO(b'<!--'), io.StringIO('<!--')):
            with self.assertRaises(IOError):
                dm.load(in_file=stream)
        # Full header, one dictionary entry, truncated C string.
        data = b'<!-- dmx encoding binary 9 format model 1 -->\n\0' + struct.pack('<ii', 0, 1) + b'broken'
        with self.assertRaises(EOFError):
            dm.load(in_file=io.BytesIO(data))

    def test_unsigned_wire_fixture_and_repeated_roundtrip(self):
        # Explicit binary 9 IDs/widths independent of the writer under test.
        entries = [(15, struct.pack('<Q', 2**64 - 1)), (16, b'\xff'),
                   (47, struct.pack('<iQQ', 2, 2**63, 2**64 - 1)),
                   (48, struct.pack('<iBB', 2, 0, 255)),
                   (47, struct.pack('<i', 0)), (48, struct.pack('<i', 0))]
        strings = ['DmElement', 'root'] + ['a' + str(i) for i in range(len(entries))]
        wire = b'<!-- dmx encoding binary 9 format model 1 -->\n\0' + struct.pack('<ii', 0, len(strings))
        wire += b''.join(s.encode() + b'\0' for s in strings)
        wire += struct.pack('<iii', 1, 0, 1) + bytes(16) + struct.pack('<i', len(entries))
        wire += b''.join(struct.pack('<iB', i + 2, typ) + payload for i, (typ, payload) in enumerate(entries))
        model = dm.load(in_file=io.BytesIO(wire))
        expected = [dm.UInt64, dm.UInt8, dm._UInt64Array, dm._UInt8Array, dm._UInt64Array, dm._UInt8Array]
        values = [2**64 - 1, 255, [2**63, 2**64 - 1], [0, 255], [], []]
        for encoding, version in [('binary', 9), ('keyvalues2', 1), ('binary', 9), ('keyvalues2', 4)]:
            for i, typ in enumerate(expected):
                value = model.root['a' + str(i)]
                self.assertIs(type(value), typ)
                self.assertEqual(value, values[i])
                if isinstance(value, list):
                    self.assertTrue(all(type(x) is typ.type for x in value))
            blob = model.echo(encoding, version)
            model = dm.load(in_file=io.BytesIO(blob)) if isinstance(blob, bytes) else dm.parse(blob)
        self.assertIs(type(dm.make_array([2**64 - 1], dm.UInt64)), dm._UInt64Array)
        self.assertIs(type(dm.make_array([255], dm.UInt8)), dm._UInt8Array)

    def test_legacy_binary_types(self):
        for version in (1, 2, 3, 4, 5, 9):
            model = dm.DataModel('model', 1)
            root = model.add_element('root')
            root['number'] = -12
            root['vectors'] = dm.make_array([dm.Vector3([1, 2, 3])], dm.Vector3)
            other = dm.load(in_file=io.BytesIO(model.echo('binary', version)))
            self.assertEqual(other.root['number'], -12)
            self.assertEqual(other.root['vectors'], [[1., 2., 3.]])

    def test_export_clip_arguments_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / 'models/heroes/hero'
            src.mkdir(parents=True)
            for name in ('hero', 'sword', 'hero_arcana', 'hero_physics', 'hero_refit'):
                (src / (name + '.vmdl_c')).touch()
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                Path(args[args.index('-o') + 1]).write_bytes(b'fake GLB')
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.object(dota_export, 'GAME', root / 'out'), patch.object(dota_export, 'game_root', return_value=root), patch.object(dota_export.subprocess, 'run', side_effect=run), patch.object(dota_export, 'pack_glb'):
                dota_export.model(root, 'hero', 'idle,run')
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][-2:], ['--gltf_animation_list', 'idle,run'])
            self.assertEqual(calls[0][0], dota_export.CLI)
            self.assertTrue(all(isinstance(a, str) for args in calls for a in args))
            self.assertNotIn('--gltf_animation_list', calls[1])
            self.assertEqual(sorted(p.name for p in (root / 'out/models/hero').iterdir()), ['hero.glb', 'sword.glb'])


if __name__ == '__main__':
    unittest.main()
