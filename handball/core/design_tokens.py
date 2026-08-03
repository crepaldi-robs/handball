"""Fonte única de verdade dos tokens visuais: le e valida design-system/*.json.

Usado tanto pelo runtime (handball/core/team_theme.py) quanto pelo gerador de
CSS (scripts/build_design_tokens.py), para que nunca existam dois parsers
divergentes do mesmo contrato. Sem dependencia externa (nao usa jsonschema);
a validacao aqui espelha manualmente design-system/schemas/theme.schema.json.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DESIGN_SYSTEM_DIR = ROOT_DIR / "design-system"
PLATFORM_PATH = DESIGN_SYSTEM_DIR / "platform.json"
THEMES_DIR = DESIGN_SYSTEM_DIR / "themes"

NEUTRAL_SLUG = "neutral"

_HEX_OR_RGBA = re.compile(
    r"^(#[0-9A-Fa-f]{6}|rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*(0|1|0?\.\d+)\s*\))$"
)
_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_STATIC_ASSET = re.compile(r"^/static/[a-zA-Z0-9_\-./]+$")

# Um time pode sobrescrever somente a marca; significado de sucesso/aviso/
# erro/informação é fundamento da plataforma (missão HM-IME §3.2) e nunca é
# redefinido por um arquivo de tema.
TEAM_OVERRIDABLE_COLOR_KEYS = (
    "brand_primary",
    "brand_primary_hover",
    "brand_on_primary",
    "canvas",
    "surface",
    "surface_raised",
    "text",
    "text_muted",
    "border",
    "focus",
)
PLATFORM_ONLY_COLOR_KEYS = ("success", "warning", "danger", "info")
ALL_COLOR_KEYS = TEAM_OVERRIDABLE_COLOR_KEYS + PLATFORM_ONLY_COLOR_KEYS


class DesignTokenError(ValueError):
    """Arquivo de token fora do contrato. Nunca deve ser corrigido em silêncio."""


@dataclass(frozen=True)
class TeamVisualIdentity:
    slug: str
    display_name: str
    monogram: str
    logo_url: str | None
    primary: str
    primary_dark: str
    canvas: str
    surface: str
    ink: str
    muted: str
    border: str
    success: str
    warning: str
    destructive: str
    focus: str
    heading_font: str

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DesignTokenError(f"Arquivo de tokens ausente: {path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DesignTokenError(f"JSON inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DesignTokenError(f"{path} precisa conter um objeto JSON no nível raiz.")
    return data


def _require_color(value: Any, *, where: str) -> str:
    if not isinstance(value, str) or not _HEX_OR_RGBA.match(value):
        raise DesignTokenError(f"Cor inválida em {where}: {value!r}")
    return value


def load_platform() -> dict[str, Any]:
    data = _read_json(PLATFORM_PATH)
    if data.get("kind") != "platform":
        raise DesignTokenError(f"{PLATFORM_PATH} não declara kind='platform'.")
    identity = data.get("identity", {})
    for key in ("slug", "display_name", "monogram"):
        if not isinstance(identity.get(key), str) or not identity[key].strip():
            raise DesignTokenError(f"platform.json.identity sem '{key}'.")
    if identity["slug"] != NEUTRAL_SLUG:
        raise DesignTokenError(
            f"platform.json.identity.slug precisa ser '{NEUTRAL_SLUG}', recebeu {identity['slug']!r}."
        )
    colors = data.get("colors", {})
    missing = [key for key in ALL_COLOR_KEYS if key not in colors]
    if missing:
        raise DesignTokenError(f"platform.json sem cores obrigatórias: {missing}")
    for key in ALL_COLOR_KEYS:
        _require_color(colors[key], where=f"platform.json:colors.{key}")
    fonts = data.get("fonts", {})
    for key in ("interface", "heading", "mono"):
        if not isinstance(fonts.get(key), str) or not fonts[key].strip():
            raise DesignTokenError(f"platform.json sem fonte '{key}'.")
    for section in ("space", "radius", "shadow", "duration"):
        values = data.get(section)
        if not isinstance(values, dict) or not values:
            raise DesignTokenError(f"platform.json sem seção '{section}'.")
    return data


def _load_team_theme_file(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if data.get("kind") != "team":
        raise DesignTokenError(f"{path} não declara kind='team'.")
    slug = data.get("slug")
    if not isinstance(slug, str) or not _SLUG.match(slug):
        raise DesignTokenError(f"Slug inválido em {path}: {slug!r}")
    if slug != path.stem:
        raise DesignTokenError(
            f"slug {slug!r} diverge do nome do arquivo {path.name} (design-system/themes/<slug>.json)."
        )
    if slug == NEUTRAL_SLUG:
        raise DesignTokenError(f"'{NEUTRAL_SLUG}' é reservado ao tema da plataforma; não pode ser um time.")
    if not isinstance(data.get("display_name"), str) or not data["display_name"].strip():
        raise DesignTokenError(f"display_name ausente em {path}.")
    monogram = data.get("monogram")
    if not isinstance(monogram, str) or not (1 <= len(monogram) <= 3):
        raise DesignTokenError(f"monogram inválido em {path}: {monogram!r}")
    logo_url = data.get("logo_url")
    if logo_url is not None and (not isinstance(logo_url, str) or not _STATIC_ASSET.match(logo_url)):
        raise DesignTokenError(f"logo_url precisa estar sob /static/ em {path}: {logo_url!r}")
    colors = data.get("colors", {})
    if not isinstance(colors, dict):
        raise DesignTokenError(f"'colors' inválido em {path}.")
    forbidden = set(colors) & set(PLATFORM_ONLY_COLOR_KEYS)
    if forbidden:
        raise DesignTokenError(
            f"{path} tenta redefinir tokens semânticos reservados à plataforma: {sorted(forbidden)}"
        )
    unknown = set(colors) - set(TEAM_OVERRIDABLE_COLOR_KEYS)
    if unknown:
        raise DesignTokenError(f"{path} usa chaves de cor desconhecidas: {sorted(unknown)}")
    for key, value in colors.items():
        _require_color(value, where=f"{path.name}:colors.{key}")
    fonts = data.get("fonts", {})
    if not isinstance(fonts, dict) or (set(fonts) - {"heading"}):
        raise DesignTokenError(f"{path} só pode sobrescrever a fonte 'heading' em 'fonts'.")
    if "heading" in fonts and (not isinstance(fonts["heading"], str) or not fonts["heading"].strip()):
        raise DesignTokenError(f"fonts.heading inválida em {path}.")
    return data


def load_platform_and_themes() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Carrega e valida platform.json e todos os design-system/themes/*.json."""
    platform = load_platform()
    themes: dict[str, dict[str, Any]] = {}
    if THEMES_DIR.is_dir():
        for path in sorted(THEMES_DIR.glob("*.json")):
            theme = _load_team_theme_file(path)
            if theme["slug"] in themes:
                raise DesignTokenError(f"Slug de time duplicado: {theme['slug']!r}")
            themes[theme["slug"]] = theme
    return platform, themes


