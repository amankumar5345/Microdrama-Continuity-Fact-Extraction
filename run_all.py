"""
run_all.py
----------
Root-level convenience wrapper for the Continuity Checker pipeline.

The implementation lives in ``continuity/run_all.py`` (shared with
``python -m continuity.run_all``); this file only makes ``python run_all.py``
work from the project root without duplicating the orchestration logic.

Usage:
    python run_all.py
    python run_all.py --eps 1 2 3
    python run_all.py --skip-extract
    python run_all.py --rebuild-aliases
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from continuity.run_all import main  # noqa: E402


if __name__ == "__main__":
    main()
