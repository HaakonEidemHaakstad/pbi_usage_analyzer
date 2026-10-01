"""The result tabs. Filtering and grouping come from `pbi_usage_analyzer.views`."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget, QAbstractItemView, QHeaderView)

from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.model import ObjectType, Status
from pbi_usage_analyzer.views import (CHANGE_LABELS, LIKELY_UNUSED_CAVEAT, SEVERITY_LABELS, STATUS_INFO,
                                      Acknowledgement, Change, DiagnosticRow, HealthRow, ObjectRow,
                                      QueryDependencyRow, filter_health, filter_objects, unused_by_table)

from .models import Column, RowTable

BUSINESS_STATUSES = (Status.USED, Status.MANUAL_REVIEW, Status.LIKELY_UNUSED)


def _combo(items: list[tuple[str, object]]) -> QComboBox:
    combo = QComboBox()
    for text, data in items:
        combo.addItem(text, data)
    return combo


def _set_combo(combo: QComboBox, data) -> None:
    index = combo.findData(data)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _search_box(placeholder: str) -> QLineEdit:
    box = QLineEdit()
    box.setPlaceholderText(placeholder)
    box.setClearButtonEnabled(True)
    box.setMinimumWidth(180)  # keep the placeholder readable in narrow windows
    return box


class _AcknowledgementBar(QWidget):
    """Hide-acknowledged toggle and (un)acknowledge buttons for a row table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide = QCheckBox("Hide acknowledged")
        self.hide.setChecked(True)
        self.acknowledge = QPushButton("Acknowledge…")
        self.acknowledge.setToolTip("Mark the selected row as reviewed, with an optional note (Ctrl+K)")
        self.remove = QPushButton("Remove acknowledgement")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.hide)
        layout.addStretch()
        layout.addWidget(self.acknowledge)
        layout.addWidget(self.remove)
        self.update_buttons(None, {})

    def update_buttons(self, key: str | None, acknowledgements: dict) -> None:
        self.acknowledge.setEnabled(key is not None)
        self.remove.setEnabled(key is not None and key in acknowledgements)


class OverviewTab(QWidget):
    """Counts with links into the other tabs, and how to read the statuses."""
    show_objects = Signal(object, object, object)  # status | None, ObjectType | None, table | None
    show_health = Signal(object)  # HealthSeverity | None
    show_diagnostics = Signal()
    show_changes = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._content: QWidget | None = None

    def set_result(self, objects: tuple[ObjectRow, ...], health: tuple[HealthRow, ...],
                   diagnostics: tuple[DiagnosticRow, ...], acknowledged: frozenset[str] = frozenset(),
                   changes: tuple[Change, ...] | None = None) -> None:
        if self._content is not None:
            self._content.deleteLater()
        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, 0, 0, 0)

        counts = QGroupBox("Cleanup status (business objects)")
        grid = QGridLayout(counts)
        for column, status in enumerate(BUSINESS_STATUSES, start=1):
            grid.addWidget(QLabel(f"<b>{STATUS_INFO[status].label}</b>"), 0, column)
        for row_number, (kind, title) in enumerate(((ObjectType.COLUMN, "Columns"),
                                                    (ObjectType.MEASURE, "Measures")), start=1):
            rows = [row for row in objects if row.object_type == kind and not row.internal]
            grid.addWidget(QLabel(f"{title}: {len(rows)}"), row_number, 0)
            for column, status in enumerate(BUSINESS_STATUSES, start=1):
                button = QPushButton(str(sum(row.status == status for row in rows)))
                button.setToolTip(f"Show {title.lower()} with status {STATUS_INFO[status].label}")
                button.clicked.connect(lambda _=False, s=status, k=kind: self.show_objects.emit(s, k, None))
                grid.addWidget(button, row_number, column)
        internal = sum(row.internal for row in objects)
        if internal:
            grid.addWidget(QLabel(f"Internal / auto-generated objects (not counted): {internal}"), 3, 0, 1, 4)
        layout.addWidget(counts)

        middle = QHBoxLayout()
        health_box = QGroupBox("Model health")
        health_layout = QVBoxLayout(health_box)
        for severity in (HealthSeverity.WARNING, HealthSeverity.INFO):
            rows = [row for row in health if row.severity == severity]
            done = sum(row.key in acknowledged for row in rows)
            text = f"{SEVERITY_LABELS[severity]}: {len(rows)}" + (f" ({done} acknowledged)" if done else "")
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, s=severity: self.show_health.emit(s))
            health_layout.addWidget(button)
        by_category = Counter(row.category_label for row in health)
        if by_category:
            health_layout.addWidget(QLabel("<br>".join(f"{name}: {count}"
                                                       for name, count in sorted(by_category.items()))))
        diagnostics_button = QPushButton(f"Diagnostics: {len(diagnostics)}")
        diagnostics_button.clicked.connect(self.show_diagnostics.emit)
        health_layout.addWidget(diagnostics_button)
        changes_text = ("Changes: first run" if changes is None
                        else f"Changes since last run: {len(changes)}")
        changes_button = QPushButton(changes_text)
        changes_button.clicked.connect(self.show_changes.emit)
        health_layout.addWidget(changes_button)
        health_layout.addStretch()
        middle.addWidget(health_box)

        tables_box = QGroupBox("Likely unused columns by table")
        tables_layout = QVBoxLayout(tables_box)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Table", "Likely unused", "Columns"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for name, unused, total in unused_by_table(objects):
            number = table.rowCount()
            table.insertRow(number)
            for column, value in enumerate((name, str(unused), str(total))):
                item = QTableWidgetItem(value)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(number, column, item)
        table.cellDoubleClicked.connect(lambda r, _c: self.show_objects.emit(
            Status.LIKELY_UNUSED, ObjectType.COLUMN, table.item(r, 0).text()))
        table.setToolTip("Double-click a table to list its Likely unused columns.")
        tables_layout.addWidget(table)
        middle.addWidget(tables_box, 2)
        layout.addLayout(middle, 1)

        guide = QGroupBox("How to read these results")
        guide_layout = QVBoxLayout(guide)
        text = "".join(f"<p><b>{info.label}</b>: {info.summary}</p>" for status, info in STATUS_INFO.items()
                       if status in BUSINESS_STATUSES)
        label = QLabel(text + f"<p><i>{LIKELY_UNUSED_CAVEAT}</i></p>")
        label.setWordWrap(True)
        guide_layout.addWidget(label)
        layout.addWidget(guide)
        self._layout.addWidget(self._content)


