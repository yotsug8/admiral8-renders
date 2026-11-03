"""Изолированные проверки Workshop без сети и Blender.

Синтетические архивы:
    py -3.11 -B -m unittest tools.skit.test_workshop_textures -v
Дополнительно prepare на существующем локальном кэше (PowerShell):
    $env:WORKSHOP_REAL_CACHE='1'
    py -3.11 -B -m unittest tools.skit.test_workshop_textures -v
    Remove-Item Env:WORKSHOP_REAL_CACHE
Подготовка карт и отчёта textures.json из имеющихся архивов:
    py -3.11 -B tools/skit/workshop_textures.py --heroes kunkka pudge --out _game/models/workshop --game-dir _game/models/render

Реальная проверка перезаписывает только подготовленные карты/manifest,
проверяет их идентичность и запрещает загрузки. Не запускает общий check.py.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from tools.skit import workshop_textures as wt


class WorkshopTexturesTest(unittest.TestCase):
    def setUp(self):
        cache=wt.ROOT/'_game/models/workshop'
        cache.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='test_',dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)/'workshop';self.out.mkdir()
        self.game=Path(self.temp.name)/'game';self.game.mkdir()
        self.network=patch.object(wt,'urlopen',side_effect=AssertionError('Network forbidden'))
        self.network.start();self.addCleanup(self.network.stop)

    def fixture(self,hero,prefix='materials',container=None,omit=None):
        payload=io.BytesIO()
        with zipfile.ZipFile(payload,'w') as archive:
            for material,(stem,game) in wt.MAP[hero].items():
                for kind in ('color','normal'):
                    rgb=(40,80,120) if kind=='color' else (100,60,240)
                    source=Image.new('RGB',(8,4),rgb)
                    data=io.BytesIO();source.save(data,format='TGA')
                    member=f'{prefix}/{stem}_{kind}.tga'
                    if member!=omit:archive.writestr(member,data.getvalue())
                    # Normal convention is deliberately opposite in the game.
                    target=rgb if kind=='color' else (100,195,240)
                    Image.new('RGB',(2,1),target).save(self.game/f'{game}_{kind}_fixture.png')
        if container:
            with zipfile.ZipFile(self.out/f'{hero}.zip','w') as archive:
                archive.writestr(container,payload.getvalue())
                archive.writestr('pudge_cute.zip',b'not a texture archive')
        else:(self.out/f'{hero}.zip').write_bytes(payload.getvalue())

    def prepare(self,*heroes):
        with contextlib.redirect_stdout(io.StringIO()):
            wt.prepare(self.out,heroes,self.game)
        return json.loads((self.out/'textures.json').read_text())

    def test_legacy_layout_schema_and_retained_entries(self):
        previous={'archives':{'unselected':{'sha256':'keep'}},
                  'materials':{'unselected':{'custom':['keep',1]}}}
        (self.out/'textures.json').write_text(json.dumps(previous))
        for hero in ('axe','rubick','lina'):
            with self.subTest(hero=hero):
                self.fixture(hero)
                current=self.prepare(hero)
                for section in ('archives','materials'):
                    for key,value in previous[section].items():
                        self.assertEqual(current[section][key],value)
                self.assertEqual(set(current['archives'][hero]),{'url','sha256','terms'})
                for material in wt.MAP[hero]:
                    for info in current['materials'][material].values():
                        self.assertEqual(set(info),{'file','archive_member','size','game_size',
                            'comparison_mae_255','green_flipped','sha256'})
                        self.assertEqual(info['size'],[8,4])
                        self.assertEqual(info['comparison_mae_255'],0)
                previous=current

    def test_explicit_layouts_provenance_and_idempotence(self):
        self.fixture('kunkka','materialsrc/models/heroes/kunkka')
        self.fixture('pudge',container='pudge_base.zip')
        before=self.prepare('kunkka','pudge')
        for hero in ('kunkka','pudge'):
            with zipfile.ZipFile(self.out/f'{hero}.zip') as outer:
                nested=outer.read('pudge_base.zip') if hero=='pudge' else None
                if nested:
                    provenance=before['archives'][hero]['nested_archive']
                    self.assertEqual(provenance['sha256'],hashlib.sha256(nested).hexdigest())
                    self.assertEqual(provenance['bytes'],len(nested))
                with contextlib.ExitStack() as stack:
                    archive=stack.enter_context(zipfile.ZipFile(io.BytesIO(nested))) if nested else outer
                    for material in wt.MAP[hero]:
                        for kind,info in before['materials'][material].items():
                            self.assertEqual(info['source_member_sha256'],
                                hashlib.sha256(archive.read(info['archive_member'])).hexdigest())
                            self.assertEqual(info['green_flipped'],kind=='normal')
                            self.assertEqual(info['size'],[8,4])
                            self.assertEqual(info['comparison_mae_255'],0)
                            if nested:self.assertEqual(info['archive_container'],'pudge_base.zip')
        self.assertEqual(before,self.prepare('kunkka','pudge'))
        self.assertEqual(len(list(self.out.glob('*.png'))),30)
        self.assertFalse((self.out/'pudge_base.zip').exists())

    def test_wrong_nested_archive_does_not_fall_back(self):
        self.fixture('pudge',container='unexpected.zip')
        with self.assertRaises(KeyError):self.prepare('pudge')
        self.assertFalse((self.out/'textures.json').exists())

    def test_missing_member_does_not_fall_back(self):
        member='materialsrc/models/heroes/kunkka/kunkka2_body_color.tga'
        self.fixture('kunkka','materialsrc/models/heroes/kunkka',omit=member)
        with zipfile.ZipFile(self.out/'kunkka.zip','a') as archive:
            archive.writestr('other/kunkka2_body_color.tga',b'wrong path')
        with self.assertRaises(KeyError):self.prepare('kunkka')

    def test_layout_mismatch_is_rejected(self):
        self.fixture('kunkka','materialsrc/models/heroes/kunkka')
        Image.new('RGB',(2,1),(255,255,255)).save(self.game/'kunkka2_body_color_fixture.png')
        with self.assertRaisesRegex(ValueError,'Source layout mismatch'):
            self.prepare('kunkka')
        self.assertFalse((self.out/'textures.json').exists())


@unittest.skipUnless(os.environ.get('WORKSHOP_REAL_CACHE')=='1','Opt-in local asset cache')
class RealWorkshopCacheTest(unittest.TestCase):
    def test_prepare_preserves_manifest_and_png_hashes_offline(self):
        out=wt.ROOT/'_game/models/workshop'
        before=json.loads((out/'textures.json').read_text())
        # Require the prior audited assets; never populate a missing cache.
        for hero in ('kunkka','pudge'):
            self.assertTrue((out/f'{hero}.zip').is_file())
            for material in wt.MAP[hero]:self.assertIn(material,before['materials'])
        png_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.png')}
        with patch.object(wt,'urlopen',side_effect=AssertionError('Network forbidden')), \
                contextlib.redirect_stdout(io.StringIO()):
            wt.prepare(out,('kunkka','pudge'),wt.ROOT/'_game/models/render')
        after=json.loads((out/'textures.json').read_text())
        self.assertEqual(before,after)
        self.assertEqual(png_hashes,
            {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.png')})


if __name__=='__main__':unittest.main()
