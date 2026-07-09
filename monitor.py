#!/usr/bin/env python3
"""fare-watch CLI shim. See `python monitor.py --help`."""
from farewatch.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
