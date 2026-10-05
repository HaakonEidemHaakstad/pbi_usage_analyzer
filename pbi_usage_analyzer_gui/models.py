"""A generic, read-only Qt table model over immutable `views` rows."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, NamedTuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableView

SORT_ROLE = Qt.ItemDataRole.UserRole


class Column(NamedTuple):
    header: str
    value: Callable[[Any], Any]
    # Optional: sort by this key instead of the displayed value (e.g. severity order).
    sort: Callable[[Any], Any] | None = None
    # Optional: text colour (a colour name such as "#c62828"), or None for the default.
    foreground: Callable[[Any], str | None] | None = None
    # Optional: tooltip text instead of the displayed value.
    tooltip: Callable[[Any], str] | None = None


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else ""
    return str(value)


def _sort_key(value: Any):
    """Numbers sort numerically, text case-insensitively, empty values first."""
    if value is None:
        return (0, 0, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (1, value, "")
    return (2, 0, _display(value).casefold())


class RowTableModel(QAbstractTableModel):
    def __init__(self, columns: Sequence[Column], parent=None):
        super().__init__(parent)
        self._columns = tuple(columns)
        self._rows: tuple = ()

    @property
    def rows(self) -> tuple:
        return self._rows

    def set_rows(self, rows: Iterable) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def row(self, index: int):
        return self._rows[index]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (Qt API)
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        column, row = self._columns[index.column()], self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return _display(column.value(row))
        if role == Qt.ItemDataRole.ToolTipRole:
            return column.tooltip(row) if column.tooltip else _display(column.value(row))
        if role == SORT_ROLE:
            return _sort_key(column.sort(row) if column.sort else column.value(row))
        if role == Qt.ItemDataRole.ForegroundRole and column.foreground:
            colour = column.foreground(row)
            return QColor(colour) if colour else None
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section].header
        return None


class _SelectionAwareDelegate(QStyledItemDelegate):
    """Coloured text (Column.foreground) would be unreadable on the selection
    highlight, so selected cells use the palette's highlighted-text colour."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 (Qt API)
        super().initStyleOption(option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            option.palette.setBrush(QPalette.ColorRole.Text, option.palette.brush(QPalette.ColorRole.HighlightedText))


class _SortProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        return left.data(SORT_ROLE) < right.data(SORT_ROLE)


class RowTable:
    """A sortable, single-selection table view over a `RowTableModel`."""

    def __init__(self, columns: Sequence[Column], parent=None):
        self.model = RowTableModel(columns, parent)
        self.proxy = _SortProxy(parent)
        self.proxy.setSourceModel(self.model)
        self.view = QTableView(parent)
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(_SelectionAwareDelegate(self.view))
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setWordWrap(False)
        self.view.verticalHeader().hide()
        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.view.sortByColumn(-1, Qt.SortOrder.AscendingOrder)  # keep source order until asked

    def set_rows(self, rows: Iterable) -> None:
        selected = self.selected()
        self.model.set_rows(rows)
        self.view.resizeColumnsToContents()
        if selected is not None:
            self.select(lambda row: row == selected)

    def selected(self):
        indexes = self.view.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.model.row(self.proxy.mapToSource(indexes[0]).row())

    def select(self, predicate: Callable[[Any], bool]) -> bool:
        """Select and show the first row matching `predicate`; False if none."""
        for number, row in enumerate(self.model.rows):
            if predicate(row):
                index = self.proxy.mapFromSource(self.model.index(number, 0))
                self.view.selectRow(index.row())
                self.view.scrollTo(index)
                return True
        return False
