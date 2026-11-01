"""F09: real vendored Lottie/Chromium, loopback only; no pipeline integration required.

Run: python -B -m unittest tools.test_lottie_loading -v
Fixtures live in memory. Clock fast-forward changes time, not loading or decoding.
"""
from collections import Counter
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PNG = BytesIO()
Image.new('RGBA', (8, 8), (220, 40, 60, 255)).save(PNG, 'PNG')


def animation(image=None):
    ks = dict(o={'a': 0, 'k': 100}, r={'a': 0, 'k': 0},
              p={'a': 1, 'k': [{'t': 0, 's': [0, 0, 0], 'h': 1},
                               {'t': 10, 's': [40, 0, 0], 'h': 1}]},
              a={'a': 0, 'k': [0, 0, 0]}, s={'a': 0, 'k': [100, 100, 100]})
    layer = dict(ty=1, ind=1, ip=0, op=30, st=0, sr=1, ks=ks,
                 sw=20, sh=20, sc='#dc283c')
    assets = []
    if image:
        layer.update(ty=2, refId='picture')
        assets = [dict(id='picture', w=8, h=8, u='', p=image, e=0)]
    return dict(v='5.13.0', w=100, h=100, fr=30, ip=0, op=30,
                layers=[layer], assets=assets)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        with self.server.lock:
            self.server.requests[path] += 1
            count = self.server.requests[path]
            self.server.seen.setdefault((path, count), threading.Event()).set()
        name = path.rsplit('/', 1)[-1]
        if name == 'stall.png':
            self.server.stop.wait(40)
            return
        if name == 'gate-preload.png':
            self.server.release.wait(5)
        status = 404 if name == 'missing.png' else 200
        if name == 'page.html':
            body = b'<style>body{margin:0}#box{width:100px;height:100px}</style><div id="box"></div>'
            kind = 'text/html'
        else:
            body = b'broken PNG' if name in ('broken.png', 'missing.png') else PNG.getvalue()
            kind = 'image/png'
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


# Instrument ownership, without replacing Lottie, Image, decoding or event delivery.
PROBE = r"""() => {
    window.probe = {timers:new Set(), imageListeners:new Map(), listeners:new Map(),
        instances:[], destroyed:0};
    const st = window.setTimeout, ct = window.clearTimeout;
    window.setTimeout = (fn, ms, ...args) => {
        let id = st(() => { probe.timers.delete(id); fn(...args); }, ms);
        if (ms === 30000) probe.timers.add(id);
        return id;
    };
    window.clearTimeout = id => { probe.timers.delete(id); ct(id); };
    const add = EventTarget.prototype.addEventListener;
    const remove = EventTarget.prototype.removeEventListener;
    EventTarget.prototype.addEventListener = function(type, fn, ...args) {
        if (this instanceof HTMLImageElement && ['load','error'].includes(type)) {
            if (!probe.imageListeners.has(this)) probe.imageListeners.set(this, new Set());
            probe.imageListeners.get(this).add(fn);
        }
        return add.call(this, type, fn, ...args);
    };
    EventTarget.prototype.removeEventListener = function(type, fn, ...args) {
        probe.imageListeners.get(this)?.delete(fn);
        return remove.call(this, type, fn, ...args);
    };
    const load = lottie.loadAnimation;
    lottie.loadAnimation = function(params) {
        const a = load.call(this, params);
        probe.instances.push(a);
        const add = a.addEventListener, remove = a.removeEventListener, destroy = a.destroy;
        a.addEventListener = function(type, fn) {
            probe.listeners.set(fn, type); return add.call(this, type, fn);
        };
        a.removeEventListener = function(type, fn) {
            probe.listeners.delete(fn); return remove.call(this, type, fn);
        };
        a.destroy = function(...args) { probe.destroyed++; return destroy.apply(this, args); };
        return a;
    };
}"""


class LottieLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.stop = threading.Event()
        cls.server.release = threading.Event()
        cls.server.lock = threading.Lock()
        cls.server.requests = Counter()
        cls.server.seen = {}
        cls.addClassCleanup(cls.server.server_close)
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)
        cls.addClassCleanup(cls.server.stop.set)
        cls.addClassCleanup(cls.server.release.set)
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(args=['--disable-gpu'])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 120, 'height': 120})
        self.addCleanup(self.page.close)
        self.external = []
        self.errors = []

        def local_only(route):
            if route.request.url.startswith(self.origin + '/'):
                route.continue_()
            else:
                self.external.append(route.request.url)
                route.abort()

        self.page.route('**/*', local_only)
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.reload()

    def reload(self):
        self.server.release.set()
        self.page.goto(self.origin + '/fixtures/page.html')
        with self.server.lock:
            self.server.requests.clear()
            self.server.seen.clear()
        self.server.release.clear()
        self.page.add_script_tag(path=str(ROOT / 'vendor/lottie/lottie_light.min.js'))
        self.page.add_script_tag(path=str(ROOT / 'scene_lottie.js'))
        self.page.evaluate(PROBE)

    def tearDown(self):
        self.server.release.set()
        self.assertEqual(self.external, [], 'No external networks allowed')
        self.assertEqual(self.errors, [], 'Unhandled browser exceptions')

    def start(self, data, **item):
        self.page.evaluate('''it => {
            window.o = {it, box:document.getElementById('box')};
            window.original = JSON.stringify(it.data);
            window.result = null;
            loadSceneLottie(o).then(() => { window.result = {ok:true}; }, e => {
                window.result = {ok:false, name:e.name, id:e.id, error:e.message};
            });
        }''', dict(id='fixture-lottie', data=data, **item))

    def result(self):
        self.page.wait_for_function('window.result !== null', timeout=2500)
        return self.page.evaluate('window.result')

    def assert_clean(self, success, destroyed=None):
        actual = self.page.evaluate('''() => ({
            timers:probe.timers.size, listeners:probe.listeners.size,
            imageListeners:[...probe.imageListeners.values()].reduce((n,s) => n+s.size, 0),
            unchanged:JSON.stringify(o.it.data) === original,
            assigned:!!o.a, registered:lottie.getRegisteredAnimations().length,
            destroyed:probe.destroyed,
        })''')
        self.assertEqual(actual['timers'], 0, actual)
        self.assertEqual(actual['listeners'], 0, actual)
        self.assertEqual(actual['imageListeners'], 0, actual)
        self.assertTrue(actual['unchanged'], actual)
        self.assertEqual(actual['assigned'], success, actual)
        self.assertEqual(actual['registered'], int(success), actual)
        if destroyed is not None:
            self.assertEqual(actual['destroyed'], destroyed, actual)

    def assert_error(self, result, contains):
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['name'], 'SceneLottieLoadError')
        self.assertEqual(result['id'], 'fixture-lottie')
        self.assertIn('fixture-lottie', result['error'])
        self.assertIn(contains, result['error'])
        self.assert_clean(False)

    def await_request(self, path, count=1):
        with self.server.lock:
            event = self.server.seen.setdefault((path, count), threading.Event())
        # Pump Playwright routing while waiting for the loopback server.
        for _ in range(100):
            if event.is_set():
                return
            self.page.wait_for_timeout(10)
        self.fail(f'Expected actual pending HTTP request: {path} #{count}')

    def pixel(self, x, y):
        return Image.open(BytesIO(self.page.screenshot())).convert('RGB').getpixel((x, y))

    def test_svg_ready_frame_seek_and_fit(self):
        for fit, expected in [('contain', 'xMidYMid meet'), ('cover', 'xMidYMid slice')]:
            with self.subTest(fit=fit):
                self.reload()
                self.start(animation(), fit=fit)
                self.assertEqual(self.result(), {'ok': True})
                state = self.page.evaluate('''() => ({loaded:o.a.isLoaded, paused:o.a.isPaused,
                    loop:o.a.loop, autoplay:o.a.autoplay,
                    fit:o.box.querySelector('svg').getAttribute('preserveAspectRatio')})''')
                self.assertEqual(state, dict(loaded=True, paused=True, loop=False, autoplay=False, fit=expected))
                self.assertEqual(self.pixel(5, 5), (220, 40, 60))
                self.page.evaluate('o.a.goToAndStop(15, true)')
                self.assertEqual(self.page.evaluate('o.a.currentFrame'), 15)
                self.assertEqual(self.pixel(5, 5), (255, 255, 255))
                self.assertEqual(self.pixel(45, 5), (220, 40, 60))
                self.assert_clean(True, destroyed=0)

    def test_image_paths_copy_and_nested_composition(self):
        for base in [None, self.origin + '/source/animation/', '../source/animation']:
            with self.subTest(base=base):
                self.reload()
                data = animation('good.png')
                data['assets'][0]['u'] = 'images/'
                child = deepcopy(data['layers'][0])
                data['assets'].append(dict(id='comp', layers=[child]))
                data['layers'][0].update(ty=0, refId='comp', w=100, h=100)
                kwargs = {'assetBase': base} if base else {}
                self.start(data, **kwargs)
                self.assertEqual(self.result(), {'ok': True})
                prefix = '/source/animation/' if base else '/fixtures/'
                expected = self.origin + prefix + 'images/good.png'
                self.assertEqual(self.page.evaluate('o.a.animationData.assets[0].p'), expected)
                self.assertEqual(self.pixel(3, 3), (220, 40, 60))
                self.assert_clean(True)

    def test_embedded_and_absolute_image_paths(self):
        import base64
        embedded = 'data:image/png;base64,' + base64.b64encode(PNG.getvalue()).decode('ascii')
        for path in [embedded, self.origin + '/absolute/good.png', '/root/good.png']:
            with self.subTest(path=path[:60]):
                self.reload()
                data = animation(path)
                data['assets'][0].update(u='ignored/', e=int(path == embedded))
                self.start(data, assetBase=self.origin + '/source/')
                self.assertEqual(self.result(), {'ok': True})
                self.assertEqual(self.pixel(3, 3), (220, 40, 60))
                self.assert_clean(True)

    def test_missing_and_corrupt_images(self):
        for name in ['missing.png', 'broken.png']:
            with self.subTest(name=name):
                self.reload()
                self.start(animation(name))
                self.assert_error(self.result(), name)

    def test_delayed_success_waits_for_image(self):
        # Chromium can reuse decoded HTML images for SVG despite no-store.
        # Do not assume a second HTTP request for the same image.
        self.start(animation('gate-preload.png'))
        self.await_request('/fixtures/gate-preload.png')
        self.assertIsNone(self.page.evaluate('window.result'))
        self.assertFalse(self.page.evaluate('!!o.a'))
        self.server.release.set()
        self.assertEqual(self.result(), {'ok': True})
        self.assertEqual(self.pixel(3, 3), (220, 40, 60))
        self.assert_clean(True)

    def test_bad_json_and_metadata(self):
        cases = ['{broken', None, [], {}]
        for key, value in [('v', None), ('fr', 0), ('fr', '30'), ('w', -1), ('h', 0),
                           ('ip', None), ('op', 0), ('op', .5), ('layers', {}),
                           ('assets', {}), ('assets', [None]), ('layers', [None])]:
            data = animation()
            data[key] = value
            cases.append(data)
        for data in cases:
            with self.subTest(data=data):
                self.reload()
                self.start(data)
                self.assert_error(self.result(), 'Lottie fixture-lottie:')
                self.assertEqual(self.page.evaluate('probe.instances.length'), 0)

    def test_missing_image_reference_and_path(self):
        for change in ['reference', 'path']:
            with self.subTest(change=change):
                self.reload()
                data = animation('good.png')
                if change == 'reference':
                    data['layers'][0]['refId'] = 'missing-asset'
                else:
                    data['assets'][0]['p'] = ''
                self.start(data)
                self.assert_error(self.result(), 'image asset')

    def test_real_lottie_configuration_error_is_caught_and_destroyed(self):
        # SVG's actual createCamera throws; no synthetic error event is dispatched.
        data = animation()
        data['layers'][0]['ty'] = 13
        self.start(data)
        self.assert_error(self.result(), '3d camera')
        self.assert_clean(False, destroyed=1)

    def test_timeout_on_real_pending_image(self):
        self.page.clock.install()
        self.start(animation('stall.png'))
        self.await_request('/fixtures/stall.png')
        self.assertIsNone(self.page.evaluate('window.result'))
        self.page.clock.fast_forward(30001)
        self.assert_error(self.result(), '30000')
        self.assert_clean(False, destroyed=0)
        self.assertFalse(self.page.evaluate('!!o.a'))

    def test_sibling_image_failure_cleans_pending_preload(self):
        data = animation('stall.png')
        data['assets'].append(dict(id='bad', w=8, h=8, u='', p='broken.png'))
        self.start(data)
        self.assert_error(self.result(), 'broken.png')
        self.assert_clean(False, destroyed=0)


if __name__ == '__main__':
    unittest.main()
