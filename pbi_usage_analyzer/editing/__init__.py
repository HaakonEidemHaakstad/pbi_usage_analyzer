"""Assisted model changes: metadata edits applied to a working copy, checked by re-analysis.

The original project is never written. See `workspace` for the procedure and
docs/AI_ASSISTANT_DESIGN.md section 16 for the design.
"""
from .operations import (MAX_OPERATIONS, OPERATION_INFO, IssueSeverity, Operation, OperationKind, PlanIssue,
                         ResolvedOperation, parse_operations, resolve_operations)
from .tmdl_edit import EditError, ObjectProperties, TmdlDocument, read_properties
from .workspace import (Batch, ChangeOutcome, Check, FileDiff, ReadBack, Workspace, WorkspaceError, WorkspaceReview,
                        apply_changes, create_working_copy, desktop_checklist, open_workspace, preview_changes,
                        review_working_copy, undo_last_change)

__all__ = [
    "MAX_OPERATIONS", "OPERATION_INFO", "Batch", "ChangeOutcome", "Check", "EditError", "FileDiff", "IssueSeverity",
    "ObjectProperties", "Operation", "OperationKind", "PlanIssue", "ReadBack", "ResolvedOperation", "TmdlDocument",
    "Workspace", "WorkspaceError", "WorkspaceReview", "apply_changes", "create_working_copy", "desktop_checklist",
    "open_workspace", "parse_operations", "preview_changes", "read_properties", "resolve_operations",
    "review_working_copy", "undo_last_change",
]