class CleanupTab(QWidget):
    object_selected = Signal(object)  # ObjectRow
    acknowledge_requested = Signal(str)  # key
    unacknowledge_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: tuple[ObjectRow, ...] = ()
        self.acknowledgements: dict[str, Acknowledgement] = {}
        self.ack_bar = _AcknowledgementBar()
        self.status = _combo([("All business objects", None)]
                             + [(STATUS_INFO[s].label, s) for s in BUSINESS_STATUSES]
                             + [(STATUS_INFO[Status.INTERNAL].label, Status.INTERNAL)])
        self.kind = _combo([("Columns and measures", None), ("Columns", ObjectType.COLUMN),
                            ("Measures", ObjectType.MEASURE)])
        self.table_filter = _combo([("All tables", None)])
        self.search = _search_box("Search table or object")
        self.internal = QCheckBox("Show internal objects")
        self.count = QLabel()
        filters = QHBoxLayout()
        for widget in (self.status, self.kind, self.table_filter, self.search, self.internal):
            filters.addWidget(widget)
        filters.addWidget(self.count)
        self.table = RowTable([
            Column("Table", lambda r: r.table), Column("Object", lambda r: r.name),
            Column("Type", lambda r: r.object_type.value), Column("Status", lambda r: r.status_label),
            Column("Hidden", lambda r: r.hidden), Column("Data type", lambda r: r.data_type),
            Column("Acknowledged", lambda r: _acknowledged(self.acknowledgements, r.key)),
        ], self)
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.ack_bar)
        layout.addWidget(self.table.view)
        for combo in (self.status, self.kind, self.table_filter):
            combo.currentIndexChanged.connect(self.apply)
        self.search.textChanged.connect(self.apply)
        self.internal.toggled.connect(self.apply)
        self.ack_bar.hide.toggled.connect(self.apply)
        self.ack_bar.acknowledge.clicked.connect(lambda: self._request(self.acknowledge_requested))
        self.ack_bar.remove.clicked.connect(lambda: self._request(self.unacknowledge_requested))
        self.table.view.selectionModel().selectionChanged.connect(self._selection_changed)

    def set_rows(self, rows: tuple[ObjectRow, ...]) -> None:
        self._rows = rows
        current = self.table_filter.currentData()
        self.table_filter.blockSignals(True)
        self.table_filter.clear()
        self.table_filter.addItem("All tables", None)
        for table in sorted({row.table for row in rows}, key=str.casefold):
            self.table_filter.addItem(table, table)
        _set_combo(self.table_filter, current)
        self.table_filter.blockSignals(False)
        self.apply()

    def set_filters(self, status=None, object_type=None, table=None) -> None:
        for widget in (self.status, self.kind, self.table_filter, self.search, self.internal):
            widget.blockSignals(True)
        _set_combo(self.status, status)
        _set_combo(self.kind, object_type)
        _set_combo(self.table_filter, table)
        self.search.clear()
        self.internal.setChecked(status == Status.INTERNAL)
        for widget in (self.status, self.kind, self.table_filter, self.search, self.internal):
            widget.blockSignals(False)
        self.apply()

    def apply(self) -> None:
        status, kind, table = self.status.currentData(), self.kind.currentData(), self.table_filter.currentData()
        include_internal = self.internal.isChecked() or status == Status.INTERNAL
        hidden = frozenset(self.acknowledgements) if self.ack_bar.hide.isChecked() else frozenset()
        rows = filter_objects(self._rows, statuses=None if status is None else [status],
                              types=None if kind is None else [kind],
                              tables=None if table is None else [table],
                              text=self.search.text(), include_internal=include_internal,
                              exclude_keys=hidden)
        self.table.set_rows(rows)
        shown = len(self._rows) if include_internal else sum(not row.internal for row in self._rows)
        self.count.setText(f"{len(rows)} of {shown}")
        self._selection_changed()

    def set_acknowledgements(self, acknowledgements: dict[str, Acknowledgement]) -> None:
        self.acknowledgements = acknowledgements
        self.apply()

    def _request(self, signal) -> None:
        row = self.table.selected()
        if row is not None:
            signal.emit(row.key)

    def select_key(self, key: str) -> bool:
        return _select_key(self.table, self.ack_bar, self.acknowledgements, key)

    def show_ref(self, ref) -> bool:
        """Clear the filters as needed and select the object."""
        row = next((r for r in self._rows if r.ref == ref), None)
        if row is None:
            return False
        self.set_filters(status=Status.INTERNAL if row.internal else None)
        return self.select_key(row.key)

    def _selection_changed(self) -> None:
        row = self.table.selected()
        self.ack_bar.update_buttons(row.key if row else None, self.acknowledgements)
        if row is not None:
            self.object_selected.emit(row)