def build_identity(platform: dict[str, Any], team: dict[str, Any] | None) -> TeamVisualIdentity:
    """Resolve um TeamVisualIdentity mesclando a plataforma com um tema de time (ou None p/ neutro)."""
    colors = dict(platform["colors"])
    if team is not None:
        colors.update(team.get("colors", {}))
    heading_font = platform["fonts"]["heading"]
    if team is not None:
        heading_font = team.get("fonts", {}).get("heading", heading_font)
    identity_meta = platform["identity"]
    return TeamVisualIdentity(
        slug=team["slug"] if team is not None else identity_meta["slug"],
        display_name=team["display_name"] if team is not None else identity_meta["display_name"],
        monogram=team["monogram"] if team is not None else identity_meta["monogram"],
        logo_url=team.get("logo_url") if team is not None else None,
        primary=colors["brand_primary"],
        primary_dark=colors["brand_primary_hover"],
        canvas=colors["canvas"],
        surface=colors["surface"],
        ink=colors["text"],
        muted=colors["text_muted"],
        border=colors["border"],
        success=colors["success"],
        warning=colors["warning"],
        destructive=colors["danger"],
        focus=colors["focus"],
        heading_font=heading_font,
    )


def load_registry() -> tuple[TeamVisualIdentity, dict[str, TeamVisualIdentity]]:
    """Retorna (tema_neutro, {slug: tema_do_time}) prontos para uso pelo backend."""
    platform, themes = load_platform_and_themes()
    neutral = build_identity(platform, None)
    resolved = {slug: build_identity(platform, team) for slug, team in themes.items()}
    return neutral, resolved
