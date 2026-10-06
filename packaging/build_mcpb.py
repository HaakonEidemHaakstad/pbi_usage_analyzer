"""Pack the built MCP server folder into a Claude Desktop extension (.mcpb).

Usage: python packaging/build_mcpb.py "dist/pbi-model-health-mcp" "dist/PBI-Model-Health-<version>.mcpb"

An .mcpb file is a zip archive with `manifest.json` at its root (MCPB manifest
specification 0.3, https://github.com/modelcontextprotocol/mcpb). The server is a
self-contained "binary" server: the frozen `pbi-model-health-mcp.exe` and its
runtime under `server/`. Claude Desktop installs it with a double-click and starts
it over stdio. Tool names and descriptions come from the server itself.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST_VERSION = "0.3"
EXTENSION_NAME = "pbi-model-health"
EXECUTABLE = "pbi-model-health-mcp.exe"
REPOSITORY = "https://github.com/HaakonEidemHaakstad/pbi_usage_analyzer"


def manifest() -> dict:
    sys.path.insert(0, str(HERE.parent))
    from pbi_usage_analyzer import __version__
    from pbi_usage_analyzer_mcp.tools import AnalyzerTools

    tools = AnalyzerTools(Path("unused"))
    return {
        "manifest_version": MANIFEST_VERSION,
        "name": EXTENSION_NAME,
        "display_name": "Power BI Model Health Analyzer",
        "version": __version__,
        "description": "Analyze Power BI projects (PBIP) for unused objects and model-health issues, "
                       "and evaluate your changes.",
        "long_description": (
            "Runs the Power BI Model Health Analyzer on your computer. Ask Claude to analyze a Power BI "
            "project (a PBIP folder saved with the PBIR report and TMDL model formats): it explains the "
            "findings, suggests next steps towards best practice, and compares the model before and after "
            "your changes. It can also make metadata improvements (descriptions, display folders, format "
            "strings, hidden fields) for you in a working copy.\n\nThe analyzer never changes your original "
            "project: changes go only to a working copy it creates next to the project, are checked by "
            "re-analysis, rolled back automatically if anything else changed, and can be undone. "
            "It makes no network connections itself; results you approve are sent to Claude as part of "
            "the conversation. \"Likely unused\" marks a cleanup candidate, not proof that deletion is "
            "safe."),
        "author": {"name": "pbi-usage-analyzer"},
        "repository": {"type": "git", "url": REPOSITORY},
        "keywords": ["power bi", "pbip", "tmdl", "pbir", "dax", "power query", "model health"],
        "server": {
            "type": "binary",
            "entry_point": f"server/{EXECUTABLE}",
            "mcp_config": {"command": f"${{__dirname}}/server/{EXECUTABLE}", "args": [], "env": {}},
        },
        "tools": [{"name": tool.name, "description": tool.description} for tool in tools.tools()],
        "tools_generated": False,
        # Prompt templates are served by the server (their text includes a fresh analysis).
        "prompts_generated": True,
        "compatibility": {"platforms": ["win32"]},
    }


def build(server_folder: Path, output: Path) -> Path:
    if not (server_folder / EXECUTABLE).is_file():
        raise SystemExit(f"{server_folder} does not contain {EXECUTABLE}")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in server_folder.rglob("*") if p.is_file())
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", json.dumps(manifest(), indent=2, ensure_ascii=False) + "\n")
        for path in files:
            archive.write(path, "server/" + path.relative_to(server_folder).as_posix())
    return output


if __name__ == "__main__":
    if len(sys.argv) != 3 or not Path(sys.argv[1]).is_dir():
        sys.exit("usage: python packaging/build_mcpb.py <built server folder> <output .mcpb>")
    result = build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Extension ({result.stat().st_size / 1e6:.1f} MB): {result}")