class HealthTab(QWidget):
    finding_selected = Signal(object)  # HealthRow
    acknowledge_requested = Signal(str)  # key
    unacknowledge_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: tuple[HealthRow, ...] = ()
        self.acknowledgements: dict[str, Acknowledgement] = {}
        self.ack_bar = _AcknowledgementBar()
        self.severity = _combo([("All severities", None)]
                               + [(SEVERITY_LABELS[s], s) for s in (HealthSeverity.WARNING, HealthSeverity.INFO)])
        self.category = _combo([("All categories", None)])
        self.rule = _combo([("All rules", None)])
        self.search = _search_box("Search rule, scope or title")
        self.count = QLabel()
        filters = QHBoxLayout()
        for widget in (self.severity, self.category, self.rule, self.search, self.count):
            filters.addWidget(widget)
        self.table = RowTable([
            Column("Severity", lambda r: SEVERITY_LABELS[r.severity]), Column("Rule", lambda r: r.rule_name),
            Column("Scope", lambda r: r.scope_label), Column("Title", lambda r: r.title),
            Column("Confidence", lambda r: r.confidence), Column("Category", lambda r: r.category_label),
            Column("Acknowledged", lambda r: _acknowledged(self.acknowledgements, r.key)),
        ], self)
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.ack_bar)
        layout.addWidget(self.table.view)
        for combo in (self.severity, self.category, self.rule):
            combo.currentIndexChanged.connect(self.apply)
        self.search.textChanged.connect(self.apply)
        self.ack_bar.hide.toggled.connect(self.apply)
        self.ack_bar.acknowledge.clicked.connect(lambda: self._request(self.acknowledge_requested))
        self.ack_bar.remove.clicked.connect(lambda: self._request(self.unacknowledge_requested))
        self.table.view.selectionModel().selectionChanged.connect(self._selection_changed)

    def set_rows(self, rows: tuple[HealthRow, ...]) -> None:
        self._rows = rows
        for combo, items in ((self.category, sorted({(r.category_label, r.category) for r in rows})),
                             (self.rule, sorted({(r.rule_name, r.rule_id) for r in rows}))):
            current = combo.currentData()
            combo.blockSignals(True)
            while combo.count() > 1:
                combo.removeItem(1)
            for text, data in items:
                combo.addItem(text, data)
            _set_combo(combo, current)
            combo.blockSignals(False)
        self.apply()

    def set_filters(self, severity=None) -> None:
        for widget in (self.severity, self.category, self.rule, self.search):
            widget.blockSignals(True)
        _set_combo(self.severity, severity)
        _set_combo(self.category, None)
        _set_combo(self.rule, None)
        self.search.clear()
        for widget in (self.severity, self.category, self.rule, self.search):
            widget.blockSignals(False)
        self.apply()

    def apply(self) -> None:
        severity, category, rule = self.severity.currentData(), self.category.currentData(), self.rule.currentData()
        hidden = frozenset(self.acknowledgements) if self.ack_bar.hide.isChecked() else frozenset()
        rows = filter_health(self._rows, severities=None if severity is None else [severity],
                             categories=None if category is None else [category],
                             rule_ids=None if rule is None else [rule], text=self.search.text(),
                             exclude_keys=hidden)
        self.table.set_rows(rows)
        self.count.setText(f"{len(rows)} of {len(self._rows)}")
        self._selection_changed()

    def set_acknowledgements(self, acknowledgements: dict[str, Acknowledgement]) -> None:
        self.acknowledgements = acknowledgements
        self.apply()

    def _request(self, signal) -> None:
        row = self.table.selected()
        if row is not None:
            signal.emit(row.key)

    def select_key(self, key: str) -> bool:
        return _select_key(self.table, self.ack_bar, self.acknowledgements, key)

    def _selection_changed(self) -> None:
        row = self.table.selected()
        self.ack_bar.update_buttons(row.key if row else None, self.acknowledgements)
        if row is not None:
            self.finding_selected.emit(row)


