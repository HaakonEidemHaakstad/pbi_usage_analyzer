"""Write README.txt, the HTML documents, THIRD_PARTY_NOTICES.txt, LICENSES/, an SBOM
(sbom.cdx.json) and a SHA-256 manifest of every file into a built app folder.

Usage: python packaging/write_notices.py "dist/PBI Model Health"
       python packaging/write_notices.py --server "dist/pbi-model-health-mcp"

Run with the same environment that built the app: the bundled distributions are
the transitive runtime requirements of pandas, openpyxl and PySide6-Essentials.
`--server` is for the Claude Desktop extension's server, which bundles only the
Python runtime and the analyzer (no third-party distributions).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
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


def sbom(version: str, dists: list[metadata.Distribution], name: str = "PBI Model Health") -> dict:
    """CycloneDX 1.5 SBOM of the bundled runtime: Python and its distributions."""
    def licenses(dist: metadata.Distribution) -> list[dict]:
        expression = dist.metadata.get("License-Expression")
        return [{"expression": expression}] if expression else [{"license": {"name": license_text(dist)}}]

    python = sys.version.split()[0]
    components = [{"type": "platform", "name": "python", "version": python,
                   "purl": f"pkg:generic/python@{python}", "licenses": [{"license": {"id": "PSF-2.0"}}]}]
    for dist in dists:
        name = dist.metadata["Name"]
        components.append({"type": "library", "name": name, "version": dist.version,
                           "purl": f"pkg:pypi/{canonical(name)}@{dist.version}", "licenses": licenses(dist)})
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "metadata": {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "component": {"type": "application", "name": name, "version": version}},
        "components": components,
    }


def write_manifest(app_folder: Path) -> None:
    """SHA-256 of every file in the folder (for allowlisting and integrity checks)."""
    name = "MANIFEST-SHA256.txt"
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(app_folder).as_posix()}"
             for path in sorted(p for p in app_folder.rglob("*") if p.is_file() and p.name != name)]
    (app_folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")


def readme(version: str) -> str:
    return f"""Power BI Model Health Analyzer {version}
=====================================

Start "PBI Model Health.exe" and open a Power BI project folder (PBIP saved
with the PBIR report format and TMDL semantic model format), or pass the
folder or .pbip file on the command line. "User manual.html" (also Help > User
manual, F1) explains every screen.

"pbi-model-health-cli.exe" writes the text and Excel reports without a window:
drop a project folder onto it, or run it from a command prompt with one or more
project folders (--out FOLDER for one report folder, --help for all options).

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
    sys.path.insert(0, str(HERE))
    from build_manual import build as build_manual  # packaging/build_manual.py

    build_manual(app_folder / "User manual.html")
    build_manual(app_folder / "IT security fact sheet.html", HERE.parent / "docs" / "IT_SECURITY_FACT_SHEET.md")
    (app_folder / "sbom.cdx.json").write_text(
        json.dumps(sbom(__version__, runtime_distributions()), indent=2), encoding="utf-8")
    write_manifest(app_folder)  # last: covers every file written above


def server_readme(version: str) -> str:
    return f"""Power BI Model Health Analyzer {version}: server for Claude Desktop
==================================================================

Claude Desktop starts "pbi-model-health-mcp.exe" when this extension is enabled
and talks to it over standard input/output (Model Context Protocol). It reads the
Power BI projects you name in the chat and never changes them. It makes no network
connections; Claude Desktop sends the results you approve to Claude.

Its only file output is one baseline per project (save_baseline) in
%APPDATA%\\pbi-usage-analyzer\\Power BI Model Health Analyzer\\assistant\\.

"Likely unused" marks a cleanup candidate, not proof that deletion is safe.

The Python runtime is listed in THIRD_PARTY_NOTICES.txt with its license under
LICENSES\\. Packaged with PyInstaller, whose bootloader is licensed under the GPL
with an exception that permits this kind of distribution.
"""


def main_server(folder: Path) -> None:
    """Notices for the extension's server folder: Python runtime only."""
    sys.path.insert(0, str(HERE.parent))
    from pbi_usage_analyzer import __version__

    licenses = folder / "LICENSES"
    if licenses.exists():
        shutil.rmtree(licenses)
    (licenses / "Python").mkdir(parents=True)
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python" / "LICENSE.txt")
    lines = ["Third-party software included in this extension", "=" * 48, "",
             f"Python {sys.version.split()[0]} - PSF License - LICENSES\\Python\\LICENSE.txt", ""]
    (folder / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")
    (folder / "README.txt").write_text(server_readme(__version__), encoding="utf-8", newline="\r\n")
    (folder / "sbom.cdx.json").write_text(
        json.dumps(sbom(__version__, [], "PBI Model Health MCP server"), indent=2), encoding="utf-8")
    write_manifest(folder)


if __name__ == "__main__":
    arguments = sys.argv[1:]
    server = arguments[:1] == ["--server"]
    arguments = arguments[1:] if server else arguments
    if len(arguments) != 1 or not Path(arguments[0]).is_dir():
        sys.exit("usage: python packaging/write_notices.py [--server] <built folder>")
    (main_server if server else main)(Path(arguments[0]))
