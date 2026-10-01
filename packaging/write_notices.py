"""Write README.txt, THIRD_PARTY_NOTICES.txt and LICENSES/ into a built app folder.

Usage: python packaging/write_notices.py "dist/PBI Model Health"

Run with the same environment that built the app: the bundled distributions are
the transitive runtime requirements of pandas, openpyxl and PySide6-Essentials.
"""
from __future__ import annotations

import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

HERE = Path(__file__).resolve().parent
ROOTS = ("pandas", "openpyxl", "PySide6-Essentials")
LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.I)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_distributions() -> list[metadata.Distribution]:
    """Transitive requirements of ROOTS whose markers apply here (no extras)."""
    found: dict[str, metadata.Distribution] = {}
    pending = list(ROOTS)
    while pending:
        name = canonical(pending.pop())
        if name in found:
            continue
        dist = metadata.distribution(name)
        found[name] = dist
        for text in dist.requires or ():
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    return sorted(found.values(), key=lambda d: canonical(d.metadata["Name"]))


def license_text(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    declared = (meta.get("License") or "").strip()
    if declared and "\n" not in declared and len(declared) < 100:
        return declared
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or () if c.startswith("License ::")]
    return ", ".join(classifiers) or "see the license files"


def readme(version: str) -> str:
    return f"""Power BI Model Health Analyzer {version}
=====================================

Start "PBI Model Health.exe" and open a Power BI project folder (PBIP saved
with the PBIR report format and TMDL semantic model format), or pass the
folder or .pbip file on the command line.

The analyzer only reads the project. It never changes or deletes anything.
"Likely unused" marks a cleanup candidate, not proof that deletion is safe:
static analysis cannot see other reports on the same semantic model, external
tools, or Power BI constructs the analyzer does not support. Remove a few
objects at a time and validate in Power BI Desktop.

Settings (recent projects) are stored per Windows user under
HKEY_CURRENT_USER\\Software\\pbi-usage-analyzer.

Qt and the GNU LGPL
-------------------
This application uses the Qt 6 libraries through Qt for Python (PySide6),
licensed under the GNU Lesser General Public License version 3 (LGPLv3); see
LICENSES\\Qt\\LGPL-3.0.txt and LICENSES\\Qt\\GPL-3.0.txt. The Qt and PySide6
libraries are included unmodified as separate files in the _internal\\PySide6
and _internal\\shiboken6 folders, and you may replace them with compatible
versions of your own build. Source code:
  Qt:      https://download.qt.io/official_releases/qt/
  PySide6: https://code.qt.io/cgit/pyside/pyside-setup.git/
Qt contains third-party components under their own licenses:
  https://doc.qt.io/qt-6/licenses-used-in-qt.html

Other third-party software, including the Python runtime, is listed in
THIRD_PARTY_NOTICES.txt with its license files under LICENSES\\.
The application was packaged with PyInstaller, whose bootloader is licensed
under the GPL with an exception that permits this kind of distribution.
"""


def main(app_folder: Path) -> None:
    sys.path.insert(0, str(HERE.parent))
    from pbi_usage_analyzer import __version__

    licenses = app_folder / "LICENSES"
    if licenses.exists():
        shutil.rmtree(licenses)
    (licenses / "Qt").mkdir(parents=True)
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        shutil.copyfile(HERE / "licenses" / name, licenses / "Qt" / name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    (licenses / "Python").mkdir()
    shutil.copyfile(python_license, licenses / "Python" / "LICENSE.txt")

    lines = ["Third-party software included in this application", "=" * 50, "",
             f"Python {sys.version.split()[0]} - PSF License - LICENSES\\Python\\LICENSE.txt", ""]
    for dist in runtime_distributions():
        name, version = dist.metadata["Name"], dist.version
        target = licenses / canonical(name)
        copied = []
        for file in dist.files or ():
            if ".dist-info" in str(file) and LICENSE_FILE.search(file.name):
                destination = target / Path(*file.parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dist.locate_file(file), destination)
                copied.append(destination.relative_to(app_folder))
        lines.append(f"{name} {version} - {license_text(dist)}")
        if dist.metadata.get("Home-page"):
            lines.append(f"  {dist.metadata['Home-page']}")
        if canonical(name) in {"pyside6-essentials", "shiboken6"}:
            lines.append("  Used under the GNU LGPL v3: LICENSES\\Qt\\LGPL-3.0.txt (see README.txt)")
        lines += [f"  {path}" for path in copied] + [""]
    # Notepad-friendly CRLF on every build host.
    (app_folder / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")
    (app_folder / "README.txt").write_text(readme(__version__), encoding="utf-8", newline="\r\n")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        sys.exit("usage: python packaging/write_notices.py <built app folder>")
    main(Path(sys.argv[1]))
