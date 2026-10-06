"""Assisted model changes (pbi_usage_analyzer.editing): TMDL edits, validation, working copies."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.editing import (EditError, IssueSeverity, TmdlDocument, WorkspaceError, apply_changes,
                                        create_working_copy, open_workspace, parse_operations, preview_changes,
                                        read_properties, resolve_operations, review_working_copy, undo_last_change)
from pbi_usage_analyzer.editing import tmdl_edit, workspace as workspace_module
from pbi_usage_analyzer.model import ObjectRef, ObjectType

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / 'tools/validation/validation_suite'
MEASURE = ObjectType.MEASURE
COLUMN = ObjectType.COLUMN

DESKTOP_TABLE = (
    "table Sales\r\n"
    "\tlineageTag: 1\r\n"
    "\r\n"
    "\tmeasure 'Total Revenue' = SUM(Sales[Amount])\r\n"
    "\t\tlineageTag: 2\r\n"
    "\r\n"
    "\tmeasure 'Old Profit' =\r\n"
    "\t\t\t// isHidden: not a property\r\n"
    "\t\t\t    SUM(Sales[Amount])\r\n"
    "\t\tlineageTag: 3\r\n"
    "\r\n"
    "\tcolumn CustomerKey\r\n"
    "\t\tdataType: int64\r\n"
    "\t\tlineageTag: 4\r\n"
    "\t\tsummarizeBy: none\r\n"
    "\t\tsourceColumn: CustomerKey\r\n"
    "\r\n"
    "\t\tannotation SummarizationSetBy = Automatic\r\n"
    "\r\n"
    "\tcolumn Amount\r\n"
    "\t\tdataType: double\r\n"
    "\t\tformatString: 0.00\r\n"
    "\t\tsourceColumn: Amount\r\n"
)


def doc(text=DESKTOP_TABLE, bom=False):
    return TmdlDocument.decode(((tmdl_edit.BOM if bom else "") + text).encode("utf-8"))


def ref(name, kind=MEASURE, table="Sales"):
    return ObjectRef(kind, table, name)


class TmdlEditTests(unittest.TestCase):
    def test_unchanged_document_round_trips_byte_for_byte(self):
        for bom in (False, True):
            data = ((tmdl_edit.BOM if bom else "") + DESKTOP_TABLE).encode("utf-8")
            self.assertEqual(TmdlDocument.decode(data).encode(), data)

    def test_description_above_object_keeps_line_endings_and_bom(self):
        edited = tmdl_edit.set_description(doc(bom=True), ref("Total Revenue"), "Sum of Amount.\n  Second line ")
        data = edited.encode()
        self.assertTrue(data.startswith(tmdl_edit.BOM.encode("utf-8")))
        text = data.decode("utf-8")[1:]
        self.assertIn("\r\n\t/// Sum of Amount.\r\n\t/// Second line\r\n\tmeasure 'Total Revenue'", text)
        self.assertNotIn("\n\t/// Sum of Amount.\n", text.replace("\r\n", "\r"))  # no bare LF added
        self.assertEqual(read_properties(edited, ref("Total Revenue")).description, "Sum of Amount.\nSecond line")
        replaced = tmdl_edit.set_description(edited, ref("Total Revenue"), "New.")
        self.assertEqual(read_properties(replaced, ref("Total Revenue")).description, "New.")
        self.assertEqual(replaced.encode().decode("utf-8").count("///"), 1)

    def test_table_description_goes_above_the_table_header(self):
        edited = tmdl_edit.set_description(doc(), ObjectRef(ObjectType.TABLE, "Sales"), "Order lines.")
        self.assertTrue(edited.lines[0] == "/// Order lines." and edited.lines[1] == "table Sales")

    def test_properties_follow_a_multi_line_expression(self):
        edited = tmdl_edit.set_hidden(doc(), ref("Old Profit"), True)
        edited = tmdl_edit.set_property(edited, ref("Old Profit"), "displayFolder", "Legacy")
        lines = list(edited.lines)
        start = lines.index("\tmeasure 'Old Profit' =")
        self.assertEqual(lines[start + 1:start + 6], ["\t\t\t// isHidden: not a property", "\t\t\t    SUM(Sales[Amount])",
                                                      "\t\tisHidden", "\t\tdisplayFolder: Legacy", "\t\tlineageTag: 3"])
        props = read_properties(edited, ref("Old Profit"))
        self.assertTrue(props.hidden)
        self.assertEqual(props.display_folder, "Legacy")
        self.assertFalse(read_properties(doc(), ref("Old Profit")).hidden)  # the comment is not a property

    def test_hiding_a_column_matches_power_bi_desktop(self):
        edited = tmdl_edit.set_hidden(doc(), ref("CustomerKey", COLUMN), True)
        lines = list(edited.lines)
        start = lines.index("\tcolumn CustomerKey")
        self.assertEqual(lines[start + 1:start + 10], [
            "\t\tdataType: int64", "\t\tisHidden", "\t\tlineageTag: 4", "\t\tsummarizeBy: none",
            "\t\tsourceColumn: CustomerKey", "", "\t\tchangedProperty = IsHidden", "",
            "\t\tannotation SummarizationSetBy = Automatic"])
        shown = tmdl_edit.set_hidden(edited, ref("CustomerKey", COLUMN), False)
        self.assertFalse(read_properties(shown, ref("CustomerKey", COLUMN)).hidden)
        self.assertEqual(sum(line.strip() == "changedProperty = IsHidden" for line in shown.lines), 1)
        last = tmdl_edit.set_hidden(doc(), ref("Amount", COLUMN), True)  # last object, no child objects
        self.assertEqual(last.lines[-4:], ("\t\tsourceColumn: Amount", "", "\t\tchangedProperty = IsHidden", ""))
        self.assertIn("\t\tisHidden", last.lines)

    def test_text_values_are_quoted_only_when_needed(self):
        edited = tmdl_edit.set_property(doc(), ref("Total Revenue"), "formatString", '"$"#,0.00')
        self.assertIn('\t\tformatString: """$""#,0.00"', edited.lines)
        self.assertEqual(read_properties(edited, ref("Total Revenue")).format_string, '"$"#,0.00')
        self.assertEqual(tmdl_edit.tmdl_text("Sales\\Margins"), "Sales\\Margins")
        self.assertEqual(tmdl_edit.tmdl_text(" x"), '" x"')
        replaced = tmdl_edit.set_property(doc(), ref("Amount", COLUMN), "formatString", "#,0")
        self.assertIn("\t\tformatString: #,0", replaced.lines)
        self.assertNotIn("\t\tformatString: 0.00", replaced.lines)
        removed = tmdl_edit.set_property(doc(), ref("Amount", COLUMN), "formatString", None)
        self.assertIsNone(read_properties(removed, ref("Amount", COLUMN)).format_string)

    def test_space_indented_object_without_properties(self):
        text = "table T\n    measure A = 1\n    measure B = 2\n"
        edited = tmdl_edit.set_property(doc(text), ref("A", table="T"), "displayFolder", "F")
        self.assertEqual(edited.lines[:4], ("table T", "    measure A = 1", "        displayFolder: F", "    measure B = 2"))

    def test_fenced_expression_as_power_bi_desktop_writes_it(self):
        text = ("table T\n\tmeasure A = ```\n\t\t\tCALCULATE(\n\t\t\t    [B], \n\tisHidden\n\t\t\t```\n"
                "\t\tformatString: 0\n\t\tlineageTag: 1\n")
        self.assertFalse(read_properties(doc(text), ref("A", table="T")).hidden)  # fence content is DAX
        edited = tmdl_edit.set_hidden(doc(text), ref("A", table="T"), True)
        edited = tmdl_edit.set_property(edited, ref("A", table="T"), "displayFolder", "F")
        self.assertEqual(edited.lines[1:], ("\tmeasure A = ```", "\t\t\tCALCULATE(", "\t\t\t    [B], ", "\tisHidden",
                                            "\t\t\t```", "\t\tisHidden", "\t\tformatString: 0",
                                            "\t\tdisplayFolder: F", "\t\tlineageTag: 1", ""))

    def test_unsupported_layouts_raise_instead_of_guessing(self):
        fenced = "table T\n\tmeasure A = ```\n\t\t\t1\n"  # no closing fence
        with self.assertRaises(EditError) as raised:
            tmdl_edit.set_hidden(doc(fenced), ref("A", table="T"), True)
        self.assertEqual(raised.exception.code, "TMDL_LAYOUT_UNSUPPORTED")
        described = "table T\n\tmeasure A = 1\n\t\tdescription: Old\n"
        with self.assertRaises(EditError):
            tmdl_edit.set_description(doc(described), ref("A", table="T"), "New")
        dynamic = "table T\n\tmeasure A = 1\n\t\tformatStringDefinition = \"0\"\n"
        self.assertTrue(read_properties(doc(dynamic), ref("A", table="T")).dynamic_format)
        with self.assertRaises(EditError):
            tmdl_edit.set_property(doc(dynamic), ref("A", table="T"), "formatString", "0")
        with self.assertRaises(EditError) as raised:
            tmdl_edit.set_hidden(doc(), ref("Missing"), True)
        self.assertEqual(raised.exception.code, "OBJECT_NOT_IN_FILE")
        with self.assertRaises(EditError):
            TmdlDocument.decode(b"table \xff")


class ScenarioTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def copy(self, scenario):
        target = Path(self.tmp.name) / scenario
        shutil.copytree(SUITE / scenario, target)
        (target / "expected.json").unlink()
        return target

    @staticmethod
    def files(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class ValidationTests(ScenarioTestCase):
    def resolve(self, scenario, operations):
        result = analyze_project(self.copy(scenario))
        parsed, issues = parse_operations(operations)
        resolved, more = resolve_operations(result, parsed)
        return resolved, issues + more

    def test_malformed_operations(self):
        self.assertEqual(parse_operations([])[1][0].code, "NO_OPERATIONS")
        self.assertEqual(parse_operations([{}] * 51)[1][0].code, "TOO_MANY_OPERATIONS")
        _, issues = parse_operations([{"op": "delete", "object": "A[B]", "value": ""},
                                      {"op": "set_hidden", "object": "A[B]", "value": "yes"},
                                      {"op": "set_hidden", "object": "A[B]", "value": True, "extra": 1}])
        self.assertEqual([i.code for i in issues], ["OPERATION_UNKNOWN", "VALUE_INVALID", "OPERATION_MALFORMED"])
        self.assertEqual([i.index for i in issues], [0, 1, 2])

    def test_objects_are_resolved_like_the_analyzer(self):
        resolved, issues = self.resolve("40_power_bi_desktop_shapes", [
            {"op": "set_hidden", "object": "'sales'[ monthkey ]", "value": True},
            {"op": "set_description", "object": "sales", "value": "Order lines."},
            {"op": "set_description", "object": "Sales[Totl Revenue]", "value": "x"},
        ])
        self.assertEqual([item.ref for item in resolved],
                         [ref("MonthKey", COLUMN), ObjectRef(ObjectType.TABLE, "Sales")])
        self.assertEqual(issues[0].code, "OBJECT_NOT_FOUND")
        self.assertIn("Sales[Total Revenue]", issues[0].message)

    def test_refusals(self):
        _, issues = self.resolve("40_power_bi_desktop_shapes", [
            {"op": "set_hidden", "object": "LocalDateTable_stock[Date]", "value": True},
            {"op": "set_hidden", "object": "Sales", "value": True},
            {"op": "set_description", "object": "Sales[Amount]", "value": "   "},
            {"op": "set_display_folder", "object": "Sales[Amount]", "value": "a\nb"},
            {"op": "set_hidden", "object": "Sales[Amount]", "value": True},
            {"op": "set_hidden", "object": "Sales[amount]", "value": False},
        ])
        self.assertEqual([i.code for i in issues if i.severity == IssueSeverity.ERROR],
                         ["OBJECT_INTERNAL", "OBJECT_TYPE_NOT_ALLOWED", "VALUE_INVALID", "VALUE_INVALID",
                          "OPERATION_DUPLICATE"])

    def test_warnings_and_values_already_set(self):
        resolved, issues = self.resolve("40_power_bi_desktop_shapes", [
            {"op": "set_description", "object": "Sales[Total Revenue]", "value": "Revenue in USD"},
            {"op": "set_hidden", "object": "Sales[ Country]", "value": True},
            {"op": "set_format_string", "object": "Sales[ Country]", "value": "@"},
        ])
        self.assertEqual([(i.code, i.severity) for i in issues], [
            ("ALREADY_SET", IssueSeverity.SKIPPED), ("HIDING_REPORT_FIELD", IssueSeverity.WARNING),
            ("FORMAT_ON_TEXT", IssueSeverity.WARNING)])
        self.assertEqual(len(resolved), 2)


class WorkingCopyTests(ScenarioTestCase):
    OPERATIONS = [
        {"op": "set_description", "object": "Sales[Missing]", "value": "The constant 2."},
        {"op": "set_description", "object": "Sales[Blank]", "value": "The constant 3."},
        {"op": "set_display_folder", "object": "Sales[Missing]", "value": "Constants"},
    ]

    def test_preview_writes_nothing_and_reports_diff_and_effects(self):
        project = self.copy("20_measure_descriptions")
        before = self.files(project)
        outcome = preview_changes(project, self.OPERATIONS)
        self.assertEqual(self.files(project), before)
        self.assertFalse(outcome.refused)
        self.assertTrue(outcome.check.passed, outcome.check.problems)
        self.assertEqual(len(outcome.diffs), 1)
        self.assertIn("+    /// The constant 2.", outcome.diffs[0].diff)
        self.assertEqual(sorted(c.change.label for c in outcome.check.assessment.changes),
                         ["Sales[Blank]", "Sales[Missing]"])  # both description findings resolved

    def test_full_procedure_on_a_working_copy(self):
        project = self.copy("20_measure_descriptions")
        original = self.files(project)
        moment = datetime(2026, 10, 6, 14, 30)
        workspace = create_working_copy(project, now=moment)
        self.assertEqual(workspace.root.name, "20_measure_descriptions (proposed 2026-10-06 1430)")
        self.assertEqual(create_working_copy(project, now=moment).root.name,
                         "20_measure_descriptions (proposed 2026-10-06 1430 2)")
        with self.assertRaises(WorkspaceError):
            apply_changes(project, self.OPERATIONS)  # the original is never a working copy

        outcome = apply_changes(workspace.root, self.OPERATIONS, "describe constants")
        self.assertTrue(outcome.applied, outcome.check.problems)
        self.assertEqual(outcome.batch.number, 1)
        self.assertEqual(self.files(project), original)
        result = analyze_project(workspace.root)
        self.assertNotIn("MEASURE_DESCRIPTION_MISSING", [f.rule_id for f in result.health_findings])
        review = review_working_copy(workspace.root)
        self.assertEqual(len(review.assessment.changes), 2)
        self.assertFalse(review.outside_changes)
        self.assertTrue(any("description" in step for step in review.checklist))

        undone = undo_last_change(workspace.root)
        self.assertEqual(undone.number, 1)
        copy_model = workspace.root / "20_measure_descriptions.SemanticModel"
        self.assertEqual((copy_model / "definition/tables/Sales.tmdl").read_bytes(),
                         original["20_measure_descriptions.SemanticModel/definition/tables/Sales.tmdl"])
        with self.assertRaises(WorkspaceError):
            undo_last_change(workspace.root)
        self.assertTrue(open_workspace(workspace.root).batches[0].undone)

    def test_outside_changes_are_reported_and_block_undo(self):
        workspace = create_working_copy(self.copy("20_measure_descriptions"))
        apply_changes(workspace.root, self.OPERATIONS[:1])
        sales = workspace.root / "20_measure_descriptions.SemanticModel/definition/tables/Sales.tmdl"
        sales.write_bytes(sales.read_bytes() + b"    measure Added = 5\n")  # as if saved by Power BI Desktop
        outcome = apply_changes(workspace.root, self.OPERATIONS[1:2])
        self.assertEqual(outcome.outside_changes, ("20_measure_descriptions.SemanticModel/definition/tables/Sales.tmdl",))
        self.assertTrue(outcome.applied)
        sales.write_bytes(sales.read_bytes() + b"    measure Added2 = 6\n")
        with self.assertRaises(WorkspaceError) as raised:
            undo_last_change(workspace.root)
        self.assertIn("changed after it was applied", str(raised.exception))

    def test_unexpected_analysis_change_refuses_the_batch(self):
        workspace = create_working_copy(self.copy("20_measure_descriptions"))
        before = self.files(workspace.root)

        def broken(document, item):  # an editor bug that drops the object
            return TmdlDocument(tuple(line for line in document.lines if "measure Missing" not in line),
                                document.newline, document.bom)

        with mock.patch.object(workspace_module, "_edit", broken):
            outcome = apply_changes(workspace.root, self.OPERATIONS[:1])
        self.assertFalse(outcome.applied)
        self.assertFalse(outcome.check.passed)
        self.assertTrue(any("no longer found" in p for p in outcome.check.problems))
        self.assertEqual(self.files(workspace.root), before)

    def test_failed_check_on_disk_rolls_back(self):
        workspace = create_working_copy(self.copy("20_measure_descriptions"))
        before = self.files(workspace.root)
        real = workspace_module._check
        calls = []

        def second_fails(*args):
            check = real(*args)
            calls.append(check)
            if len(calls) == 2:
                return workspace_module.Check(("simulated failure",), check.readback, check.assessment)
            return check

        with mock.patch.object(workspace_module, "_check", second_fails):
            outcome = apply_changes(workspace.root, self.OPERATIONS)
        self.assertTrue(outcome.rolled_back)
        self.assertFalse(outcome.applied)
        self.assertEqual(self.files(workspace.root), before)
        self.assertEqual(open_workspace(workspace.root).batches, [])

    def test_working_copy_record_is_checked(self):
        project = self.copy("20_measure_descriptions")
        with self.assertRaises(WorkspaceError):
            open_workspace(project)
        workspace = create_working_copy(project)
        marker = workspace.root / ".pbi-model-health" / "workspace.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["original"] = str(workspace.root)
        marker.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            open_workspace(workspace.root)
        with self.assertRaises(WorkspaceError):
            create_working_copy(project, target=project / "inside")

    def test_copy_contains_only_the_project(self):
        project = self.copy("40_power_bi_desktop_shapes")
        (project / "raw data.csv").write_text("a,b\n", encoding="utf-8")
        workspace = create_working_copy(project)
        names = sorted(p.name for p in workspace.root.iterdir())
        self.assertEqual(names, [".pbi-model-health", "40_power_bi_desktop_shapes.Report",
                                 "40_power_bi_desktop_shapes.SemanticModel", "40_power_bi_desktop_shapes.pbip"])


class OfflineTests(unittest.TestCase):
    def test_editing_loads_no_network_or_gui_library(self):
        import subprocess
        import sys
        code = ("import sys, pbi_usage_analyzer.editing; bad = [m for m in ('socket', 'http.client', "
                "'urllib.request', 'PySide6', 'anthropic') if m in sys.modules]; print(bad)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
        self.assertEqual(out.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
