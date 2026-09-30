"""Validate a saved export without loading a PBIP project or importing the analyzer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__:
    from .export_consistency import consistency_errors
else:
    from export_consistency import consistency_errors


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonstandard JSON number: {value}")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def json_pointer(parts) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts) or "<root>"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate a saved Power BI Analyzer JSON export (schema version 1).")
    parser.add_argument("export", type=Path, help="Saved JSON export to validate; the file is never modified.")
    args = parser.parse_args(argv)
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
    except ImportError:
        print("Validation dependency missing. Install with: .venv/bin/python -m pip install -r requirements-dev.txt", file=sys.stderr)
        return 2

    schema_path = Path(__file__).resolve().parents[2] / "schemas/analysis-result-v1.schema.json"
    try:
        schema = read_json(schema_path)
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Could not load schema {schema_path}: {exc}", file=sys.stderr)
        return 2
    except SchemaError as exc:
        # Invalid installed schemas are tool failures, not invalid input exports.
        print(f"Invalid schema {schema_path}: {exc}", file=sys.stderr)
        return 2

    try:
        document = read_json(args.export)
    except OSError as exc:
        print(f"Could not read export {args.export}: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON {args.export}:{exc.lineno}:{exc.colno}: {exc.msg}", file=sys.stderr)
        return 1
    except (UnicodeError, ValueError) as exc:
        print(f"Invalid JSON {args.export}: {exc}", file=sys.stderr)
        return 1

    errors = sorted(Draft202012Validator(schema).iter_errors(document),
                    key=lambda error: (json_pointer(error.absolute_path), error.message))
    if errors:
        print(f"Invalid export: {args.export}", file=sys.stderr)
        for error in errors:
            print(f"  {json_pointer(error.absolute_path)}: {error.message}", file=sys.stderr)
        return 1
    semantic_errors = consistency_errors(document)
    if semantic_errors:
        print(f"Inconsistent export: {args.export}", file=sys.stderr)
        for location, message in semantic_errors:
            print(f"  {location}: {message}", file=sys.stderr)
        return 1
    print(f"Valid export (schema version 1): {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
