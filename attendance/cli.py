from __future__ import annotations

import argparse
import getpass
import json
import secrets
from datetime import datetime
from pathlib import Path

from argon2 import PasswordHasher

from .database import AttendanceRepository


def _write_config(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def initialize(args: argparse.Namespace) -> int:
    config_path = Path(args.config_path).resolve()
    existing: dict[str, object] = {}
    if config_path.exists():
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        if not args.force:
            print(f"Configuração já existe: {config_path}")
            return 0

    default_user = str(existing.get("admin_username") or "roberto")
    username = input(f"Usuário administrador [{default_user}]: ").strip() or default_user
    while True:
        password = getpass.getpass("Nova senha: ")
        confirmation = getpass.getpass("Confirme a senha: ")
        if password != confirmation:
            print("As senhas não coincidem.")
            continue
        if not password:
            print("A senha não pode ficar vazia.")
            continue
        break

    data = {
        "admin_username": username,
        "password_hash": PasswordHasher().hash(password),
        "secret_key": str(existing.get("secret_key") or secrets.token_urlsafe(48)),
        "db_path": str(Path(args.db_path).resolve()),
        "backup_dir": str(Path(args.backup_dir).resolve()),
        "cookie_secure": bool(args.secure_cookie),
        "session_max_age_seconds": 43200,
    }
    _write_config(config_path, data)
    print(f"Configuração criada: {config_path}")
    return 0


def reset_password(args: argparse.Namespace) -> int:
    config_path = Path(args.config_path).resolve()
    if not config_path.exists():
        raise SystemExit(f"Configuração não encontrada: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    while True:
        password = getpass.getpass("Nova senha: ")
        confirmation = getpass.getpass("Confirme a senha: ")
        if password != confirmation:
            print("As senhas não coincidem.")
            continue
        if not password:
            print("A senha não pode ficar vazia.")
            continue
        break
    data["password_hash"] = PasswordHasher().hash(password)
    data["secret_key"] = secrets.token_urlsafe(48)
    _write_config(config_path, data)
    print("Senha redefinida. Todas as sessões anteriores foram invalidadas.")
    return 0


def backup(args: argparse.Namespace) -> int:
    config_path = Path(args.config_path).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    backup_dir = Path(str(data["backup_dir"]))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    repository = AttendanceRepository(Path(str(data["db_path"])))
    repository.initialize()
    destination = repository.backup_to(backup_dir / f"presencas-{timestamp}.db")
    backups = sorted(backup_dir.glob("presencas-*.db"), reverse=True)
    for old_backup in backups[max(args.keep, 1) :]:
        old_backup.unlink()
    print(destination)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administração do registrador.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Criar configuração segura.")
    init_parser.add_argument("--config-path", required=True)
    init_parser.add_argument("--db-path", required=True)
    init_parser.add_argument("--backup-dir", required=True)
    init_parser.add_argument("--secure-cookie", action="store_true")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=initialize)

    reset_parser = subparsers.add_parser("reset-password", help="Redefinir senha.")
    reset_parser.add_argument("--config-path", required=True)
    reset_parser.set_defaults(handler=reset_password)

    backup_parser = subparsers.add_parser("backup", help="Criar e rotacionar backup.")
    backup_parser.add_argument("--config-path", required=True)
    backup_parser.add_argument("--keep", type=int, default=30)
    backup_parser.set_defaults(handler=backup)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
