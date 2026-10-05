"""Entry point: run the MCP server on stdio, or print a Claude Desktop config entry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pbi_usage_analyzer import __version__

from .protocol import McpServer
from .tools import INSTRUCTIONS, AnalyzerTools

SERVER_NAME = "pbi-model-health"


def build_server(data_dir: Path | None = None) -> McpServer:
    tools = AnalyzerTools(data_dir)
    return McpServer(SERVER_NAME, "Power BI Model Health Analyzer", __version__, INSTRUCTIONS,
                     tools.tools(), tools.prompts())


def config_entry() -> dict:
    """The `mcpServers` entry that starts this server the way it is running now."""
    if getattr(sys, "frozen", False):  # pbi-model-health-cli.exe --mcp
        return {"command": sys.executable, "args": ["--mcp"]}
    root = Path(__file__).resolve().parent.parent
    return {"command": sys.executable, "args": ["-m", "pbi_usage_analyzer_mcp"],
            "env": {"PYTHONPATH": str(root), "PYTHONUTF8": "1"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pbi_usage_analyzer_mcp",
        description="Model Context Protocol server for Claude Desktop (stdio). Reads Power BI projects; "
                    "never writes to them and makes no network connections.")
    parser.add_argument("--config", action="store_true",
                        help="print the Claude Desktop configuration entry for this installation and exit")
    parser.add_argument("--data-dir", type=Path, help="per-user state folder (default: the desktop app's)")
    args = parser.parse_args(argv)
    if args.config:
        print(json.dumps({"mcpServers": {SERVER_NAME: config_entry()}}, indent=2))
        return 0
    build_server(args.data_dir).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
