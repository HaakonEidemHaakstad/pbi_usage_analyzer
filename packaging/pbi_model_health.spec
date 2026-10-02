# PyInstaller spec: one-folder, windowed build of the desktop GUI.
# Build with scripts\build_windows.ps1 (runs from the repository root).
# One folder (not one file) keeps the Qt libraries as separate, replaceable DLLs,
# as the LGPL requires.
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (provided by PyInstaller)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "pbi_model_health.py")],
    pathex=[str(ROOT)],
    # pandas loads the Excel writer engine by name at run time.
    hiddenimports=["openpyxl"],
    # Not used at run time: development/validation tools and other GUI toolkits.
    # No network stack either: the app makes no connections, so Qt's network module
    # and Python's TLS support are left out (see the binary filter below).
    excludes=["tkinter", "jsonschema", "PyQt5", "PyQt6", "IPython", "matplotlib", "pytest",
              "PySide6.QtNetwork", "ssl", "_ssl"],
    noarchive=False,
)
# A Qt Widgets app needs neither Mesa's software OpenGL renderer (20 MB, own
# license) nor Qt's translations (the interface is English, no translator is loaded).
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() != "opengl32sw.dll"]
# Network-only Qt parts: the network library and its Python binding, the TLS and
# network-information plugins, and the TUIO touch plugin (which listens on UDP).
# Only these import Qt6Network.dll; the build verifies that nothing
# left in the app depends on a removed file (packaging/check_bundle.py).
NETWORK_FILES = {"qt6network.dll", "qtnetwork.pyd", "qtuiotouchplugin.dll", "libssl-3.dll", "_ssl.pyd"}
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in NETWORK_FILES
              and not any(part in entry[0].replace("\\", "/") for part in ("/plugins/tls/", "/plugins/networkinformation/"))]
a.datas = [entry for entry in a.datas if "PySide6/translations/" not in entry[0].replace("\\", "/")]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PBI Model Health",
    console=False,
    upx=False,
)
# Console companion from the same analysis: writes reports without a window. The
# entry script chooses the mode by the executable's name ("-cli").
cli_exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pbi-model-health-cli",
    console=True,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    cli_exe,
    a.binaries,
    a.datas,
    name="PBI Model Health",
    upx=False,
)
