"""Entrypoint operacional; detalhes de persistência ficam em database."""

from .database.cli import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
