"""Erros estáveis compartilhados entre a composição e os módulos."""
from __future__ import annotations

from dataclasses import dataclass


class HandballError(RuntimeError):
    """Erro base esperado da plataforma."""


class ConfigurationError(HandballError):
    """A configuração obrigatória está ausente ou é inválida."""


class ModuleOperationError(HandballError):
    """Uma operação de módulo não pôde ser concluída."""


@dataclass(frozen=True)
class CalendarProblem(ModuleOperationError):
    code: str
    title: str
    message: str
    suggestion: str
    status_code: int = 400
    field: str | None = None
    recoverable: bool = True

    def __str__(self) -> str:
        return self.message

    def to_detail(self, *, request_id: str | None = None) -> dict[str, object]:
        return {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "suggestion": self.suggestion,
            "field": self.field,
            "recoverable": self.recoverable,
            "request_id": request_id,
        }
