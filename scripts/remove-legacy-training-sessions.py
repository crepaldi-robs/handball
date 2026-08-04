"""Remove chamadas legadas específicas com backup e auditoria de segurança.

Execute primeiro sem --execute. Para efetivar, informe novamente todas as
datas na confirmação; isto impede remoção por engano de outro intervalo.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from handball.database.maintenance import (  # noqa: E402
    execute_legacy_training_removal,
    preview_legacy_training_removal,
)
from handball.database.manager import DatabaseManager  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", required=True, type=Path)
    parser.add_argument("--actor-username", required=True)
    parser.add_argument("--date", action="append", dest="dates", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--confirm-dates",
        help="Datas AAAA-MM-DD separadas por vírgula, exatamente como --date.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manager = DatabaseManager.from_config(args.config_path)
    preview = preview_legacy_training_removal(manager, dates=args.dates)
    if not args.execute:
        print(json.dumps({"mode": "preview", **preview}, ensure_ascii=False, indent=2))
        return 0
    confirmation = tuple(
        sorted(value.strip() for value in str(args.confirm_dates or "").split(",") if value.strip())
    )
    if confirmation != tuple(preview["dates"]):
        raise SystemExit("--confirm-dates deve repetir exatamente as datas da prévia.")
    result = execute_legacy_training_removal(
        manager, dates=args.dates, actor_username=args.actor_username
    )
    print(json.dumps({"mode": "executed", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
