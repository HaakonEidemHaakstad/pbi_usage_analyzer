"""Entry script for the frozen Windows application (see pbi_model_health.spec)."""
import sys

from pbi_usage_analyzer_gui.app import main

if __name__ == "__main__":
    sys.exit(main())
