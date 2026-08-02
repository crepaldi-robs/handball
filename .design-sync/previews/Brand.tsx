import type { ReactNode } from "react";
import { Brand } from "@handball/design-mirror";

function Stage({ team = "hm-ime", children }: { team?: string; children: ReactNode }) {
  return (
    <div
      data-theme={team === "neutral" ? "neutral" : "team"}
      data-team={team}
      style={{ background: "var(--color-text)", padding: 16 }}
    >
      {children}
    </div>
  );
}

// Placeholder inline (nunca o logotipo real — o asset aprovado só resolve
// contra a origem do app real em /static/hm-ime-logo.jpg). Prova apenas que
// o caminho .has-image renderiza sem quebrar.
const PLACEHOLDER_LOGO =
  "data:image/svg+xml;utf8," +
  encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="#D71920"/></svg>');

export function HmImeMonogram() {
  return (
    <Stage>
      <Brand displayName="HM-IME" monogram="HM" subtitle="Calendário" />
    </Stage>
  );
}

export function HmImeWithLogoPlaceholder() {
  return (
    <Stage>
      <Brand displayName="HM-IME" monogram="HM" logoUrl={PLACEHOLDER_LOGO} subtitle="Presenças" />
    </Stage>
  );
}

export function NeutralTheme() {
  return (
    <Stage team="neutral">
      <Brand displayName="Handball" monogram="H" subtitle="Administração de usuários" />
    </Stage>
  );
}

export function LongTeamName() {
  return (
    <Stage>
      <Brand displayName="Handebol Masculino IME-USP Sub-17" monogram="HM" subtitle="Meu relatório" />
    </Stage>
  );
}
