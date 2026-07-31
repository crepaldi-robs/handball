from __future__ import annotations

from dataclasses import asdict, dataclass


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

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


NEUTRAL_THEME = TeamVisualIdentity(
    slug="neutral",
    display_name="Handball",
    monogram="H",
    logo_url=None,
    primary="#334155",
    primary_dark="#1E293B",
    canvas="#F4F6F8",
    surface="#FFFFFF",
    ink="#171717",
    muted="#667085",
    border="#DDE2E7",
    success="#0F7B5A",
    warning="#B45F06",
    destructive="#7F1D1D",
)

TEAM_THEMES: dict[str, TeamVisualIdentity] = {
    "hm-ime": TeamVisualIdentity(
        slug="hm-ime",
        display_name="HM-IME",
        monogram="HM",
        logo_url="/static/hm-ime-logo.jpg",
        primary="#D71920",
        primary_dark="#A40E17",
        canvas="#F7F4F2",
        surface="#FFFFFF",
        ink="#171717",
        muted="#6B6464",
        border="#E6DEDB",
        success="#0F7B5A",
        warning="#B45F06",
        destructive="#7F1D1D",
    ),
}


def team_theme(slug: str | None) -> TeamVisualIdentity:
    return TEAM_THEMES.get(str(slug or "").strip().casefold(), NEUTRAL_THEME)
