"""Compatibility entrypoint for the staging-guarded index preflight."""
import sys
from preflight_index_check import main


if __name__ == "__main__":
    sys.exit(main())
