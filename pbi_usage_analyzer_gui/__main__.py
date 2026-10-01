import importlib.util
import sys

if importlib.util.find_spec("PySide6") is None:
    sys.exit("The GUI needs PySide6. Install it into this environment with:\n"
             "    python -m pip install -r requirements-gui.txt")

from .app import main  # noqa: E402

sys.exit(main())
