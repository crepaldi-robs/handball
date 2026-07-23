from dataclasses import dataclass


@dataclass(frozen=True)
class OrganizationIdentity:
    code: str
    slug: str
    display_name: str


ORGANIZATION = OrganizationIdentity("HM_IME", "hm-ime", "HM-IME")
CURRENT_SEASON_LABEL = "2026.2"
