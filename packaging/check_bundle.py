"""Check a built app folder: no network components, no missing DLL dependencies.

Usage: python packaging/check_bundle.py "dist/PBI Model Health"

Exit code 1 lists problems: a network component that should have been left out
(see pbi_model_health.spec), or a bundled binary whose import table names a DLL
that is neither in the bundle nor part of Windows. Needs `pefile` (installed with
PyInstaller).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pefile

FORBIDDEN = {"qt6network.dll", "qtnetwork.pyd", "qtuiotouchplugin.dll", "libssl-3.dll", "_ssl.pyd"}
FORBIDDEN_FOLDERS = ("plugins/tls/", "plugins/networkinformation/")
SYSTEM = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def imports(path: Path) -> list[str]:
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                           pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    entries = getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
    return [entry.dll.decode("ascii", "replace").lower() for entry in entries]


def check(app: Path) -> list[str]:
    binaries = [p for p in app.rglob("*") if p.suffix.lower() in {".dll", ".pyd", ".exe"}]
    bundled = {p.name.lower() for p in binaries}
    problems = []
    for path in binaries:
        relative = path.relative_to(app).as_posix()
        if path.name.lower() in FORBIDDEN or any(folder in relative.lower() for folder in FORBIDDEN_FOLDERS):
            problems.append(f"network component present: {relative}")
            continue
        try:
            names = imports(path)
        except pefile.PEFormatError:
            continue
        for name in names:
            if name in bundled or name.startswith(("api-ms-win-", "ext-ms-")) or (SYSTEM / name).exists():
                continue
            problems.append(f"{relative} imports {name}, which is not bundled")
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        sys.exit("usage: python packaging/check_bundle.py <built app folder>")
    found = check(Path(sys.argv[1]))
    for problem in found:
        print(problem)
    print(f"Bundle check: {len(found)} problems")
    sys.exit(1 if found else 0)
