"""Allow `python -m tidownloader.web` to run the web server."""

import sys

try:
    from tidownloader.web.server import main
except ImportError:
    from .server import main

if __name__ == "__main__":
    sys.exit(main())
