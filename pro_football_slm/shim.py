"""Permanent ``nfl-stat`` console-script alias."""
from __future__ import annotations


def main(argv=None) -> int:
    from . import main as real_main
    return int(real_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
