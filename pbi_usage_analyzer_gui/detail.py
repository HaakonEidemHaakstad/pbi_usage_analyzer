"""The detail panel: why an object has its status, or what a finding says."""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QTextBrowser

from pbi_usage_analyzer.model import ObjectRef, Status
from pbi_usage_analyzer.views import (EVIDENCE_LABELS, SEVERITY_LABELS, STATUS_INFO, DiagnosticRow,
                                      Explanation, HealthRow, ObjectRow, QueryDependencyRow, format_path)

# Status colours are a hint only; the label always carries the meaning. Qt follows
# the Windows light/dark setting, so each status has a shade for either background.
STATUS_COLOURS = {
    Status.USED: ("#2e7d32", "#81c784"),
    Status.MANUAL_REVIEW: ("#b26a00", "#ffb74d"),
    Status.LIKELY_UNUSED: ("#c62828", "#ef9a9a"),
    Status.INTERNAL: ("#616161", "#bdbdbd"),
}


def status_colour(status: Status) -> str:
    dark = QApplication.palette().color(QPalette.ColorRole.Base).lightness() < 128
    return STATUS_COLOURS[status][1 if dark else 0]


class _Html:
    """Collects HTML and the targets of its links (`link:N` hrefs)."""

    def __init__(self):
        self.parts: list[str] = []
        self.links: list[tuple] = []

    def add(self, html: str) -> None:
        self.parts.append(html)

    def heading(self, text: str) -> None:
        self.add(f"<h3 style='margin-bottom:2px'>{escape(text)}</h3>")

    def paragraph(self, text: str) -> None:
        self.add(f"<p>{escape(text)}</p>")

    def link(self, text: str, target: tuple) -> str:
        self.links.append(target)
        return f"<a href='link:{len(self.links) - 1}'>{escape(text)}</a>"

    def source(self, path: str, line: int | None) -> None:
        if not path:
            return
        where = Path(path).name + (f" line {line}" if line else "")
        self.add(f"<p><b>Source:</b> {self.link(where, ('file', path))}<br>"
                 f"<span style='color:gray'>{escape(path)}</span></p>")

    def html(self) -> str:
        return "".join(self.parts)


def object_html(row: ObjectRow, explanation: Explanation, status_of=lambda ref: None) -> _Html:
    """`status_of` gives the cleanup status of evidence sources (e.g. an unused measure)."""
    info = STATUS_INFO[row.status]
    out = _Html()
    out.add(f"<h2>{escape(row.ref.label)}</h2>")
    extra = ", ".join(x for x in (row.data_type, "calculated" if row.calculated else "",
                                  "hidden" if row.hidden else "") if x)
    out.add(f"<p style='color:gray'>{escape(row.object_type.value)}{escape(' · ' + extra) if extra else ''}</p>")
    out.add(f"<p><b style='color:{status_colour(row.status)}'>{escape(info.label)}</b> — "
            f"{escape(info.summary)}</p>")
    out.paragraph(info.explanation)
    if explanation.use_path:
        out.heading("Why it is used")
        out.add(f"<p><code>{escape(format_path(explanation.use_path))}</code></p>")
    if explanation.review_path:
        out.heading("Why it needs review")
        out.add(f"<p><code>{escape(format_path(explanation.review_path))}</code></p>")
    out.heading("Evidence")
    if explanation.evidence:
        items = []
        for ev in explanation.evidence:
            source = ""
            if ev.source_file and " | " not in ev.source_file and Path(ev.source_file).is_absolute():
                source = f" ({out.link(Path(ev.source_file).name, ('file', ev.source_file))})"
            elif ev.source_file:  # e.g. raw report hits: several report-relative files
                source = f" <span style='color:gray'>({escape(ev.source_file)})</span>"
            owner = status_of(ev.source) if ev.source is not None else None
            owner_note = ""
            if owner is not None and owner != Status.USED:
                owner_note = (f" — <span style='color:{status_colour(owner)}'>"
                              f"{escape(ev.source.label)} is {escape(STATUS_INFO[owner].label)}</span>")
            items.append(f"<li><b>{escape(EVIDENCE_LABELS[ev.evidence_type])}</b> "
                         f"<span style='color:gray'>[{escape(ev.confidence)}]</span>: "
                         f"{escape(ev.reason)}{owner_note}{source}</li>")
        out.add("<ul>" + "".join(items) + "</ul>")
    else:
        out.paragraph("No evidence points at this object.")
    out.source(row.source_file, row.source_line)
    return out


def health_html(row: HealthRow) -> _Html:
    out = _Html()
    out.add(f"<h2>{escape(row.title)}</h2>")
    out.add(f"<p style='color:gray'>{escape(row.rule_name)} · {escape(row.rule_id)}</p>")
    out.add(f"<p><b>{escape(SEVERITY_LABELS[row.severity])}</b> · confidence {escape(row.confidence)} · "
            f"{escape(row.category_label)}</p>")
    scope = escape(row.scope_label)
    if row.object_ref is not None:
        scope = out.link(row.scope_label, ("object", row.object_ref))
    if row.scope_label != row.scope:
        scope += f" <span style='color:gray'>({escape(row.scope)})</span>"
    out.add(f"<p><b>Scope:</b> {scope}</p>")
    out.paragraph(row.explanation)
    out.heading("Evidence")
    out.add("<ul>" + "".join(f"<li>{escape(item)}</li>" for item in row.evidence) + "</ul>")
    out.heading("Recommendation")
    out.paragraph(row.recommendation)
    out.source(row.source_file, row.line)
    return out


def diagnostic_html(row: DiagnosticRow) -> _Html:
    out = _Html()
    out.add(f"<h2>{escape(row.code)}</h2>")
    out.paragraph(row.message)
    if row.object_ref is not None:
        out.add(f"<p><b>Object:</b> {out.link(row.object_ref.label, ('object', row.object_ref))}</p>")
    out.paragraph("Diagnostics mean some sources could not be fully read or traced. Affected objects "
                  "get conservative manual-review evidence; treat the results as incomplete.")
    out.source(row.source_file, row.line)
    return out


def query_html(row: QueryDependencyRow) -> _Html:
    out = _Html()
    out.add(f"<h2>{escape(row.query)} ← {escape(row.depends_on)}</h2>")
    out.paragraph(f"The M of query '{row.query}' reads query '{row.depends_on}'.")
    if row.via:
        out.paragraph("Through load-disabled queries: " + " -> ".join(row.via))
    out.source(row.source_file, None)
    return out


class DetailPanel(QTextBrowser):
    open_file = Signal(str)
    show_object = Signal(object)  # ObjectRef

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._clicked)
        self._links: list[tuple] = []
        self.clear_detail()

    def clear_detail(self) -> None:
        self._links = []
        self.setHtml("<p style='color:gray'>Select a row to see its details and evidence.</p>")

    def show_html(self, content: _Html) -> None:
        self._links = content.links
        self.setHtml(content.html())

    def _clicked(self, url: QUrl) -> None:
        text = url.toString()
        if not text.startswith("link:"):
            return
        kind, target = self._links[int(text[5:])]
        if kind == "file":
            self.open_file.emit(target)
        elif kind == "object" and isinstance(target, ObjectRef):
            self.show_object.emit(target)
