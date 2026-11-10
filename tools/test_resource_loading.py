"""F09 browser regressions: real Chromium/Three.js, loopback fixtures, no TTS.

Run: python -m unittest tools.test_resource_loading -v
Timeout tests advance the browser clock; image loading/decoding is never mocked.
"""
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PNG = BytesIO()
Image.new('RGBA', (8, 8), (220, 40, 60, 255)).save(PNG, format='PNG')


class FixtureHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if not path.startswith('/__resources__/'):
            return super().do_GET()
        with self.server.lock:
            self.server.requests[path] += 1
        name = path.rsplit('/', 1)[-1]
        if name.startswith('stall'):
            self.server.stop.wait(40)
            return
        if name.startswith('slow'):
            self.server.stop.wait(.15)
        status = 404 if 'missing' in name else 200
        body = b'not an image' if 'broken' in name or status == 404 else PNG.getvalue()
        self.send_response(status)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class ResourceLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
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
        cls.browser = cls.driver.chromium.launch(args=['--disable-gpu'])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1080, 'height': 1920})
        self.addCleanup(self.page.close)
        self.external = []

        def local_only(route):
            if route.request.url.startswith(self.origin + '/'):
                route.continue_()
            else:
                self.external.append(route.request.url)
                route.abort()

        self.page.route('**/*', local_only)
        self.page.on('pageerror', lambda error: self.failures.append(str(error)))
        self.failures = []
        self.reload()

    def tearDown(self):
        self.assertEqual(self.external, [], 'External requests are forbidden')
        self.assertEqual(self.failures, [], 'Unhandled browser exceptions')

    def reload(self):
        self.page.goto(self.origin + '/video.html')
        self.page.wait_for_function('window.T3 !== undefined')
        self.page.evaluate('document.fonts.ready')

    @staticmethod
    def src(name):
        return '/__resources__/' + name + '.png'

    @staticmethod
    def data(**segment):
        return {'watermark': '', 'segs': [dict(start=0, dur=5, words=[],
                                             headline='', at=[], **segment)]}

    def scene(self, name):
        return self.data(scene={'camera': False, 'items': [
            {'type': 'img', 'src': self.src(name), 'x': 100, 'y': 300, 'w': 80, 'h': 80}]})

    def mosaic(self, hero='good', icon='good'):
        return self.data(layout='mosaic', visual={
            'heroes': [self.src(hero)], 'icons': {'src': self.src(icon), 'count': 250},
            'number': '250', 'caption': '', 'note': ''})

    def outcome(self, expression, argument=None):
        # This watchdog makes regressions fail instead of hanging page.evaluate forever.
        return self.page.evaluate('''async arg => {
            let timer;
            try { return await Promise.race([
                (async () => { try { await (EXPRESSION); return {ok:true}; }
                    catch (e) { return {ok:false, error:e.message}; } })(),
                new Promise(resolve => { timer = setTimeout(() => resolve(
                    {ok:false, error:'TEST WATCHDOG: promise did not settle'}), 2000); })
            ]); } finally { clearTimeout(timer); }
        }'''.replace('EXPRESSION', expression), argument)

    def assert_resource_error(self, result, name, timeout=False):
        self.assertFalse(result['ok'], result)
        self.assertIn(self.src(name), result['error'])
        if timeout:
            self.assertIn('30000', result['error'])
        else:
            self.assertNotIn('30000', result['error'])

    def test_dom_missing_and_corrupt_fail_init(self):
        for name in ('slow-missing', 'slow-broken'):
            with self.subTest(name=name):
                self.reload()
                self.assert_resource_error(self.outcome('init(arg)', self.scene(name)), name)

    def test_dom_already_complete_broken_is_not_success(self):
        self.page.evaluate('''src => new Promise(resolve => {
            const im = new Image(); im.onerror = resolve; im.src = src;
            document.getElementById('preload').appendChild(im);
        })''', self.src('broken'))
        self.assertEqual(self.page.evaluate('''() => {
            const im = document.images[0]; return [im.complete, im.naturalWidth];
        }'''), [True, 0])
        self.assert_resource_error(self.outcome('init(arg)', self.data(scene={'items': []})), 'broken')

    def test_dom_empty_source_fails(self):
        self.page.evaluate("document.getElementById('preload').appendChild(new Image())")
        result = self.outcome('init(arg)', self.data(scene={'items': []}))
        self.assertFalse(result['ok'])
        self.assertIn('src', result['error'])

    def test_healthy_dom_and_preloaded_frames_draw(self):
        src = self.src('good')
        items = [dict(type=kind, src=src, x=100, y=200 + i * 100, w=80, h=80)
                 for i, kind in enumerate(('img', 'hero', 'card'))]
        items += [dict(type='anim', x=100, y=600, w=80, h=80, anim={'frames': [src], 'fps': 1}),
                  dict(type='video', x=100, y=700, w=80, h=80, clip={'frames': [src], 'fps': 1})]
        self.assertEqual(self.outcome('init(arg)', self.data(scene={'camera': False, 'items': items})), {'ok': True})
        actual = self.page.evaluate('''() => {
            seek(2);
            return {images:[...document.images].map(im => [im.naturalWidth, im.naturalHeight]),
                pixels:[...document.querySelectorAll('.animbox canvas,.vidbox canvas')]
                    .map(cv => [...cv.getContext('2d').getImageData(1,1,1,1).data])};
        }''')
        self.assertEqual(actual['images'], [[8, 8]] * 5)
        self.assertEqual(actual['pixels'], [[220, 40, 60, 255]] * 2)

    def test_preloaded_anim_and_video_bad_frame_fail_init(self):
        for kind in ('anim', 'video'):
            with self.subTest(kind=kind):
                self.reload()
                item = dict(type=kind, x=100, y=300, w=80, h=80)
                item['anim' if kind == 'anim' else 'clip'] = {
                    'frames': [self.src('good'), self.src('slow-broken')], 'fps': 1}
                self.assert_resource_error(self.outcome('init(arg)', self.data(scene={'items': [item]})), 'slow-broken')

    def test_mosaic_pending_errors_reject_even_if_other_image_stalls(self):
        for hero, icon in [('slow-missing', 'good'), ('good', 'slow-broken'),
                           ('stall-hero', 'slow-broken')]:
            with self.subTest(hero=hero, icon=icon):
                self.reload()
                name = 'slow-missing' if hero == 'slow-missing' else 'slow-broken'
                self.assert_resource_error(self.outcome('init(arg)', self.mosaic(hero, icon)), name)

    def test_mosaic_already_complete_broken_images_reject_before_drawing(self):
        for bad_part in ('hero', 'icon'):
            with self.subTest(part=bad_part):
                self.reload()
                self.page.evaluate('''async ({src, part}) => {
                    const hero = new Image(), icon = new Image();
                    await Promise.all([hero,icon].map((im,i) => new Promise(resolve => {
                        im.onload = im.onerror = resolve;
                        im.src = (i === (part === 'hero' ? 0 : 1)) ? src : '/__resources__/good.png';
                    })));
                    window.fixture = {parts:{hero,icon,cv:document.createElement('canvas')},
                        s:{visual:{icons:{count:10}}}};
                }''', {'src': self.src('broken'), 'part': bad_part})
                result = self.outcome('buildMosaic(window.fixture)')
                self.assert_resource_error(result, 'broken')
                self.assertIn(bad_part, result['error'])

    def test_healthy_mosaic_builds_and_draws(self):
        self.assertEqual(self.outcome('init(arg)', self.mosaic()), {'ok': True})
        actual = self.page.evaluate('''() => {
            seek(4.9); const P = SEGS[0].parts;
            return {count:P.pts.length, finite:P.lensAt.every(Number.isFinite),
                alpha:P.ctx.getImageData(500,365,1,1).data[3]};
        }''')
        self.assertEqual(actual, {'count': 250, 'finite': True, 'alpha': 255})

    def setup_map(self, name='good', slot='g_tColor0'):
        self.page.evaluate('''({name,slot}) => {
            const {THREE} = T3, root = new THREE.Group();
            const params = Object.fromEntries([0,1,2,3].map(i => ['g_tColor'+i, 'good.vtex']));
            params.g_tTintMasks = 'good.vtex'; params[slot] = name + '.vtex';
            const mat = new THREE.MeshBasicMaterial();
            mat.userData.vmat = {ShaderName:'multiblend.vfx', TextureParams:params,
                IntParams:{F_TINT_MASK:1}};
            root.add(new THREE.Mesh(new THREE.PlaneGeometry(1,1), mat));
            window.mapFixture = {root, prepare: () => T3.prepareDotaMap(THREE, root, '/__resources__/')};
        }''', {'name': name, 'slot': slot})

    def test_map_missing_and_corrupt_color_or_mask_reject_ready(self):
        for name, slot in [('slow-missing', 'g_tColor3'), ('slow-broken', 'g_tTintMasks')]:
            with self.subTest(name=name, slot=slot):
                self.reload()
                self.setup_map(name, slot)
                result = self.outcome('mapFixture.prepare().ready')
                self.assert_resource_error(result, name)

    def test_healthy_map_waits_for_decoded_textures_and_reuses_request(self):
        with self.server.lock:
            before = self.server.requests[self.src('slow-good')]
        self.setup_map()
        self.page.evaluate('''() => {
            const v = mapFixture.root.children[0].material.userData.vmat;
            for (const k of Object.keys(v.TextureParams)) v.TextureParams[k] = 'slow-good.vtex';
        }''')
        self.assertEqual(self.outcome('mapFixture.prepare().ready'), {'ok': True})
        self.assertEqual(self.page.evaluate('''() => {
            const u = mapFixture.root.children[0].material.uniforms;
            return ['c0','c1','c2','c3','mask'].map(k => [u[k].value.image.naturalWidth,
                u[k].value.image.naturalHeight]);
        }'''), [[8, 8]] * 5)
        with self.server.lock:
            self.assertEqual(self.server.requests[self.src('slow-good')] - before, 1)

    def assert_stall_timeout(self, expression, argument, name):
        self.page.clock.install()
        with self.page.expect_request(self.origin + self.src(name)):
            self.page.evaluate('''arg => {
                window.settled = null;
                (EXPRESSION).then(() => window.settled = {ok:true},
                    e => window.settled = {ok:false,error:e.message});
            }'''.replace('EXPRESSION', expression), argument)
        # Allow init's fonts/microtasks to reach the image wait before advancing time.
        self.page.evaluate('document.fonts.ready')
        self.assertIsNone(self.page.evaluate('window.settled'))
        self.page.clock.fast_forward(30001)
        result = self.page.evaluate('window.settled')
        self.assertIsNotNone(result, 'Stalled resource must settle within 30 seconds')
        self.assert_resource_error(result, name, timeout=True)

    def test_dom_stalled_request_has_named_timeout(self):
        self.assert_stall_timeout('init(arg)', self.scene('stall-dom'), 'stall-dom')

    def test_mosaic_stalled_request_has_named_timeout(self):
        self.assert_stall_timeout('init(arg)', self.mosaic(icon='stall-icon'), 'stall-icon')

    def test_map_stalled_request_has_named_timeout(self):
        self.setup_map('stall-map')
        self.assert_stall_timeout('mapFixture.prepare().ready', None, 'stall-map')


if __name__ == '__main__':
    unittest.main()
