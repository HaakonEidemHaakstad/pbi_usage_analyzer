"""Check fixture reproducibility without rewriting the reference corpus."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


def file_inventory(root: Path) -> dict[Path, Path]:
    if not root.is_dir():
        raise NotADirectoryError(f"Fixture directory does not exist: {root}")
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError(f"Fixture symlinks are unsupported: {path}")
        if path.is_file():
            files[path.relative_to(root)] = path
    return files


def compare_fixtures(reference: Path, generated: Path) -> list[str]:
    """Compare file paths and bytes, including the manifest and expected results."""
    existing = file_inventory(reference)
    fresh = file_inventory(generated)
    changes = []
    for name in sorted(existing.keys() | fresh.keys()):
        if name not in existing:
            changes.append(f"Missing from corpus: {name.as_posix()}")
        elif name not in fresh:
            changes.append(f"Extra in corpus: {name.as_posix()}")
        elif existing[name].read_bytes() != fresh[name].read_bytes():
            changes.append(f"Changed: {name.as_posix()}")
    return changes


def main(argv=None) -> int:
    location = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Regenerate synthetic fixtures temporarily and detect corpus drift.")
    parser.add_argument('corpus', nargs='?', type=Path, default=location / 'validation_suite')
    args = parser.parse_args(argv)
    try:
        file_inventory(args.corpus)
        with tempfile.TemporaryDirectory(prefix='pbi-fixtures-') as folder:
            generated = Path(folder) / 'validation_suite'
            subprocess.run([sys.executable, str(location / 'generate_validation_suite.py'), str(generated)],
                           check=True, capture_output=True, text=True)
            changes = compare_fixtures(args.corpus, generated)
    except subprocess.CalledProcessError as exc:
        print(f"Fixture generation failed:\n{exc.stderr or exc.stdout}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"Could not check fixtures: {exc}", file=sys.stderr)
        return 2
    if changes:
        print('Fixture drift detected:', file=sys.stderr)
        for change in changes:
            print(f'  {change}', file=sys.stderr)
        print('Review the generator and corpus; regenerate intentionally with make fixtures.', file=sys.stderr)
        return 1
    print('Fixture corpus matches fresh generation.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
