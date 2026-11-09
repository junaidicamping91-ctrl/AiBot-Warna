#!/usr/bin/env python3
"""Launcher dari ROOT proyek (cara paling aman, tidak peduli working directory).

    python run.py --synthetic --mock --headless
    python run.py --camera 0 --mock
    python run.py --port COM3
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _p in (str(ROOT / "python"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
