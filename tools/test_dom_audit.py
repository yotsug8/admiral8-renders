"""Exercise the rendered DOM audit in Chromium, without external assets or voices."""
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class DOMAuditTests(unittest.TestCase):
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
        self.page.evaluate('''() => init({watermark:'', segs:[{
            start:0, dur:5, words:[], headline:'', at:[],
            scene:{camera:false, items:[]}
        }]})''')
        self.page.evaluate('seek(2)')

    def box(self, x=59, y=300, w=100, h=100, kind='pic', parent='', child=''):
        self.page.evaluate('''d => {
            document.getElementById('fixture')?.remove();
            const wrap = document.createElement('div');
            wrap.id = 'fixture'; wrap.style.cssText = d.parent;
            const box = document.createElement(d.kind === 'hero' ? 'img' : 'div');
            box.className = d.kind;
            box.style.cssText = `position:absolute;left:${d.x}px;top:${d.y}px;width:${d.w}px;height:${d.h}px;${d.child}`;
            wrap.appendChild(box); SEGS[0].el.appendChild(wrap);
        }''', dict(x=x, y=y, w=w, h=h, kind=kind, parent=parent, child=child))

    def audit(self):
        return self.page.evaluate('audit()')

    def test_exact_safe_rectangle_and_one_pixel_outside_each_edge(self):
        for rect in [(60, 150, 880, 1410), (59, 300, 100, 100),
                     (841, 300, 100, 100), (100, 149, 100, 100), (100, 1461, 100, 100)]:
            with self.subTest(rect=rect):
                self.box(*rect)
                self.assertEqual(len(self.audit()), 0 if rect[0] == 60 else 1)

    def test_ancestor_hiding_and_composed_opacity(self):
        for parent, child in [('display:none', ''), ('opacity:0', ''),
                              ('visibility:hidden', ''), ('content-visibility:hidden', ''),
                              ('opacity:.97', 'opacity:.97')]:
            with self.subTest(parent=parent):
                self.box(parent=parent, child=child)
                self.assertEqual(self.audit(), [])
        self.box(parent='opacity:.99', child='opacity:.99')
        self.assertEqual(len(self.audit()), 1)
        # content-visibility hides descendants, but not the element's own background box.
        self.box(child='content-visibility:hidden;background:red')
        self.assertEqual(len(self.audit()), 1)

    def test_explicit_visibility_override_is_still_audited(self):
        self.box(parent='visibility:hidden', child='visibility:visible')
        self.assertEqual(len(self.audit()), 1)

    def test_model_animation_and_hero_bounds_are_included(self):
        for kind in ('modelbox', 'animbox', 'hero'):
            with self.subTest(kind=kind):
                self.box(kind=kind)
                self.assertEqual(len(self.audit()), 1)

    def test_stage_exemption_is_per_registered_box(self):
        self.box(x=0, y=0, w=1080, h=1920, kind='modelbox')
        self.assertEqual(len(self.audit()), 1)
        self.page.evaluate("SEGS[0].sc.stages = [{box:document.querySelector('#fixture > div')}]")
        self.assertEqual(self.audit(), [])
        self.box(kind='modelbox')
        self.assertEqual(len(self.audit()), 1)

    def test_hidden_subtitle_does_not_trigger_false_text_overlap(self):
        self.box(x=100, y=300, kind='note', child='font:30px sans-serif')
        self.page.evaluate('''() => {
            document.querySelector('#fixture > div').textContent = 'Label';
            const subs = document.getElementById('subs');
            subs.style.cssText = 'position:absolute;left:100px;top:300px;width:100px;justify-content:flex-start;opacity:0';
            subs.innerHTML = '<span style="display:block;width:100px;height:100px">Words</span>';
        }''')
        self.assertEqual(self.audit(), [])
        self.page.evaluate("document.getElementById('subs').style.opacity = 1")
        self.assertTrue(any('наложение' in issue for issue in self.audit()))


if __name__ == '__main__':
    unittest.main()
