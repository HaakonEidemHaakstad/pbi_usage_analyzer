"""Versioned JSON projection of an analysis result, without analysis logic."""
from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path

from ..api import AnalysisResult


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def analysis_to_dict(result: AnalysisResult) -> dict:
    """Return schema version 1. Internal parser state is intentionally not serialized."""
    from .. import __version__

    def counts(value):
        return {**asdict(value), "business_total": value.business_total}

    objects = []
    for obj in sorted(result.objects, key=lambda obj: obj.ref):
        objects.append({
            "ref": asdict(obj.ref), "source_file": obj.source_file,
            "source_line": obj.source_line, "hidden": obj.hidden,
            "calculated": obj.calculated, "source_column": obj.source_column,
            "data_type": obj.data_type, "expression": obj.expression,
            "sort_by_column": obj.sort_by_column, "description": obj.description,
        })
    return _json_value({
        "schema_version": 1,
        "analyzer_version": __version__,
        "project": asdict(result.project),
        "summary": {"columns": counts(result.summary.columns),
                    "measures": counts(result.summary.measures),
                    "query_dependencies": result.summary.query_dependencies},
        "objects": objects,
        "dependency_evidence": [asdict(evidence) for evidence in result.graph.evidence],
        "cleanup_findings": [{**asdict(finding), "status_id": finding.status.name}
                             for finding in result.findings],
        "diagnostics": [asdict(diagnostic) for diagnostic in result.diagnostics],
        # object_ref is not part of schema version 1.
        "health_findings": [{key: value for key, value in asdict(finding).items() if key != "object_ref"}
                            for finding in result.health_findings],
        "health_filter_scope": asdict(result.health_filter_scope),
    })


def generate_json(result: AnalysisResult) -> str:
    """Serialize without file writes, preserving Unicode and deterministic key order."""
    return json.dumps(analysis_to_dict(result), ensure_ascii=False, indent=2,
                      sort_keys=True, allow_nan=False) + "\n"


def write_json(path: str | Path, result: AnalysisResult) -> None:
    """Write a UTF-8 report; serialization failures occur before the file is opened."""
    content = generate_json(result)
    Path(path).write_text(content, encoding="utf-8")
