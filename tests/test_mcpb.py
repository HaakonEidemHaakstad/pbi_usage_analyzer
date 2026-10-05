"""Claude Desktop extension packing (packaging/build_mcpb.py), without PyInstaller."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from pbi_usage_analyzer import __version__
from pbi_usage_analyzer_mcp.server import build_server

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_mcpb', ROOT / 'packaging' / 'build_mcpb.py')
build_mcpb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_mcpb)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = build_mcpb.manifest()

    def test_required_fields_of_manifest_spec_0_3(self):
        for field in ('manifest_version', 'name', 'version', 'description', 'author', 'server'):
            self.assertIn(field, self.manifest)
        self.assertEqual(self.manifest['manifest_version'], '0.3')
        self.assertEqual(self.manifest['version'], __version__)
        self.assertTrue(self.manifest['author']['name'])
        self.assertEqual(self.manifest['compatibility'], {'platforms': ['win32']})

    def test_binary_server_runs_the_bundled_executable(self):
        server = self.manifest['server']
        self.assertEqual(server['type'], 'binary')
        self.assertEqual(server['entry_point'], 'server/pbi-model-health-mcp.exe')
        self.assertEqual(server['mcp_config']['command'], '${__dirname}/server/pbi-model-health-mcp.exe')

    def test_tools_match_the_server(self):
        served = build_server(Path(tempfile.gettempdir())).handle(
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['result']['tools']
        self.assertEqual(self.manifest['tools'],
                         [{'name': t['name'], 'description': t['description']} for t in served])
        self.assertTrue(self.manifest['prompts_generated'])
        self.assertNotIn('prompts', self.manifest)

    def test_promises_match_the_design(self):
        text = self.manifest['long_description']
        self.assertIn('never changes them', text)
        self.assertIn('no network connections', text)
        self.assertIn('not proof that deletion is safe', text)


class PackTests(unittest.TestCase):
    def test_zip_has_manifest_at_root_and_server_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'pbi-model-health-mcp'
            (folder / '_internal').mkdir(parents=True)
            (folder / 'pbi-model-health-mcp.exe').write_bytes(b'MZ')
            (folder / '_internal' / 'python3.dll').write_bytes(b'x')
            output = build_mcpb.build(folder, Path(tmp) / 'out' / 'ext.mcpb')
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                manifest = json.loads(archive.read('manifest.json'))
        self.assertEqual(names[0], 'manifest.json')
        self.assertEqual(sorted(names[1:]), ['server/_internal/python3.dll', 'server/pbi-model-health-mcp.exe'])
        self.assertEqual(manifest['name'], 'pbi-model-health')

    def test_refuses_a_folder_without_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                build_mcpb.build(Path(tmp), Path(tmp) / 'ext.mcpb')


if __name__ == '__main__':
    unittest.main()
