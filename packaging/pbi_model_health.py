"""Entry script for both frozen Windows executables (see pbi_model_health.spec).

"PBI Model Health.exe" starts the desktop app. "pbi-model-health-cli.exe" (same
script, console build) writes the text and Excel reports without a window, like
run_analyzer.py; dropping a project folder onto it works too. With `--mcp` it is the
Model Context Protocol server Claude Desktop starts (`--mcp --config` prints the
configuration entry).
"""
import os
import sys
from pathlib import Path


def _own_console_window() -> bool:
    """True when Windows created the console just for this process (double-click or
    drag-and-drop), so it would vanish before the summary can be read."""
    if os.environ.get("PBI_NO_PAUSE") or not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        import ctypes
        processes = (ctypes.c_uint32 * 2)()
        return ctypes.windll.kernel32.GetConsoleProcessList(processes, 2) == 1
    except (AttributeError, OSError):
        return False


def console_main() -> int:
    if sys.argv[1:2] == ["--mcp"]:
        # Started by Claude Desktop: MCP over stdio, never a pause prompt.
        from pbi_usage_analyzer_mcp.server import main as mcp_main
        return mcp_main(sys.argv[2:])
    from pbi_usage_analyzer.main import cli  # no Qt in the console build path
    try:
        return cli()
    finally:
        if _own_console_window():
            input("\nPress Enter to close this window.")


if __name__ == "__main__":
    if Path(sys.executable).stem.casefold().endswith("-cli"):
        sys.exit(console_main())
    from pbi_usage_analyzer_gui.app import main
    sys.exit(main())
