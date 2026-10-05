"""Entry script of the Claude Desktop extension's server (see pbi_model_health_mcp.spec).

A console executable that only serves the Model Context Protocol on stdio; it
contains no GUI, no Excel writer and no network stack.
"""
import sys

from pbi_usage_analyzer_mcp.server import main

if __name__ == "__main__":
    sys.exit(main())
