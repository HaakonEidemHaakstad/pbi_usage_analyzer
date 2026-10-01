"""Build-time checks of the Windows app folder (skipped without the build tools)."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[1] / 'packaging'
HAS_BUILD_TOOLS = all(importlib.util.find_spec(m) for m in ('pefile', 'packaging', 'markdown'))


@unittest.skipUnless(HAS_BUILD_TOOLS, 'build tools not installed (requirements-build.lock)')
class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PACKAGING))

    def test_bundle_check_flags_network_components(self):
        from check_bundle import check
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            (app / '_internal' / 'PySide6' / 'plugins' / 'tls').mkdir(parents=True)
            (app / '_internal' / 'PySide6' / 'Qt6Network.dll').write_bytes(b'not a PE file')
            (app / '_internal' / 'PySide6' / 'plugins' / 'tls' / 'qschannelbackend.dll').write_bytes(b'x')
            (app / '_internal' / 'harmless.dll').write_bytes(b'x')
            problems = check(app)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all('network component present' in p for p in problems))

    def test_sbom_and_manifest(self):
        from write_notices import runtime_distributions, sbom, write_manifest
        dists = runtime_distributions()
        document = sbom('1.2.3', dists)
        self.assertEqual((document['bomFormat'], document['specVersion']), ('CycloneDX', '1.5'))
        purls = {c['purl'].split('@')[0] for c in document['components']}
        self.assertLessEqual({'pkg:pypi/pandas', 'pkg:pypi/openpyxl', 'pkg:pypi/pyside6-essentials',
                              'pkg:generic/python'}, purls)
        self.assertEqual(len(document['components']), len(dists) + 1)
        json.dumps(document)  # serializable
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            (app / 'sub').mkdir()
            (app / 'a.txt').write_text('a', encoding='utf-8')
            (app / 'sub' / 'b.bin').write_bytes(b'b')
            write_manifest(app)
            lines = (app / 'MANIFEST-SHA256.txt').read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines, [f"{hashlib.sha256(b'a').hexdigest()}  a.txt",
                                 f"{hashlib.sha256(b'b').hexdigest()}  sub/b.bin"])

    def test_lock_pins_every_package_with_hashes(self):
        text = (PACKAGING.parent / 'requirements-build.lock').read_text(encoding='utf-8')
        pins = [line for line in text.splitlines() if '==' in line and not line.startswith('#')]
        self.assertGreater(len(pins), 10)
        blocks = text.split('==')[1:]
        self.assertTrue(all('--hash=sha256:' in block for block in blocks))


if __name__ == '__main__':
    unittest.main()
