from __future__ import annotations

from .design_tokens import TeamVisualIdentity, load_registry

__all__ = ["TeamVisualIdentity", "NEUTRAL_THEME", "TEAM_THEMES", "team_theme"]

# Fonte única de verdade: design-system/platform.json + design-system/themes/*.json,
# validados por handball/core/design_tokens.py. Não copie valores hexadecimais
# manualmente aqui nem em CSS — gere static/css/tokens.generated.css com
# scripts/build_design_tokens.py.
NEUTRAL_THEME, TEAM_THEMES = load_registry()


def team_theme(slug: str | None) -> TeamVisualIdentity:
    """Resolve a identidade visual de um slug de time; nunca lança para slug desconhecido.

    Um slug ausente, vazio ou não cadastrado sempre cai no tema neutro
    (Caso E da missão de design system: time sem identidade cadastrada nunca
    quebra a renderização nem herda a identidade de outro time).
    """
    return TEAM_THEMES.get(str(slug or "").strip().casefold(), NEUTRAL_THEME)