def _select_key(table: RowTable, bar: _AcknowledgementBar, acknowledgements: dict, key: str) -> bool:
    """Select a row by key, showing acknowledged rows if that is what hides it."""
    if table.select(lambda row: row.key == key):
        return True
    if key in acknowledgements and bar.hide.isChecked():
        bar.hide.setChecked(False)  # re-applies the filters
        return table.select(lambda row: row.key == key)
    return False


def _acknowledged(acknowledgements: dict, key: str) -> str:
    item = acknowledgements.get(key)
    if item is None:
        return ""
    return item.note or f"yes ({item.acknowledged_at})"


class _ListTab(QWidget):
    """A plain table without filters (diagnostics, query dependencies)."""
    row_selected = Signal(object)

    def __init__(self, columns: list[Column], empty_text: str, parent=None):
        super().__init__(parent)
        self.table = RowTable(columns, self)
        self.empty = QLabel(empty_text)
        layout = QVBoxLayout(self)
        layout.addWidget(self.empty)
        layout.addWidget(self.table.view)
        self.table.view.selectionModel().selectionChanged.connect(self._selection_changed)

    def set_rows(self, rows: tuple) -> None:
        self.table.set_rows(rows)
        self.empty.setVisible(not rows)

    def _selection_changed(self) -> None:
        row = self.table.selected()
        if row is not None:
            self.row_selected.emit(row)


class DiagnosticsTab(_ListTab):
    def __init__(self, parent=None):
        super().__init__([
            Column("Code", lambda r: r.code), Column("Message", lambda r: r.message),
            Column("File", lambda r: Path(r.source_file).name if r.source_file else ""),
            Column("Line", lambda r: r.line),
        ], "No diagnostics: every source was read and traced.", parent)


class QueriesTab(_ListTab):
    def __init__(self, parent=None):
        super().__init__([
            Column("Query", lambda r: r.query), Column("Depends on", lambda r: r.depends_on),
            Column("Through load-disabled queries", lambda r: " -> ".join(r.via)),
            Column("File", lambda r: Path(r.source_file).name if r.source_file else ""),
        ], "No Power Query dependencies between model queries.", parent)

    def show_query(self, name: str) -> bool:
        return self.table.select(lambda row: name in (row.query, row.depends_on))


class ChangesTab(_ListTab):
    """Differences from the previous analysis of the same project."""

    def __init__(self, parent=None):
        super().__init__([
            Column("Change", lambda c: CHANGE_LABELS[c.kind.value]), Column("Item", lambda c: c.label),
            Column("Before", lambda c: c.before), Column("After", lambda c: c.after),
        ], "", parent)

    def set_changes(self, changes: tuple[Change, ...] | None, baseline: str | None) -> None:
        self.set_rows(changes or ())
        if changes is None:
            self.empty.setText("First analysis of this project on this computer: nothing to compare yet. "
                               "Re-run after changing the model to see what changed.")
        elif not changes:
            self.empty.setText(f"No changes since the previous analysis ({baseline}).")
        else:
            self.empty.setText(f"{len(changes)} changes since the previous analysis ({baseline}).")
        self.empty.setVisible(True)
