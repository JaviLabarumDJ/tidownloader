"""Allow `python -m tidownloader` to run the CLI."""

import sys

try:
    from tidownloader.cli import main
except ImportError:
    from .cli import main

if __name__ == "__main__":
    sys.exit(main())
