import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.validation.check_fixture_drift import compare_fixtures


class FixtureDriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reference = self.root / 'reference'
        self.generated = self.root / 'generated'
        self.reference.mkdir()
        self.generated.mkdir()

    def test_added_removed_and_byte_changes_are_reported(self):
        (self.reference / 'changed').write_bytes(b'old\n')
        (self.generated / 'changed').write_bytes(b'new\n')
        (self.reference / 'extra').write_bytes(b'')
        (self.generated / 'missing').write_bytes(b'')
        self.assertEqual(compare_fixtures(self.reference, self.generated),
                         ['Changed: changed', 'Extra in corpus: extra', 'Missing from corpus: missing'])
        self.assertEqual((self.reference / 'changed').read_bytes(), b'old\n')

    def test_same_files_and_missing_corpus(self):
        for root in (self.reference, self.generated):
            (root / 'same.json').write_bytes(b'{"value":1}\n')
        self.assertEqual(compare_fixtures(self.reference, self.generated), [])
        with self.assertRaises(NotADirectoryError):
            compare_fixtures(self.root / 'absent', self.generated)

    def test_symlinks_are_rejected(self):
        try:
            (self.reference / 'link').symlink_to(self.generated, target_is_directory=True)
        except OSError as exc:  # Windows without Developer Mode/admin cannot create symlinks
            self.skipTest(f'symlink creation not permitted: {exc}')
        with self.assertRaises(ValueError):
            compare_fixtures(self.reference, self.generated)

    def test_command_checks_real_corpus_and_detects_drift_without_writes(self):
        repo = Path(__file__).resolve().parents[1]
        script = repo / 'tools/validation/check_fixture_drift.py'
        shutil.copytree(repo / 'tools/validation/validation_suite', self.reference, dirs_exist_ok=True)
        command = [sys.executable, str(script), str(self.reference)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.reference / 'suite_manifest.json'
        manifest.write_bytes(b'changed\n')
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Changed: suite_manifest.json', result.stderr)
        self.assertEqual(manifest.read_bytes(), b'changed\n')
        missing = subprocess.run([sys.executable, str(script), str(self.root / 'absent')], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
