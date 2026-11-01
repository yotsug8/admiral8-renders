"""F09: real vendored GLTFLoader and stage textures in software WebGL.

Fixtures are generated in memory and served on loopback; no game files or TTS.
"""
import base64
from collections import Counter
from http.server import ThreadingHTTPServer
import json
import struct
import threading
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from tools import test_resource_loading as resources
from tools.test_lottie_loading import animation

FixtureHandler, PNG = resources.FixtureHandler, resources.PNG


def model(image=None, empty=False):
    vertices = struct.pack('<9f', -1, -1, 0, 1, -1, 0, 0, 1, 0)
    data = {'asset': {'version': '2.0'}, 'scene': 0,
            'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
            'buffers': [{'byteLength': len(vertices), 'uri':
                        'data:application/octet-stream;base64,' + base64.b64encode(vertices).decode()}],
            'bufferViews': [{'buffer': 0, 'byteLength': len(vertices)}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3,
                           'type': 'VEC3', 'min': [-1, -1, 0], 'max': [1, 1, 0]}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}],
            'materials': [{'doubleSided': True, 'pbrMetallicRoughness': {
                'baseColorFactor': [1, .1, .1, 1], 'metallicFactor': 0}}]}
    if empty:
        data['nodes'] = [{}]
    if image:
        data['images'] = [{'uri': image}]
        data['textures'] = [{'source': 0}]
        data['materials'][0]['pbrMetallicRoughness']['baseColorTexture'] = {'index': 0}
    chunk = json.dumps(data).encode()
    chunk += b' ' * (-len(chunk) % 4)
    return struct.pack('<III', 0x46546C67, 2, 20 + len(chunk)) + struct.pack('<II', len(chunk), 0x4E4F534A) + chunk


