"""The user manual: images and in-page links resolve; the HTML build embeds everything."""
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / 'docs' / 'manual' / 'USER_MANUAL.md'


def slug(heading: str) -> str:
    """Python-Markdown's default toc slug (also GitHub's for these headings)."""
    text = re.sub(r'[^\w\s-]', '', heading).strip().lower()
    return re.sub(r'[-\s]+', '-', text)


class UserManualTests(unittest.TestCase):
    def test_images_exist_and_anchors_match_headings(self):
        text = MANUAL.read_text(encoding='utf-8')
        for image in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text):
            with self.subTest(image=image):
                self.assertTrue((MANUAL.parent / image).exists())
        headings = {slug(h) for h in re.findall(r'^#{2,3} (.+)$', text, re.M)}
        for anchor in re.findall(r'\]\(#([^)]+)\)', text):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, headings)

    @unittest.skipUnless(importlib.util.find_spec('markdown'), 'markdown is not installed (requirements-build.txt)')
    def test_html_build_is_self_contained(self):
        sys.path.insert(0, str(ROOT / 'packaging'))
        from build_manual import build
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'manual.html'
            build(output)
            html = output.read_text(encoding='utf-8')
        self.assertEqual(html.count('data:image/png;base64,'),
                         len(re.findall(r'!\[', MANUAL.read_text(encoding='utf-8'))))
        self.assertNotIn('src="images/', html)
        ids = set(re.findall(r'id="([^"]+)"', html))
        self.assertLessEqual(set(re.findall(r'href="#([^"]+)"', html)), ids)


if __name__ == '__main__':
    unittest.main()
