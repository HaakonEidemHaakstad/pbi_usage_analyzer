# PyInstaller spec: one-folder console build of the MCP server for the Claude
# Desktop extension (.mcpb). Build with scripts\build_windows.ps1.
# The server uses the analyzer core and the standard library only: no Qt, no
# pandas/openpyxl (Excel reports are not written here), no TLS. One folder (not one
# file) so Claude Desktop starts it without unpacking to a temporary folder.
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (provided by PyInstaller)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "pbi_model_health_mcp.py")],
    pathex=[str(ROOT)],
    hiddenimports=[],
    excludes=["tkinter", "jsonschema", "IPython", "matplotlib", "pytest", "markdown",
              "PySide6", "shiboken6", "PyQt5", "PyQt6",
              "pandas", "numpy", "openpyxl", "lxml",
              "ssl", "_ssl", "asyncio", "http", "urllib.request", "email", "xmlrpc"],
    noarchive=False,
)
NETWORK_FILES = {"libssl-3.dll", "_ssl.pyd"}
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in NETWORK_FILES]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pbi-model-health-mcp",
    console=True,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="pbi-model-health-mcp",
    upx=False,
)
