"""Compatibilidade temporária para a CLI canônica em :mod:`handball.cli`."""

from handball.database.cli import *  # noqa: F401,F403
from handball.database.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
