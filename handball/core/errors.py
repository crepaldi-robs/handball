"""Erros estáveis compartilhados entre a composição e os módulos."""


class HandballError(RuntimeError):
    """Erro base esperado da plataforma."""


class ConfigurationError(HandballError):
    """A configuração obrigatória está ausente ou é inválida."""


class ModuleOperationError(HandballError):
    """Uma operação de módulo não pôde ser concluída."""
