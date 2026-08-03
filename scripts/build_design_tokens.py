"""Gera static/css/tokens.generated.css a partir de design-system/*.json.

Fonte única de verdade dos tokens visuais (missão de design system, §8):
handball/core/design_tokens.py valida e carrega design-system/platform.json e
design-system/themes/*.json; este script usa exatamente a mesma leitura e
apenas serializa o resultado em CSS, de forma determinística (chaves
ordenadas, mesma ordem de bloco sempre).

Uso:
    python scripts/build_design_tokens.py            # escreve o arquivo
    python scripts/build_design_tokens.py --check     # falha (exit 1) se o
                                                        # arquivo em disco
                                                        # estiver desatualizado

Não roda como parte do runtime da aplicação — é uma etapa de build local,
chamada manualmente ou por teste de regressão (tests/test_design_tokens.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from handball.core.design_tokens import (  # noqa: E402
    DESIGN_SYSTEM_DIR,
    NEUTRAL_SLUG,
    load_platform_and_themes,
)

OUTPUT_PATH = ROOT_DIR / "static" / "css" / "tokens.generated.css"

_COLOR_CSS_NAMES = {
    "brand_primary": "--color-brand-primary",
    "brand_primary_hover": "--color-brand-primary-hover",
    "brand_on_primary": "--color-brand-on-primary",
    "canvas": "--color-canvas",
    "surface": "--color-surface",
    "surface_raised": "--color-surface-raised",
    "text": "--color-text",
    "text_muted": "--color-text-muted",
    "border": "--color-border",
    "focus": "--color-focus",
    "success": "--color-success",
    "warning": "--color-warning",
    "danger": "--color-danger",
    "info": "--color-info",
}
_COLOR_ORDER = (
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
    "success",
    "warning",
    "danger",
    "info",
)
_SPACE_ORDER = ("1", "2", "3", "4", "6", "8", "12")
_RADIUS_ORDER = ("control", "card", "dialog")
_SHADOW_ORDER = ("low", "medium", "high")
_DURATION_ORDER = ("fast", "normal")


def _declarations(pairs: list[tuple[str, str]], *, indent: str = "  ") -> str:
    return "\n".join(f"{indent}{name}: {value};" for name, value in pairs)


def _platform_declarations(platform: dict) -> list[tuple[str, str]]:
    colors = platform["colors"]
    fonts = platform["fonts"]
    space = platform["space"]
    radius = platform["radius"]
    shadow = platform["shadow"]
    duration = platform["duration"]
    pairs: list[tuple[str, str]] = []
    for key in _COLOR_ORDER:
        pairs.append((_COLOR_CSS_NAMES[key], colors[key]))
    pairs.append(("--font-interface", fonts["interface"]))
    pairs.append(("--font-heading", fonts["heading"]))
    pairs.append(("--font-mono", fonts["mono"]))
    for key in _SPACE_ORDER:
        pairs.append((f"--space-{key}", space[key]))
    for key in _RADIUS_ORDER:
        pairs.append((f"--radius-{key}", radius[key]))
    for key in _SHADOW_ORDER:
        pairs.append((f"--shadow-{key}", shadow[key]))
    for key in _DURATION_ORDER:
        pairs.append((f"--duration-{key}", duration[key]))
    return pairs


def _team_declarations(team: dict) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    colors = team.get("colors", {})
    for key in _COLOR_ORDER:
        if key in colors:
            pairs.append((_COLOR_CSS_NAMES[key], colors[key]))
    heading = team.get("fonts", {}).get("heading")
    if heading:
        pairs.append(("--font-heading", heading))
    return pairs


def render_css() -> str:
    platform, themes = load_platform_and_themes()
    lines = [
        "/* GERADO AUTOMATICAMENTE por scripts/build_design_tokens.py — não editar à mão.",
        "   Fonte: design-system/platform.json + design-system/themes/*.json.",
        "   Ver docs/design-system/ARCHITECTURE.md para o contrato das três camadas. */",
        "",
        f':root,\n[data-theme="{NEUTRAL_SLUG}"] {{',
        _declarations(_platform_declarations(platform)),
        "}",
    ]
    for slug in sorted(themes):
        team = themes[slug]
        team_pairs = _team_declarations(team)
        if not team_pairs:
            continue
        lines.append("")
        lines.append(f'[data-team="{slug}"] {{')
        lines.append(_declarations(team_pairs))
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    css = render_css()
    if check_only:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else None
        if current != css:
            print(
                f"{OUTPUT_PATH} está desatualizado em relação a {DESIGN_SYSTEM_DIR}. "
                "Rode: python scripts/build_design_tokens.py",
                file=sys.stderr,
            )
            return 1
        print("tokens.generated.css está atualizado.")
        return 0
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(css, encoding="utf-8", newline="\n")
    print(f"Escrito {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
