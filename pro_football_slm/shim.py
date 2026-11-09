"""Deprecated ``nfl-stat`` console-script shim (one release)."""
from __future__ import annotations

import sys


_NOTICE = (
    "pro-football-slm: the 'nfl-stat' command is deprecated; "
    "use 'pro-football-slm' or 'pfslm'. Running the new entry point.\n"
)


def main(argv=None) -> int:
    try:
        sys.stderr.write(_NOTICE)
    except Exception:
        pass
    from . import main as real_main
    return int(real_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
