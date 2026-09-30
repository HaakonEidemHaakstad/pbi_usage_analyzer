__version__ = "2.0.0-dev"

from .api import (AnalysisResult, AnalysisSummary, Diagnostic, DiagnosticSeverity,
                  ObjectCounts, analyze_project)

__all__ = ["analyze_project", "AnalysisResult", "AnalysisSummary", "Diagnostic",
           "DiagnosticSeverity", "ObjectCounts"]

from .health.model import HealthFinding, HealthSeverity

__all__ += ["HealthFinding", "HealthSeverity"]

from .health.filtering import HealthFilterScope, filter_health_findings

__all__ += ["filter_health_findings", "HealthFilterScope"]

from .reporting.json_report import analysis_to_dict, generate_json, write_json

__all__ += ["analysis_to_dict", "generate_json", "write_json"]
