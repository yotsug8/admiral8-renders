"""Real browser regressions for stale media and conflicting transition layers."""
import base64
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class SegmentVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(args=['--allow-file-access-from-files', '--disable-gpu'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1080, 'height': 1920})
        self.addCleanup(self.page.close)
        self.page.goto((ROOT / 'video.html').as_uri())

    def init_scene(self, theme='', transition='push', clip=False):
        stream = BytesIO()
        Image.new('RGB', (8, 8), 'red').save(stream, format='PNG')
        uri = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
        item = dict(type='video', id='clip', x=100, y=300, w=200, h=200, hold=False,
                    clip=dict(fps=30, frames=[uri] * 200))
        segments = [dict(start=i*3, dur=3, words=[], headline='', at=[], hook=False, outro=False,
                         scene=dict(camera=False, items=[item] if clip and i == 0 else []))
                    for i in range(2)]
        self.page.evaluate('d => init(d)', dict(watermark='', theme=theme,
                                              transition=transition, segs=segments))

    def seek(self, time):
        self.page.evaluate('t => seek(t)', time)

    def test_clip_hidden_after_cut_and_restored_on_reverse_seek(self):
        self.init_scene(clip=True)
        clip = self.page.locator('.vidbox')
        self.seek(1.5)
        self.assertTrue(clip.is_visible())
        for time in (3, 4.5, 1.5, 3, 1.5):
            self.seek(time)
            self.assertEqual(clip.is_visible(), time < 3)

    def test_explicitly_visible_nested_child_cannot_escape_inactive_segment(self):
        self.init_scene()
        self.page.evaluate('''() => {
            const child = document.createElement('div');
            child.id='explicit-visible';
            child.style.cssText='visibility:visible;width:100px;height:100px;background:red';
            document.querySelector('.seg').appendChild(child);
        }''')
        self.seek(1.5)
        self.assertTrue(self.page.locator('#explicit-visible').is_visible())
        self.seek(4.5)
        self.assertFalse(self.page.locator('#explicit-visible').is_visible())

    def test_custom_transition_hides_theme_layers_and_legacy_mode_still_works(self):
        for theme, layer in [('k', 'tide'), ('c', 'ring')]:
            with self.subTest(theme=theme):
                self.page.goto((ROOT / 'video.html').as_uri())
                self.init_scene(theme=theme)
                for time in (1.5, 2.9, 3, 4.5, 1.5):
                    self.seek(time)
                    for name in ('tide', 'ring'):
                        self.assertFalse(self.page.locator('#' + name).is_visible())
                self.page.evaluate('D.transition = null')
                self.seek(2.9)
                self.assertTrue(self.page.locator('#' + layer).is_visible())
                self.seek(1.5)
                self.assertFalse(self.page.locator('#' + layer).is_visible())


if __name__ == '__main__':
    unittest.main()
