"""Real Chromium CSS/font decoding and failure handling; loopback fixtures only."""
from collections import Counter
from http.server import ThreadingHTTPServer
import threading
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from tools import test_resource_loading as resources


class Handler(resources.FixtureHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if not path.startswith('/__styles__/'):
            return super().do_GET()
        with self.server.lock:
            self.server.requests[path] += 1
        if 'stall' in path:
            self.server.stop.wait(40)
            return
        if 'slow' in path:
            self.server.stop.wait(.15)
        status = 404 if 'missing' in path else 200
        if path.endswith('.woff2'):
            body = (resources.ROOT / 'fonts/manrope-latin-600-normal.woff2').read_bytes()
            kind = 'font/woff2'
        elif path.endswith('.css'):
            body = b'.fixture { background-image: url(images/good.png); }'
            kind = 'text/css'
        else:
            body, kind = resources.PNG.getvalue(), 'image/png'
        if 'broken' in path or status != 200:
            body = b'broken resource'
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class StyleLoadingTests(unittest.TestCase):
    setUp = resources.ResourceLoadingTests.setUp
    tearDown = resources.ResourceLoadingTests.tearDown
    reload = resources.ResourceLoadingTests.reload
    outcome = resources.ResourceLoadingTests.outcome

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.stop, cls.server.lock = threading.Event(), threading.Lock()
        cls.server.requests = Counter()
        cls.addClassCleanup(cls.server.server_close)
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)
        cls.addClassCleanup(cls.server.stop.set)
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(args=['--disable-gpu'])
        cls.addClassCleanup(cls.browser.close)

    def scene(self, **kwargs):
        return resources.ResourceLoadingTests.data(scene={'camera': False, 'items': [dict(
            type='text', id='style-fixture', text='Проверка ABC', x=100, y=300,
            w=700, h=300, size=32, cls='fixture', **kwargs)]})

    def font(self, name):
        self.page.add_style_tag(content=f'''@font-face {{ font-family: FixtureFont;
            src:url("/__styles__/{name}.woff2"); font-weight:600; }}
            .fixture {{ font-family: FixtureFont; font-weight:600; }}''')

    def assert_failed(self, result, part):
        self.assertFalse(result['ok'], result)
        self.assertIn(part, result['error'])
        self.assertNotIn('TEST WATCHDOG', result['error'])

    def test_background_and_mask_errors_are_not_ignored(self):
        for prop in ('background-image', 'mask-image', 'border-image-source'):
            for name in ('missing', 'broken'):
                with self.subTest(prop=prop, name=name):
                    self.reload()
                    self.page.add_style_tag(content=f'.fixture {{{prop}:url("/__styles__/{name}.png")}}')
                    self.assert_failed(self.outcome('init(arg)', self.scene()), f'{name}.png')

    def test_generated_content_and_pseudo_background_are_checked(self):
        for declaration in ('content:url("/__styles__/missing.png")',
                            'content:""; background-image:url("/__styles__/broken.png")'):
            with self.subTest(declaration=declaration):
                self.reload()
                self.page.add_style_tag(content=f'.fixture::after {{{declaration}}}')
                result = self.outcome('init(arg)', self.scene())
                self.assert_failed(result, '::after')

    def test_later_hidden_segment_background_is_checked(self):
        data = self.scene()
        data['segs'].append(dict(data['segs'][0], start=5))
        self.page.add_style_tag(content='.seg:nth-child(2) .fixture {background-image:url("/__styles__/missing.png")}')
        self.assert_failed(self.outcome('init(arg)', data), 'missing.png')

    def test_layered_images_and_css_relative_paths_load(self):
        self.page.add_style_tag(url=self.origin + '/__styles__/relative.css')
        self.assertEqual(self.outcome('init(arg)', self.scene()), {'ok': True})
        self.page.evaluate('seek(.5)')
        with self.server.lock:
            self.assertGreater(self.server.requests['/__styles__/images/good.png'], 0)
        self.reload()
        self.page.add_style_tag(content='''.fixture {background-image:
            linear-gradient(red, blue), url("/__styles__/slow.png"), url("/__styles__/good.png");}''')
        self.assertEqual(self.outcome('init(arg)', self.scene()), {'ok': True})

    def test_encoded_quote_and_parenthesis_in_url(self):
        self.page.add_style_tag(content=r'''.fixture { background-image:url("/__styles__/good(1)\".png"); }''')
        self.assertEqual(self.outcome('init(arg)', self.scene()), {'ok': True})
        with self.server.lock:
            self.assertTrue(any('good(1)' in path for path in self.server.requests))

    def test_missing_and_corrupt_font_reject_init(self):
        for name in ('missing', 'broken'):
            with self.subTest(name=name):
                self.reload()
                self.font(name)
                self.assert_failed(self.outcome('init(arg)', self.scene()), 'FixtureFont')

    def test_delayed_font_loads_before_measurement(self):
        self.font('slow')
        self.assertEqual(self.outcome('init(arg)', self.scene()), {'ok': True})
        states = self.page.evaluate('[...document.fonts].map(f => f.status)')
        self.assertTrue(states and all(state == 'loaded' for state in states), states)

    def test_missing_stylesheet_is_reported(self):
        self.page.evaluate('''() => new Promise(resolve => {
            const link=document.createElement('link'); link.rel='stylesheet';
            link.href='/__styles__/missing.css'; link.onload=link.onerror=resolve;
            document.head.appendChild(link);
        })''')
        self.assert_failed(self.outcome('init(arg)', self.scene()), 'missing.css')

    def test_hung_image_and_font_have_named_timeout(self):
        for kind in ('image', 'font'):
            with self.subTest(kind=kind):
                self.reload()
                self.page.clock.install()
                if kind == 'image':
                    self.page.add_style_tag(content='.fixture {background-image:url("/__styles__/stall.png")}')
                    expected, path = 'stall.png', '/__styles__/stall.png'
                else:
                    self.font('stall')
                    expected, path = 'FixtureFont', '/__styles__/stall.woff2'
                self.page.evaluate('''data => {
                    window.result=null;
                    init(data).then(()=>window.result={ok:true}, e=>window.result={ok:false,error:e.message});
                }''', self.scene())
                for _ in range(100):
                    self.page.wait_for_timeout(10)
                    with self.server.lock:
                        if self.server.requests[path]:
                            break
                with self.server.lock:
                    self.assertGreater(self.server.requests[path], 0)
                self.assertIsNone(self.page.evaluate('window.result'))
                self.page.clock.fast_forward(30001)
                result = self.page.evaluate('window.result')
                self.assert_failed(result, expected)
                self.assertIn('30000', result['error'])


if __name__ == '__main__':
    unittest.main()