class SceneHandler(FixtureHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if not (path.startswith('/_game/maps/__test_') or path.startswith('/assets/tex/__test_')):
            return super().do_GET()
        with self.server.lock:
            self.server.requests[path] += 1
        if 'stall' in path:
            self.server.stop.wait(40)
            return
        if 'slow' in path:
            self.server.stop.wait(.15)
        status = 404 if 'missing' in path else 200
        body = model() if path.endswith('.glb') else PNG.getvalue()
        if 'broken' in path or status == 404:
            body = b'not a resource'
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class SceneLoadingTests(unittest.TestCase):
    # Reuse fixture helpers, not the test class (no inherited duplicate tests).
    setUp = resources.ResourceLoadingTests.setUp
    tearDown = resources.ResourceLoadingTests.tearDown
    reload = resources.ResourceLoadingTests.reload
    outcome = resources.ResourceLoadingTests.outcome

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), SceneHandler)
        cls.server.stop = threading.Event()
        cls.server.lock = threading.Lock()
        cls.server.requests = Counter()
        cls.addClassCleanup(cls.server.server_close)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.thread.join)
        cls.addClassCleanup(cls.server.shutdown)
        cls.addClassCleanup(cls.server.stop.set)
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(args=[
            '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        cls.addClassCleanup(cls.browser.close)

    def data(self, **item):
        result = resources.ResourceLoadingTests.data(scene={'camera': False, 'items': [dict(
            type='model', id='fixture', x=100, y=300, w=128, h=128, yaw=0, **item)]})
        result['http'] = self.origin + '/'
        return result

    def hero(self, **kwargs):
        return self.data(glb=[base64.b64encode(model(**kwargs)).decode()])

    def lottie(self, **kwargs):
        data = self.data()
        data['segs'][0]['scene']['items'][0].update(type='lottie', data=animation(), **kwargs)
        return data

    def test_integrated_lottie_ready_before_seek(self):
        self.assertEqual(self.outcome('init(arg)', self.lottie(start=.25)), {'ok': True})
        self.page.evaluate('seek(.75)')
        result = self.page.evaluate('''() => {
            const a = lottie.getRegisteredAnimations()[0];
            return {ready:a.isLoaded, frame:a.currentFrame, svg:!!document.querySelector('[data-sid="fixture"] svg')};
        }''')
        self.assertEqual(result, {'ready': True, 'frame': 15, 'svg': True})

    def test_integrated_lottie_image_failure_rejects_init(self):
        data = self.lottie()
        data['segs'][0]['scene']['items'][0]['data'] = animation('/__resources__/missing.png')
        result = self.outcome('init(arg)', data)
        self.assertFalse(result['ok'])
        self.assertIn('Lottie fixture', result['error'])
        self.assertIn('missing.png', result['error'])

    def stage(self, **kwargs):
        data = self.data()
        data['segs'][0]['scene']['items'][0].update(
            type='stage', actors=[], bed='__test_good', bank='__test_slow')
        data['segs'][0]['scene']['items'][0].update(kwargs)
        return data

    def test_valid_glb_can_render_visible_geometry(self):
        self.assertEqual(self.outcome('init(arg)', self.hero()), {'ok': True})
        self.page.evaluate('seek(.5)')
        visible = self.page.evaluate('''() => {
            const canvas = document.querySelector('[data-sid="fixture"] canvas');
            const target = document.createElement('canvas'); target.width=128; target.height=128;
            const ctx = target.getContext('2d'); ctx.drawImage(canvas,0,0);
            const rgba=ctx.getImageData(0,0,128,128).data;
            return [...rgba].filter((v,i)=>i%4===3 && v>0).length;
        }''')
        self.assertGreater(visible, 100)

    def test_bad_glb_and_empty_model_fail_by_name(self):
        for data in (self.data(glb=[]), self.data(glb=['not base64!']),
                     self.data(glb=[base64.b64encode(b'bad glb').decode()]), self.hero(empty=True)):
            with self.subTest(data=str(data)[:100]):
                self.reload()
                result = self.outcome('init(arg)', data)
                self.assertFalse(result['ok'])
                self.assertIn('Модель fixture', result['error'])

    def test_requested_missing_clip_does_not_fallback(self):
        data = self.hero()
        data['segs'][0]['scene']['items'][0]['anim'] = 'missing_walk'
        result = self.outcome('init(arg)', data)
        self.assertFalse(result['ok'])
        self.assertIn('missing_walk', result['error'])

    def test_missing_and_corrupt_gltf_texture_fail(self):
        for name in ('missing', 'broken'):
            with self.subTest(name=name):
                self.reload()
                url = self.origin + '/__resources__/' + name + '.png'
                result = self.outcome('init(arg)', self.hero(image=url))
                self.assertFalse(result['ok'])
                self.assertIn(url, result['error'])

    def test_delayed_gltf_texture_is_ready(self):
        url = self.origin + '/__resources__/slow.png'
        self.assertEqual(self.outcome('init(arg)', self.hero(image=url)), {'ok': True})
        with self.server.lock:
            self.assertGreater(self.server.requests['/__resources__/slow.png'], 0)

    def test_missing_and_corrupt_map_fail(self):
        for name in ('missing', 'broken'):
            with self.subTest(name=name):
                self.reload()
                result = self.outcome('init(arg)', self.stage(map='__test_' + name))
                self.assertFalse(result['ok'])
                self.assertIn('_game/maps/__test_' + name + '.glb', result['error'])

    def test_map_does_not_request_unused_bed_and_bank(self):
        with self.server.lock:
            before = self.server.requests.copy()
        data = self.stage(map='__test_good', bed='__test_unused_missing', bank='__test_unused_broken')
        self.assertEqual(self.outcome('init(arg)', data), {'ok': True})
        self.page.evaluate('seek(.5)')
        with self.server.lock:
            delta = self.server.requests - before
        self.assertFalse(any('/assets/tex/' in path for path in delta), delta)

    def test_procedural_stage_waits_for_both_textures(self):
        self.assertEqual(self.outcome('init(arg)', self.stage()), {'ok': True})
        self.page.evaluate('seek(.5)')
        with self.server.lock:
            for name in ('good', 'slow'):
                self.assertGreater(self.server.requests['/assets/tex/__test_' + name + '.jpg'], 0)

    def test_missing_and_broken_stage_texture_fail(self):
        for name in ('missing', 'broken'):
            with self.subTest(name=name):
                self.reload()
                result = self.outcome('init(arg)', self.stage(bank='__test_' + name))
                self.assertFalse(result['ok'])
                self.assertIn('assets/tex/__test_' + name + '.jpg', result['error'])

    def test_real_stalled_resources_have_bounded_wait(self):
        for label, data in (
            ('GLB 1', self.hero(image=self.origin + '/__resources__/stall.png')),
            ('_game/maps/__test_stall.glb', self.stage(map='__test_stall')),
            ('assets/tex/__test_stall.jpg', self.stage(bank='__test_stall'))):
            with self.subTest(label=label):
                self.reload()
                self.page.clock.install()
                self.page.evaluate('''data => {
                    window.result = null;
                    init(data).then(()=>window.result={ok:true},e=>window.result={ok:false,error:e.message});
                }''', data)
                self.page.wait_for_timeout(200)
                self.assertIsNone(self.page.evaluate('window.result'))
                self.page.clock.fast_forward(30001)
                result = self.page.evaluate('window.result')
                self.assertFalse(result['ok'])
                self.assertIn(label, result['error'])
                self.assertIn('30000', result['error'])


if __name__ == '__main__':
    unittest.main()
