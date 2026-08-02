"""Autorizacao centralizada, sem conhecer detalhes de SQLite."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from fastapi import HTTPException, Request, status


class Permission(StrEnum):
    USERS_MANAGE = "users.manage"
    SESSIONS_REVOKE = "auth.sessions.revoke"
    ATTENDANCE_READ_SELF = "attendance.read.self"
    ATTENDANCE_WRITE_SELF = "attendance.write.self"
    ATTENDANCE_READ_TEAM = "attendance.read.team"
    ATTENDANCE_WRITE = "attendance.write"
    ATTENDANCE_FINALIZE = "attendance.finalize"
    ATTENDANCE_REOPEN = "attendance.reopen"
    MEMBERS_READ_TEAM = "members.read.team"
    MEMBERS_MANAGE = "members.manage"
    PLAYER_ACCOUNTS_MANAGE = "player_accounts.manage"
    AUDIT_READ_SPORT = "audit.read.sport"
    EXPORT_READ_TEAM = "export.read.team"
    BACKUP_DOWNLOAD = "backup.download"
    REPORTS_READ_SELF = "reports.read.self"
    DIAGNOSTICS_READ = "diagnostics.read"
    CALENDAR_READ_TEAM = "calendar.read.team"
    CALENDAR_MANAGE = "calendar.manage"
    CALENDAR_VISIBILITY_MANAGE = "calendar.visibility.manage"
    CALENDAR_JUSTIFICATION_SELF = "calendar.justification.self"
    PLAYBOOK_READ = "playbook.read"
    PLAYBOOK_MANAGE = "playbook.manage"
    SQL_EXPLORE = "sql.explore"
    SQL_ADMIN = "sql.admin"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "DEV": frozenset({Permission.USERS_MANAGE, Permission.SESSIONS_REVOKE, Permission.DIAGNOSTICS_READ,
                      Permission.PLAYBOOK_READ, Permission.PLAYBOOK_MANAGE,
                      Permission.CALENDAR_VISIBILITY_MANAGE,
                      Permission.SQL_ADMIN}),
    "CT": frozenset({Permission.ATTENDANCE_READ_TEAM, Permission.ATTENDANCE_WRITE,
                     Permission.ATTENDANCE_FINALIZE, Permission.ATTENDANCE_REOPEN,
                     Permission.MEMBERS_READ_TEAM, Permission.MEMBERS_MANAGE,
                     Permission.PLAYER_ACCOUNTS_MANAGE,
                     Permission.AUDIT_READ_SPORT, Permission.EXPORT_READ_TEAM,
                     Permission.BACKUP_DOWNLOAD, Permission.CALENDAR_READ_TEAM,
                     Permission.CALENDAR_MANAGE, Permission.CALENDAR_VISIBILITY_MANAGE,
                     Permission.PLAYBOOK_READ,
                     Permission.PLAYBOOK_MANAGE, Permission.SQL_EXPLORE}),
    "PLAYER": frozenset({Permission.ATTENDANCE_READ_SELF, Permission.ATTENDANCE_WRITE_SELF, Permission.REPORTS_READ_SELF,
                         Permission.CALENDAR_READ_TEAM,
                         Permission.CALENDAR_JUSTIFICATION_SELF,
                         Permission.PLAYBOOK_READ}),
}


@dataclass(frozen=True)
class AccessContext:
    user_id: int
    person_id: int | None
    session_id: str
    username: str
    display_name: str
    team_ids: frozenset[int]
    system_roles: frozenset[str]
    team_roles: frozenset[str]
    permissions: frozenset[Permission]
    linked_player_id: int | None
    csrf_token: str
    must_change_password: bool = False


def require_authenticated_user(request: Request) -> AccessContext:
    context = getattr(request.state, "access_context", None)
    if context is None:
        from .auth import session_from_request

        session_from_request(request)
        context = getattr(request.state, "access_context", None)
    if context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return context


def require_permission(permission: Permission) -> Callable[[Request], AccessContext]:
    def dependency(request: Request) -> AccessContext:
        context = require_authenticated_user(request)
        if permission not in context.permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return context
    return dependency


def require_read_only_permission(
    *permissions: Permission,
) -> Callable[[Request], AccessContext]:
    """Autentica uma consulta sem atualizar last_seen_at da sessão.

    Aceita uma ou mais permissões; basta ter uma delas para passar.
    """

    def dependency(request: Request) -> AccessContext:
        context = getattr(request.state, "access_context", None)
        if context is None:
            from .auth import session_from_request

            session_from_request(request, touch=False)
            context = getattr(request.state, "access_context", None)
        if context is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not any(permission in context.permissions for permission in permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return context

    return dependency


def require_team_access(team_id: int, context: AccessContext) -> None:
    if team_id not in context.team_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def require_self_or_permission(player_id: int, permission: Permission, context: AccessContext) -> None:
    if context.linked_player_id == player_id or permission in context.permissions:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
