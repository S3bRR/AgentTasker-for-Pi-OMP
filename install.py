#!/usr/bin/env python3
"""Bootstrap from a checkout without importing/installing third-party dependencies."""
import sys

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required")

from agent_tasker_mcp.installation import main

if __name__ == "__main__":
    raise SystemExit(main())
