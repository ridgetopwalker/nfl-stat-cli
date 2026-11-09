#!/usr/bin/env python3
"""Compatibility launcher for the nfl_stat_cli package."""
import nfl_stat_cli as _package

# Preserve the former module's public and private attributes for legacy imports.
globals().update({name: value for name, value in vars(_package).items()
                  if not name.startswith("__") or name in ("__version__", "__author__", "__license__")})

if __name__ == "__main__":
    import sys
    sys.exit(_package.main())
