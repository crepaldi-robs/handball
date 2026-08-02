import type { ReactNode } from "react";

export interface ModuleCardProps {
  /** Ícone decorativo (glifo curto). O texto do título já identifica o módulo. */
  icon: ReactNode;
  /** Rótulo de status: "Disponível", "Em preparação", "Interno", "DEV". */
  status: string;
  /** true quando o módulo está de fato disponível (barra superior e ícone em verde). */
  available?: boolean;
  title: string;
  description: string;
  href: string;
  /** Texto do link de ação, ex.: "Abrir módulo". */
  actionLabel: string;
}

/**
 * Cartão de módulo do Hub — espelha `.module-card` de templates/hub.html. O
 * cartão inteiro é clicável (âncora, não botão dentro de um card). A cor de
 * "disponível" vem sempre de `--color-success`, nunca da marca do time —
 * estados semânticos não são customizáveis por time.
 */
export function ModuleCard({ icon, status, available = false, title, description, href, actionLabel }: ModuleCardProps) {
  return (
    <a className={"module-card" + (available ? " module-card-available" : "")} href={href}>
      <span className="module-icon" aria-hidden="true">{icon}</span>
      <span className={"module-status" + (available ? " module-status-available" : "")}>{status}</span>
      <span className="module-card-copy">
        <strong>{title}</strong>
        <span>{description}</span>
      </span>
      <span className="module-card-action" aria-hidden="true">
        {actionLabel} <b>→</b>
      </span>
    </a>
  );
}
