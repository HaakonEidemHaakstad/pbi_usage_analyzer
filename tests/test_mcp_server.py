"""MCP server for Claude Desktop (pbi_usage_analyzer_mcp): protocol eras, tools, prompts."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pbi_usage_analyzer.views import ProjectState
from pbi_usage_analyzer.views.history import state_file
from pbi_usage_analyzer_mcp.protocol import (INVALID_PARAMS, INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR,
                                             UNSUPPORTED_PROTOCOL_VERSION)
from pbi_usage_analyzer_mcp.server import SERVER_NAME, build_server, config_entry

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / 'tools/validation/validation_suite'
META = {'io.modelcontextprotocol/protocolVersion': '2026-07-28', 'io.modelcontextprotocol/clientCapabilities': {}}


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / 'data'
        self.server = build_server(self.data_dir)
        self.next_id = 0

    def request(self, method, params=None, modern=False):
        self.next_id += 1
        params = dict(params or {})
        if modern:
            params['_meta'] = META
        return self.server.handle({'jsonrpc': '2.0', 'id': self.next_id, 'method': method, 'params': params})

    def call(self, name, **arguments):
        result = self.request('tools/call', {'name': name, 'arguments': arguments})['result']
        return result['content'][0]['text'], result['isError']

    def copy(self, scenario):
        target = Path(self.tmp.name) / scenario
        shutil.copytree(SUITE / scenario, target)
        return target


class ProtocolTests(ServerTestCase):
    def test_legacy_handshake(self):
        result = self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                             'clientInfo': {'name': 't', 'version': '1'}})['result']
        self.assertEqual(result['protocolVersion'], '2025-06-18')
        self.assertEqual(result['capabilities'], {'tools': {}, 'prompts': {}})
        self.assertEqual(result['serverInfo']['name'], SERVER_NAME)
        self.assertIn('Never describe any object as safe to delete', result['instructions'])
        self.assertNotIn('resultType', result)
        unknown = self.request('initialize', {'protocolVersion': '1999-01-01'})['result']
        self.assertEqual(unknown['protocolVersion'], '2025-11-25')
        self.assertNotIn('resultType', self.request('tools/list')['result'])

    def test_modern_discover_and_requests(self):
        result = self.request('server/discover', modern=True)['result']
        self.assertEqual(result['supportedVersions'], ['2026-07-28'])
        self.assertEqual(result['resultType'], 'complete')
        self.assertEqual(result['_meta']['io.modelcontextprotocol/serverInfo']['name'], SERVER_NAME)
        tools = self.request('tools/list', modern=True)['result']
        self.assertEqual(tools['resultType'], 'complete')
        self.assertEqual([t['name'] for t in tools['tools']],
                         ['analyze_model', 'explain_object', 'save_baseline', 'compare_with_baseline',
                          'create_working_copy', 'preview_changes', 'apply_changes', 'undo_last_change',
                          'review_working_copy'])
        annotations = {t['name']: t['annotations'] for t in tools['tools']}
        self.assertTrue(annotations['preview_changes']['readOnlyHint'])
        self.assertTrue(annotations['apply_changes']['destructiveHint'])

    def test_version_and_metadata_errors(self):
        meta = {'io.modelcontextprotocol/protocolVersion': '2099-01-01', 'io.modelcontextprotocol/clientCapabilities': {}}
        error = self.server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {'_meta': meta}})['error']
        self.assertEqual(error['code'], UNSUPPORTED_PROTOCOL_VERSION)
        self.assertIn('2026-07-28', error['data']['supported'])
        self.assertEqual(error['data']['requested'], '2099-01-01')
        missing = {'io.modelcontextprotocol/protocolVersion': '2026-07-28'}
        error = self.server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {'_meta': missing}})['error']
        self.assertEqual(error['code'], INVALID_PARAMS)
        self.assertEqual(self.request('server/discover')['error']['code'], INVALID_PARAMS)

    def test_json_rpc_edge_cases(self):
        self.assertIsNone(self.server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
        self.assertIsNone(self.server.handle({'jsonrpc': '2.0', 'id': 5, 'result': {}}))
        self.assertEqual(self.request('resources/list')['error']['code'], METHOD_NOT_FOUND)
        self.assertEqual(self.request('ping')['result'], {})
        self.assertEqual(self.server.handle([])['error']['code'], INVALID_REQUEST)
        self.assertEqual(self.server.handle({'jsonrpc': '2.0', 'id': None, 'method': 'ping'})['error']['code'],
                         INVALID_REQUEST)
        reply = json.loads(self.server.handle_line(b'{not json'))
        self.assertEqual((reply['id'], reply['error']['code']), (None, PARSE_ERROR))
        with_bom = json.loads(self.server.handle_line(b'\xef\xbb\xbf{"jsonrpc":"2.0","id":9,"method":"ping"}'))
        self.assertEqual((with_bom['id'], with_bom['result']), (9, {}))
        self.assertEqual(self.request('tools/call', {'name': 'nope'})['error']['code'], INVALID_PARAMS)

    def test_stdio_subprocess_one_message_per_line(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                'name': 'analyze_model', 'arguments': {'project_path': str(SUITE / '02_dax_transitive')}}},
        ]
        data = ''.join(json.dumps(m) + '\n' for m in messages).encode('utf-8')
        completed = subprocess.run([sys.executable, '-m', 'pbi_usage_analyzer_mcp', '--data-dir', str(self.data_dir)],
                                   input=data, capture_output=True, cwd=ROOT, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode('utf-8', 'replace'))
        lines = completed.stdout.decode('utf-8').splitlines()
        self.assertEqual([json.loads(line)['id'] for line in lines], [1, 2])
        self.assertIn("SUM('Sales'[Amount])", json.loads(lines[1])['result']['content'][0]['text'])

    def test_config_entry_runs_this_package(self):
        entry = config_entry()
        self.assertEqual(entry['command'], sys.executable)
        self.assertEqual(entry['args'], ['-m', 'pbi_usage_analyzer_mcp'])
        self.assertEqual(Path(entry['env']['PYTHONPATH']), ROOT)


class ToolTests(ServerTestCase):
    def test_analyze_model_wraps_the_briefing(self):
        text, error = self.call('analyze_model', project_path=str(SUITE / '41_m_usage_aware_lineage'))
        self.assertFalse(error)
        self.assertIn('<analysis>\n# Analysis briefing: 41_m_usage_aware_lineage', text)
        self.assertTrue(text.endswith('</analysis>'))
        only, _ = self.call('analyze_model', project_path=str(SUITE / '41_m_usage_aware_lineage'),
                            sections=['health'], include_expressions=False)
        self.assertIn('## Model-health findings', only)
        self.assertNotIn('## Project', only)

    def test_argument_and_path_errors_are_tool_errors(self):
        text, error = self.call('analyze_model', project_path=str(Path(self.tmp.name) / 'missing'))
        self.assertTrue(error)
        self.assertIn('No such folder or file', text)
        text, error = self.call('analyze_model', project_path='x', sections=['bogus'])
        self.assertTrue(error)
        self.assertIn("may only contain", text)
        text, error = self.call('explain_object', project_path='x')
        self.assertTrue(error)
        self.assertIn("Missing required argument 'object'", text)

    def test_explain_object_status_path_and_dax(self):
        project = str(SUITE / '02_dax_transitive')
        text, error = self.call('explain_object', project_path=project, object="'sales'[ AMOUNT ]")
        self.assertFalse(error)
        self.assertIn('Sales[Amount] (column): Used', text)
        self.assertIn('Why: Report -> Sales[Measure A] -> DAX -> Sales[Measure B] -> DAX -> Sales[Amount]', text)
        text, _ = self.call('explain_object', project_path=project, object='Sales[Measure B]')
        self.assertIn("DAX:\n```dax\nSUM('Sales'[Amount])\n```", text)
        self.assertIn('It depends on:\n- DAX: Sales[Amount]', text)
        overview, _ = self.call('explain_object', project_path=project, object='Sales')
        self.assertIn('- Sales[Unused] (column): Likely unused', overview)
        missing, error = self.call('explain_object', project_path=project, object='Sales[Amout]')
        self.assertTrue(error)
        self.assertIn('Similar names: Sales[Amount]', missing)

    def test_baseline_and_comparison(self):
        project = self.copy('41_m_usage_aware_lineage')
        text, error = self.call('compare_with_baseline', project_path=str(project))
        self.assertTrue(error)
        self.assertIn('No baseline is saved', text)
        text, error = self.call('save_baseline', project_path=str(project))
        self.assertFalse(error)
        self.assertTrue(state_file(self.data_dir, project, 'assistant').exists())
        self.assertFalse(any(project.rglob('*.json.tmp')))
        (next(project.rglob('Visual2')) / 'visual.json').unlink()  # the Budget[Note] visual
        text, error = self.call('compare_with_baseline', project_path=str(project))
        self.assertFalse(error)
        self.assertIn('[Attention] Status changed: Budget[Note] (Used -> Likely unused).', text)
        self.assertIn('## Project', text)
        self.assertNotIn('## Model-health findings', text)

    def test_acknowledgements_from_the_desktop_app_reach_the_briefing(self):
        project = SUITE / '41_m_usage_aware_lineage'
        state = ProjectState(str(project))
        state.acknowledge('Column|Budget|Note', 'kept for finance', datetime(2026, 10, 1))
        state.save(state_file(self.data_dir, project))
        text, _ = self.call('analyze_model', project_path=str(project))
        self.assertIn('- Column|Budget|Note (acknowledged 2026-10-01): kept for finance', text)


class ChangeToolTests(ServerTestCase):
    OPERATIONS = [{'op': 'set_description', 'object': 'Sales[Missing]', 'value': 'The constant 2.'},
                  {'op': 'set_display_folder', 'object': 'Sales[Missing]', 'value': 'Constants'}]

    def test_change_procedure(self):
        project = self.copy('20_measure_descriptions')
        original = (project / '20_measure_descriptions.SemanticModel/definition/tables/Sales.tmdl').read_bytes()
        text, error = self.call('apply_changes', working_copy=str(project), operations=self.OPERATIONS)
        self.assertTrue(error)
        self.assertIn('not a working copy', text)

        text, error = self.call('create_working_copy', project_path=str(project))
        self.assertFalse(error)
        copy = Path(text.splitlines()[0].split(': ', 1)[1])
        self.assertTrue((copy / '.pbi-model-health' / 'workspace.json').exists())

        text, error = self.call('preview_changes', project_path=str(copy), operations=self.OPERATIONS)
        self.assertFalse(error)
        self.assertTrue(text.startswith('Preview only, nothing was written.'))
        self.assertIn('Checks: 2 of 2 values read back as intended', text)
        self.assertIn('- Improvement: Sales[Missing]: Document this measure -> (none).', text)
        self.assertIn('+    /// The constant 2.', text)

        text, error = self.call('apply_changes', working_copy=str(copy), operations=self.OPERATIONS,
                                note='describe constants')
        self.assertFalse(error)
        self.assertTrue(text.startswith('Applied as change 1 to the working copy.'), text)
        text, _ = self.call('review_working_copy', working_copy=str(copy))
        self.assertIn('- Change 1, ', text)
        self.assertIn(': describe constants; 2 operation(s)', text)
        self.assertIn('To check in Power BI Desktop (the analyzer cannot):\n1. ', text)
        text, error = self.call('undo_last_change', working_copy=str(copy))
        self.assertFalse(error)
        self.assertIn('Undid change 1 (describe constants)', text)
        self.assertEqual((project / '20_measure_descriptions.SemanticModel/definition/tables/Sales.tmdl')
                         .read_bytes(), original)

    def test_refusals_are_explained(self):
        project = str(SUITE / '20_measure_descriptions')
        text, error = self.call('preview_changes', project_path=project, operations=[
            {'op': 'set_hidden', 'object': 'Sales[Nope]', 'value': True},
            {'op': 'set_description', 'object': 'Sales[Documented]', 'value': 'Revenue in local currency.\nExcludes tax.'}])
        self.assertFalse(error)  # a refusal is a normal answer with reasons, not a tool failure
        self.assertTrue(text.startswith('Refused: nothing was written.'))
        self.assertIn("- error (operation 1): No column or measure named 'Sales[Nope]'.", text)
        self.assertIn('- skipped (operation 2):', text)
        text, error = self.call('preview_changes', project_path=project, operations=['x'])
        self.assertTrue(error)
        self.assertIn('must be a list of objects', text)


class PromptTests(ServerTestCase):
    def test_prompt_list_and_get(self):
        prompts = self.request('prompts/list')['result']['prompts']
        self.assertEqual([p['name'] for p in prompts], ['interpret', 'next_steps', 'evaluate', 'improve_model'])
        self.assertTrue(prompts[0]['arguments'][0]['required'])
        result = self.request('prompts/get', {'name': 'next_steps', 'arguments': {
            'project_path': str(SUITE / '02_dax_transitive'), 'question': 'Focus on DAX.'}})['result']
        text = result['messages'][0]['content']['text']
        self.assertEqual(result['messages'][0]['role'], 'user')
        self.assertIn('<analysis>', text)
        self.assertIn('<question>\nFocus on DAX.\n</question>', text)
        self.assertIn('Project path for this server', text)

    def test_prompt_errors(self):
        self.assertEqual(self.request('prompts/get', {'name': 'nope'})['error']['code'], INVALID_PARAMS)
        self.assertEqual(self.request('prompts/get', {'name': 'interpret', 'arguments': {}})['error']['code'],
                         INVALID_PARAMS)
        error = self.request('prompts/get', {'name': 'evaluate', 'arguments': {
            'project_path': str(SUITE / '02_dax_transitive')}})['error']
        self.assertEqual(error['code'], INVALID_PARAMS)
        self.assertIn('save_baseline', error['message'])

    def test_improve_prompt(self):
        result = self.request('prompts/get', {'name': 'improve_model', 'arguments': {
            'project_path': str(SUITE / '20_measure_descriptions')}})['result']
        text = result['messages'][0]['content']['text']
        self.assertIn('create_working_copy', text)
        self.assertIn('Never hide a field because it is Likely unused', text)

    def test_evaluate_after_baseline(self):
        project = self.copy('41_m_usage_aware_lineage')
        self.call('save_baseline', project_path=str(project))
        result = self.request('prompts/get', {'name': 'evaluate', 'arguments': {
            'project_path': str(project), 'previous_advice': 'S1: remove Old[X]'}})['result']
        text = result['messages'][0]['content']['text']
        self.assertIn('## Changes since the previous analysis', text)
        self.assertIn('<previous_advice>\nS1: remove Old[X]\n</previous_advice>', text)


class OfflineImportTests(unittest.TestCase):
    def test_server_loads_no_network_library(self):
        code = ("import sys, pbi_usage_analyzer_mcp.server; "
                "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
                "{'anthropic', 'httpx', 'httpx2', 'requests', 'socket', 'ssl', 'asyncio'} "
                "or m in {'http.client', 'urllib.request'}); print(bad); sys.exit(1 if bad else 0)")
        completed = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
