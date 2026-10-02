"""Frozen entry point: the local web edition (one backend process, opened in the browser)."""
from repairshop.server import main

if __name__ == "__main__":
    raise SystemExit(main())
