#!/usr/bin/env python
"""Shortcut launcher — same as `ps-daily`, but runnable without `pip install -e .`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cli.run_daily import main

if __name__ == "__main__":
    main()
