"""Smoke-test analysis and exports in a disposable runtime-only environment."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile


def worker(repo: Path) -> None:
    if importlib.util.find_spec('jsonschema') is not None:
        raise RuntimeError('Runtime-only environment unexpectedly contains jsonschema')
    sys.path.insert(0, str(repo))
    from pbi_usage_analyzer import analyze_project, generate_json

    with tempfile.TemporaryDirectory(prefix='pbi-runtime-project-') as folder:
        project = Path(folder) / 'project'
        shutil.copytree(repo / 'tools/validation/validation_suite/20_measure_descriptions', project)
        before = {path.relative_to(project): path.read_bytes() for path in project.rglob('*') if path.is_file()}
        result = analyze_project(project)
        document = json.loads(generate_json(result))
        if document['schema_version'] != 1 or document['summary']['measures']['business_total'] != 4:
            raise RuntimeError('Unexpected API smoke-test result')
        if len(document['health_findings']) != 2:
            raise RuntimeError('Expected two measure documentation findings')
        after = {path.relative_to(project): path.read_bytes() for path in project.rglob('*') if path.is_file()}
        if before != after:
            raise RuntimeError('Library analysis/export modified project files')
        subprocess.run([sys.executable, str(repo / 'run_analyzer.py'), str(project),
                        '--json', '--health-severity', 'warning'], check=True)
        exported = json.loads(result.project.root.joinpath(f'{result.project.project_name}_usage_analysis_v2.json').read_text(encoding='utf-8'))
        if exported['health_findings'] or exported['health_filter_scope']['severities'] != ['warning']:
            raise RuntimeError('CLI JSON export did not preserve health filters')
        if not result.project.text_output.read_text(encoding='utf-8').strip():
            raise RuntimeError('Text report is empty')
        with zipfile.ZipFile(result.project.excel_output) as workbook:
            if workbook.testzip() is not None or 'xl/workbook.xml' not in workbook.namelist():
                raise RuntimeError('Excel report is not a valid workbook archive')
    print('Runtime-only API, CLI, text, Excel and JSON smoke checks passed.')


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    if sys.argv[1:] == ['--worker']:
        worker(repo)
        return
    if sys.argv[1:]:
        raise SystemExit('Usage: check_runtime.py')
    with tempfile.TemporaryDirectory(prefix='pbi-runtime-env-') as folder:
        environment = Path(folder) / 'venv'
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        clean_env = dict(os.environ)
        clean_env.pop('PYTHONPATH', None)
        clean_env.pop('PYTHONHOME', None)
        clean_env['PYTHONNOUSERSITE'] = '1'
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(repo / 'requirements.txt')],
                       check=True, env=clean_env)
        subprocess.run([str(python), '-I', str(Path(__file__).resolve()), '--worker'],
                       check=True, env=clean_env, cwd=folder)


if __name__ == '__main__':
    main()
