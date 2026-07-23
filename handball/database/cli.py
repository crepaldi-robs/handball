from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path

from argon2 import PasswordHasher

from . import AttendanceRepository
from .migrations import (
    FINGERPRINT_FORMAT,
    MAX_SUPPORTED_SCHEMA_VERSION,
    MIN_SUPPORTED_SCHEMA_VERSION,
    DatabaseMigrator,
    logical_fingerprint,
    migration_manifest,
    verify_database as inspect_database,
)


def release_contract(_args: argparse.Namespace) -> int:
    """Emite o contrato de schema aceito pelo código, sem acessar o banco."""

    print(
        json.dumps(
            {
                "format": 1,
                "schema_compatibility": {
                    "minimum": MIN_SUPPORTED_SCHEMA_VERSION,
                    "maximum": MAX_SUPPORTED_SCHEMA_VERSION,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _write_config(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_config(path_value: str | Path) -> tuple[Path, dict[str, object]]:
    config_path = Path(path_value).resolve()
    if not config_path.is_file():
        raise SystemExit(f"Configuração não encontrada: {config_path}")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Configuração inválida: {config_path}") from exc
    if not data.get("db_path"):
        raise SystemExit("Configuração inválida: db_path ausente.")
    return config_path, data


def _repository_from_config(data: dict[str, object]) -> AttendanceRepository:
    return AttendanceRepository(Path(str(data["db_path"])))


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


def initialize_database(args: argparse.Namespace) -> int:
    """Cria o SQLite somente no bootstrap explícito da primeira instalação."""

    _, data = _load_config(args.config_path)
    repository = _repository_from_config(data)
    username = str(data.get("admin_username") or "").strip()
    password_hash = str(data.get("password_hash") or "").strip()
    repository.bootstrap(
        legacy_admin=(username, password_hash) if username and password_hash else None
    )
    print(repository.db_path.resolve())
    return 0


def verify_database(args: argparse.Namespace) -> int:
    """Valida banco existente sem criar, migrar ou executar seed."""

    _, data = _load_config(args.config_path)
    repository = _repository_from_config(data)
    repository.validate_existing(quick_check=True)
    print("ok")
    return 0


def _migration_plan(data: dict[str, object]) -> dict[str, object]:
    repository = _repository_from_config(data)
    migrator = DatabaseMigrator(repository.db_path)
    status = migrator.status()
    fingerprint = (
        logical_fingerprint(repository.db_path)
        if repository.db_path.is_file()
        else None
    )
    action = "none"
    if status.state in {"missing", "empty"}:
        action = "bootstrap-required"
    elif status.problems:
        action = "blocked"
    elif not status.versioned and status.state == "legacy_current":
        action = "adopt-baseline"
    elif status.pending_versions:
        action = "migrate"
    problems = list(status.problems)
    if (
        2 in status.pending_versions
        and repository.db_path.is_file()
        and (
            not str(data.get("admin_username") or "").strip()
            or not str(data.get("password_hash") or "").strip()
        )
    ):
        problems.append(
            "A migração v2 requer admin_username e password_hash na configuração."
        )
        action = "blocked"
    payload: dict[str, object] = {
        "action": action,
        "database_path": status.database_path,
        "from_version": status.current_version,
        "to_version": status.latest_version,
        "versioned": status.versioned,
        "pending_versions": list(status.pending_versions),
        "compatible_with_application": status.compatible,
        "fingerprint_format": FINGERPRINT_FORMAT,
        "logical_fingerprint": fingerprint,
        "problems": problems,
        "migration_manifest": migration_manifest(status),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["plan_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def database_status(args: argparse.Namespace) -> int:
    """Mostra versão/compatibilidade em modo estritamente somente leitura."""

    _, data = _load_config(args.config_path)
    repository = _repository_from_config(data)
    status = DatabaseMigrator(repository.db_path).status().to_dict()
    verification = inspect_database(repository.db_path)
    print(
        json.dumps(
            {"schema": status, "verification": verification},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if verification["ok"] and status["compatible"] else 2


def database_plan(args: argparse.Namespace) -> int:
    """Produz plano estável sem criar arquivo, backup ou migration."""

    _, data = _load_config(args.config_path)
    plan = _migration_plan(data)
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    return 0 if not plan["problems"] else 2


def migrate_database(args: argparse.Namespace) -> int:
    """Aplica migração explícita após backup verificado obrigatório."""

    _, data = _load_config(args.config_path)
    if not data.get("backup_dir"):
        raise SystemExit("Configuração inválida: backup_dir ausente.")

    plan = _migration_plan(data)
    if plan["problems"]:
        raise SystemExit("Migração recusada: " + " ".join(plan["problems"]))
    if plan["action"] == "none":
        print(json.dumps({"status": "no-op", "plan": plan}, ensure_ascii=False))
        return 0
    if not args.apply:
        print(json.dumps({"status": "planned", "plan": plan}, ensure_ascii=False))
        return 0
    if args.expected_plan_sha256 != plan["plan_sha256"]:
        raise SystemExit("O plano mudou; execute database-plan novamente.")
    if args.expected_fingerprint != plan["logical_fingerprint"]:
        raise SystemExit("O conteúdo do banco mudou; migração recusada.")
    if not args.backup_path:
        raise SystemExit("--backup-path é obrigatório ao aplicar uma migração.")

    backup_root = Path(str(data["backup_dir"])).resolve()
    backup_path = Path(args.backup_path).resolve()
    if not backup_path.is_relative_to(backup_root):
        raise SystemExit(f"O backup deve permanecer dentro de {backup_root}.")

    repository = _repository_from_config(data)
    backup = repository.backup_to(
        backup_path,
        pre_migration=True,
        expected_fingerprint=args.expected_fingerprint,
    )
    backup_sha256 = hashlib.sha256(backup.read_bytes()).hexdigest()
    migrator = DatabaseMigrator(repository.db_path)
    username = str(data.get("admin_username") or "").strip()
    password_hash = str(data.get("password_hash") or "").strip()
    result = migrator.apply_pending(
        app_version=args.app_version,
        origin="migrate-database.ps1",
        expected_fingerprint=args.expected_fingerprint,
        legacy_admin=(username, password_hash) if username and password_hash else None,
    )
    verification = inspect_database(repository.db_path)
    if not verification["ok"]:
        raise SystemExit(
            "Migração aplicada, mas a verificação falhou; mantenha o serviço parado."
        )
    print(
        json.dumps(
            {
                "status": "applied",
                "schema": result.to_dict(),
                "backup_path": str(backup),
                "backup_sha256": backup_sha256,
                "verification": verification,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def fingerprint_database(args: argparse.Namespace) -> int:
    """Emite somente o SHA-256 lógico usado para provar não mutação no update."""

    _, data = _load_config(args.config_path)
    repository = _repository_from_config(data)
    print(repository.logical_fingerprint())
    return 0


def backup(args: argparse.Namespace) -> int:
    _, data = _load_config(args.config_path)
    if not data.get("backup_dir"):
        raise SystemExit("Configuração inválida: backup_dir ausente.")

    backup_dir = Path(str(data["backup_dir"])).resolve()
    repository = _repository_from_config(data)
    explicit_destination = getattr(args, "destination", None)
    if explicit_destination:
        destination_path = Path(explicit_destination).resolve()
        if not destination_path.is_relative_to(backup_dir):
            raise SystemExit(
                f"O destino do backup deve permanecer dentro de {backup_dir}."
            )
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination_path = backup_dir / f"presencas-{timestamp}.db"

    destination = repository.backup_to(destination_path)
    if not explicit_destination:
        backups = sorted(backup_dir.glob("presencas-*.db"), reverse=True)
        for old_backup in backups[max(args.keep, 1) :]:
            old_backup.unlink()
    print(destination)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administração do registrador.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    release_contract_parser = subparsers.add_parser(
        "release-contract",
        help="Exibir a faixa de schemas aceita pelo código sem abrir o banco.",
    )
    release_contract_parser.set_defaults(handler=release_contract)

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

    database_init_parser = subparsers.add_parser(
        "init-database",
        help="Criar o banco somente na primeira instalação.",
    )
    database_init_parser.add_argument("--config-path", required=True)
    database_init_parser.set_defaults(handler=initialize_database)

    database_verify_parser = subparsers.add_parser(
        "verify-database",
        help="Validar banco existente sem modificá-lo.",
    )
    database_verify_parser.add_argument("--config-path", required=True)
    database_verify_parser.set_defaults(handler=verify_database)

    database_status_parser = subparsers.add_parser(
        "database-status",
        help="Inspecionar versão e integridade sem alterar o banco.",
    )
    database_status_parser.add_argument("--config-path", required=True)
    database_status_parser.set_defaults(handler=database_status)

    database_plan_parser = subparsers.add_parser(
        "database-plan",
        help="Planejar migrações sem alterar o banco.",
    )
    database_plan_parser.add_argument("--config-path", required=True)
    database_plan_parser.set_defaults(handler=database_plan)

    database_migrate_parser = subparsers.add_parser(
        "database-migrate",
        help="Aplicar migração separada com backup obrigatório.",
    )
    database_migrate_parser.add_argument("--config-path", required=True)
    database_migrate_parser.add_argument("--apply", action="store_true")
    database_migrate_parser.add_argument("--expected-plan-sha256", default="")
    database_migrate_parser.add_argument("--expected-fingerprint", default="")
    database_migrate_parser.add_argument("--backup-path", default="")
    database_migrate_parser.add_argument("--app-version", default="unknown")
    database_migrate_parser.set_defaults(handler=migrate_database)

    database_fingerprint_parser = subparsers.add_parser(
        "fingerprint-database",
        help="Calcular impressão lógica sem revelar dados.",
    )
    database_fingerprint_parser.add_argument("--config-path", required=True)
    database_fingerprint_parser.set_defaults(handler=fingerprint_database)

    backup_parser = subparsers.add_parser("backup", help="Criar e rotacionar backup.")
    backup_parser.add_argument("--config-path", required=True)
    backup_parser.add_argument("--keep", type=int, default=30)
    backup_parser.add_argument(
        "--destination",
        help="Destino explícito dentro do diretório de backups; não aplica rotação.",
    )
    backup_parser.set_defaults(handler=backup)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
