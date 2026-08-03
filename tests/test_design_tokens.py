"""Tokens visuais: fonte única de verdade, fallback neutro e login sem marca.

Cobre a fundação do design system multi-time (docs/design-system/AUDIT.md e
ARCHITECTURE.md): design-system/*.json validado sem cópia manual de
hexadecimais, static/css/tokens.generated.css nunca desatualizado em relação
à fonte, resolução de time ativo por sessão com fallback neutro (Casos D/E),
e ausência de marca de time no login (Caso A).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from handball.core.design_tokens import (
    DesignTokenError,
    NEUTRAL_SLUG,
    _load_team_theme_file,
    load_platform_and_themes,
)
from handball.core.team_theme import NEUTRAL_THEME, TEAM_THEMES, team_theme

from tests.test_modular_web import make_client
from tests.test_modular_web import login as login_roberto

ROOT_DIR = Path(__file__).resolve().parent.parent


def login(client: TestClient, username: str, password: str):
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response


def create_dev_only_user(manager, *, username: str, password: str) -> None:
    """Cria um usuário DEV sem nenhum vínculo de time (Caso D)."""
    password_hash = PasswordHasher().hash(password)
    with manager.unit_of_work() as unit_of_work:
        person_id = unit_of_work.identity.create_person(f"Pessoa {username}")
        unit_of_work.identity.create_user(
            person_id=person_id,
            username=username,
            password_hash=password_hash,
            roles=["DEV"],
            linked_player_id=None,
            actor_user_id=1,
        )
        unit_of_work.connection.execute(
            "UPDATE users SET must_change_password=0 WHERE username=?",
            (username,),
        )


# ---------------------------------------------------------------------------
# Fonte canônica: platform.json + themes/*.json
# ---------------------------------------------------------------------------

def test_platform_and_hm_ime_theme_validate_without_copies():
    platform, themes = load_platform_and_themes()
    assert platform["identity"]["slug"] == NEUTRAL_SLUG
    assert set(themes) == {"hm-ime"}
    hm_ime = themes["hm-ime"]
    assert hm_ime["display_name"] == "HM-IME"
    assert hm_ime["colors"]["brand_primary"] == "#82143C"
    # success/warning/danger são fundamentos da plataforma; um time nunca os define.
    assert "success" not in hm_ime["colors"]
    assert "warning" not in hm_ime["colors"]
    assert "danger" not in hm_ime["colors"]


def test_generated_css_is_not_stale():
    """Falha se static/css/tokens.generated.css divergir de design-system/*.json.

    Espelha o que um gate de CI rodaria: qualquer edição manual do CSS gerado,
    ou do JSON fonte sem regenerar, quebra este teste.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT_DIR / "scripts" / "build_design_tokens.py"), "--check"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_generated_css_defines_neutral_root_and_team_override():
    css = (ROOT_DIR / "static" / "css" / "tokens.generated.css").read_text(encoding="utf-8")
    assert ':root,\n[data-theme="neutral"] {' in css
    assert '[data-team="hm-ime"] {' in css
    assert "#82143C" in css
    assert "javascript:" not in css.casefold()


# ---------------------------------------------------------------------------
# Resolução team_theme(): fallback neutro nunca falha, nunca herda outro time
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slug", [None, "", "   ", "time-inexistente", "HM_IME_TYPO"])
def test_team_theme_falls_back_to_neutral_for_unknown_or_absent_slug(slug):
    assert team_theme(slug) is NEUTRAL_THEME
    assert team_theme(slug).slug == "neutral"
    assert team_theme(slug).logo_url is None


def test_team_theme_is_case_insensitive_for_known_slug():
    assert team_theme("HM-IME") is TEAM_THEMES["hm-ime"]
    assert team_theme("hm-ime").primary == "#82143C"


def test_neutral_theme_has_no_hm_ime_asset():
    assert NEUTRAL_THEME.logo_url is None
    assert NEUTRAL_THEME.display_name != "HM-IME"


# ---------------------------------------------------------------------------
# Validação de arquivo de tema — cada violação de contrato falha alto, nunca
# em silêncio (design-system/schemas/theme.schema.json).
# ---------------------------------------------------------------------------

def test_theme_file_rejects_semantic_state_override(tmp_path):
    path = tmp_path / "acme.json"
    path.write_text(
        '{"kind":"team","slug":"acme","display_name":"Acme","monogram":"AC",'
        '"logo_url":null,"colors":{"brand_primary":"#111111","success":"#00FF00"}}',
        encoding="utf-8",
    )
    with pytest.raises(DesignTokenError, match="success"):
        _load_team_theme_file(path)


def test_theme_file_rejects_unknown_color_key(tmp_path):
    path = tmp_path / "acme.json"
    path.write_text(
        '{"kind":"team","slug":"acme","display_name":"Acme","monogram":"AC",'
        '"logo_url":null,"colors":{"brand_primary":"#111111","accent_extra":"#222222"}}',
        encoding="utf-8",
    )
    with pytest.raises(DesignTokenError, match="accent_extra"):
        _load_team_theme_file(path)


def test_theme_file_rejects_invalid_hex(tmp_path):
    path = tmp_path / "acme.json"
    path.write_text(
        '{"kind":"team","slug":"acme","display_name":"Acme","monogram":"AC",'
        '"logo_url":null,"colors":{"brand_primary":"red"}}',
        encoding="utf-8",
    )
    with pytest.raises(DesignTokenError):
        _load_team_theme_file(path)


def test_theme_file_rejects_slug_filename_mismatch(tmp_path):
    path = tmp_path / "acme.json"
    path.write_text(
        '{"kind":"team","slug":"outro-slug","display_name":"Acme","monogram":"AC","logo_url":null,"colors":{}}',
        encoding="utf-8",
    )
    with pytest.raises(DesignTokenError, match="diverge"):
        _load_team_theme_file(path)


def test_theme_file_rejects_neutral_as_team_slug(tmp_path):
    path = tmp_path / "neutral.json"
    path.write_text(
        '{"kind":"team","slug":"neutral","display_name":"X","monogram":"X","logo_url":null,"colors":{}}',
        encoding="utf-8",
    )
    with pytest.raises(DesignTokenError, match="reservado"):
        _load_team_theme_file(path)


def test_theme_file_rejects_external_or_unsafe_logo_url(tmp_path):
    path = tmp_path / "acme.json"
    path.write_text(
        '{"kind":"team","slug":"acme","display_name":"Acme","monogram":"AC",'
        '"logo_url":"https://exemplo-externo.com/logo.png","colors":{}}',
        encoding="utf-8",
    )
    with pytest.raises(DesignTokenError, match="static"):
        _load_team_theme_file(path)


# ---------------------------------------------------------------------------
# Backend: get_teams_by_ids nunca aceita input não confiável, só IDs internos
# ---------------------------------------------------------------------------

def test_get_teams_by_ids_returns_empty_for_no_ids_or_unknown_ids(tmp_path):
    _client, manager = make_client(tmp_path)
    with manager.unit_of_work(read_only=True) as unit_of_work:
        assert unit_of_work.identity.get_teams_by_ids([]) == []
        assert unit_of_work.identity.get_teams_by_ids([999999]) == []
        rows = unit_of_work.identity.get_teams_by_ids([1])
    assert len(rows) == 1
    assert rows[0]["slug"] == "hm-ime"


# ---------------------------------------------------------------------------
# Caso A: login nunca mostra marca de time
# ---------------------------------------------------------------------------

def test_login_page_has_no_team_branding(tmp_path):
    """Caso A: /login não adota a identidade de time nenhum.

    O assistente de cadastro precisa listar os times ativos para o visitante
    escolher o seu — então o *nome* do time aparece como dado escolhível. O
    que continua proibido é a página vestir esse time: sem data-team, sem
    logotipo, sem o CSS de acentos do time, sem organization/team_theme.
    """
    client, _ = make_client(tmp_path)

    response = client.get("/login")

    assert response.status_code == 200
    body = response.text
    assert 'data-theme="neutral"' in body
    assert "data-team=" not in body
    assert "hm-ime-logo" not in body
    assert "hm-ime-expressive.css" not in body
    assert "AAAMAT" not in body
    assert "Handebol Masculino IME-USP" not in body


# ---------------------------------------------------------------------------
# Casos B/D: hub resolve o time pela sessão, não por uma constante global
# ---------------------------------------------------------------------------

def test_hub_shows_resolved_team_theme_for_member(tmp_path):
    """O admin legado (bootstrap DEV+CT) já tem vínculo com o time HM-IME."""
    client, _manager = make_client(tmp_path)
    login_roberto(client)

    response = client.get("/app")

    assert response.status_code == 200
    body = response.text
    assert 'data-theme="team"' in body
    assert 'data-team="hm-ime"' in body
    assert "HM-IME" in body


def test_hub_falls_back_to_neutral_for_dev_without_team(tmp_path):
    """Caso D: DEV sem vínculo de time nunca herda a marca do HM-IME."""
    client, manager = make_client(tmp_path)
    create_dev_only_user(manager, username="only-dev", password="senha-dev-forte")

    login(client, "only-dev", "senha-dev-forte")
    response = client.get("/app")

    assert response.status_code == 200
    body = response.text
    assert 'data-theme="neutral"' in body
    assert 'data-team="neutral"' in body
    assert "HM-IME" not in body
    assert "hm-ime-logo" not in body


# ---------------------------------------------------------------------------
# Acessibilidade: contraste WCAG AA das combinações de cor de cada tema
# (missão de design system §15). Ver docs/design-system/ACCESSIBILITY.md para
# o que é validado aqui vs. o que fica documentado como limitação conhecida
# (ex.: borda-sobre-canvas, que este teste não cobre).
# ---------------------------------------------------------------------------

def _linearize(channel: float) -> float:
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def _contrast_ratio(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


AA_NORMAL_TEXT = 4.5


@pytest.mark.parametrize(
    "theme_slug,pair_name,foreground,background",
    [
        ("neutral", "text/canvas", NEUTRAL_THEME.ink, NEUTRAL_THEME.canvas),
        ("neutral", "text/surface", NEUTRAL_THEME.ink, NEUTRAL_THEME.surface),
        ("neutral", "text_muted/canvas", NEUTRAL_THEME.muted, NEUTRAL_THEME.canvas),
        ("neutral", "on_primary/primary", NEUTRAL_THEME.surface, NEUTRAL_THEME.primary),
        ("neutral", "on_primary/primary_dark", NEUTRAL_THEME.surface, NEUTRAL_THEME.primary_dark),
        ("neutral", "white/success", "#FFFFFF", NEUTRAL_THEME.success),
        ("neutral", "white/warning", "#FFFFFF", NEUTRAL_THEME.warning),
        ("neutral", "white/destructive", "#FFFFFF", NEUTRAL_THEME.destructive),
        ("hm-ime", "text/canvas", TEAM_THEMES["hm-ime"].ink, TEAM_THEMES["hm-ime"].canvas),
        ("hm-ime", "text/surface", TEAM_THEMES["hm-ime"].ink, TEAM_THEMES["hm-ime"].surface),
        ("hm-ime", "text_muted/canvas", TEAM_THEMES["hm-ime"].muted, TEAM_THEMES["hm-ime"].canvas),
        ("hm-ime", "on_primary/primary", TEAM_THEMES["hm-ime"].surface, TEAM_THEMES["hm-ime"].primary),
        ("hm-ime", "on_primary/primary_dark", TEAM_THEMES["hm-ime"].surface, TEAM_THEMES["hm-ime"].primary_dark),
        ("hm-ime", "white/success", "#FFFFFF", TEAM_THEMES["hm-ime"].success),
        ("hm-ime", "white/warning", "#FFFFFF", TEAM_THEMES["hm-ime"].warning),
        ("hm-ime", "white/destructive", "#FFFFFF", TEAM_THEMES["hm-ime"].destructive),
    ],
)
def test_theme_color_pairs_meet_wcag_aa_for_normal_text(theme_slug, pair_name, foreground, background):
    ratio = _contrast_ratio(foreground, background)
    assert ratio >= AA_NORMAL_TEXT, (
        f"{theme_slug}:{pair_name} tem contraste {ratio:.2f}:1, abaixo de {AA_NORMAL_TEXT}:1 (WCAG AA)."
    )


# ---------------------------------------------------------------------------
# Fase 7: Calendário e Playbook resolvem o tema pela sessão, não por
# ORGANIZATION/team_theme(ORGANIZATION.slug) hardcoded (mesmo padrão do hub).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/app/calendario", "/app/playbook"])
def test_module_page_shows_resolved_team_theme_for_member(tmp_path, path):
    client, _manager = make_client(tmp_path)
    login_roberto(client)

    response = client.get(path)

    assert response.status_code == 200
    body = response.text
    assert 'data-theme="team"' in body
    assert 'data-team="hm-ime"' in body
    assert "HM-IME" in body
    assert "theme-hm-ime" not in body


def test_module_page_falls_back_to_neutral_for_dev_without_team(tmp_path):
    """Só /app/playbook é alcançável por um DEV puro (PLAYBOOK_READ vem do
    papel DEV); /app/calendario exige CALENDAR_READ_TEAM, que só vem de CT/
    PLAYER — e ambos exigem team_id na criação da conta, então um usuário com
    permissão de calendário sem nenhum time não é um estado alcançável hoje
    (default-deny correto, não um caso de tematização a cobrir aqui)."""
    client, manager = make_client(tmp_path)
    create_dev_only_user(manager, username="only-dev-module", password="senha-dev-forte")
    login(client, "only-dev-module", "senha-dev-forte")

    response = client.get("/app/playbook")

    assert response.status_code == 200
    body = response.text
    assert 'data-theme="neutral"' in body
    assert 'data-team="neutral"' in body
    assert "HM-IME" not in body


# ---------------------------------------------------------------------------
# Fase 7: as 6 páginas antes "legadas" também resolvem organization/team_theme
# pela sessão (nenhuma mais hardcoded a ORGANIZATION, nenhuma mais ausente).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/app/presencas", "/app/estatisticas", "/app/consultas", "/app/admin/usuarios"],
)
def test_previously_legacy_page_now_resolves_team_theme(tmp_path, path):
    client, _manager = make_client(tmp_path)
    login_roberto(client)

    response = client.get(path)

    assert response.status_code == 200
    body = response.text
    assert 'data-theme="team"' in body
    assert 'data-team="hm-ime"' in body


@pytest.mark.parametrize("path", ["/app/presencas", "/app/admin/usuarios"])
def test_previously_legacy_page_no_longer_uses_hardcoded_mini_mark(tmp_path, path):
    """O bloco de marca compartilhado (templates/partials/_brand.html) usa
    .platform-brand (tematizado); .mini-mark ficava preso ao laranja legado."""
    client, _manager = make_client(tmp_path)
    login_roberto(client)

    response = client.get(path)

    assert response.status_code == 200
    body = response.text
    assert 'class="mini-mark"' not in body
    assert "platform-brand" in body


# ---------------------------------------------------------------------------
# Caso E ponta a ponta: DEV cria um time real sem tema cadastrado (feature de
# outro agente, POST /api/v1/admin/teams) e um usuário vinculado a ele nunca
# herda a marca HM-IME nem quebra a renderização.
# ---------------------------------------------------------------------------

def test_new_team_created_via_admin_api_falls_back_to_neutral_theme(tmp_path):
    client, manager = make_client(tmp_path)
    create_dev_only_user(manager, username="dev-times", password="senha-dev-forte")
    login(client, "dev-times", "senha-dev-forte")
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]

    created = client.post(
        "/api/v1/admin/teams",
        json={
            "code": "NOVO_TIME",
            "slug": "novo-time",
            "display_name": "Novo Time SC",
            "season_label": "2026.2",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    new_team_id = created.json()["id"]

    with manager.unit_of_work() as unit_of_work:
        ct_person = unit_of_work.identity.create_person("Comissão Novo Time")
        unit_of_work.identity.create_user(
            person_id=ct_person,
            username="ct-novo-time",
            password_hash=PasswordHasher().hash("senha-ct-forte"),
            roles=["CT"],
            linked_player_id=None,
            team_id=new_team_id,
            actor_user_id=1,
        )

    login(client, "ct-novo-time", "senha-ct-forte")
    response = client.get("/app")

    assert response.status_code == 200
    body = response.text
    assert 'data-theme="neutral"' in body
    assert 'data-team="neutral"' in body
    assert "HM-IME" not in body
    assert "Novo Time SC" in body
