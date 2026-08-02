import type { CSSProperties } from "react";

export interface BrandProps {
  /** Nome do time, ou "Handball" no tema neutro (organization.display_name). */
  displayName: string;
  /** Sigla curta mostrada quando não há logotipo (team_theme.monogram). */
  monogram: string;
  /** URL do logotipo aprovado (team_theme.logo_url), ou undefined para mostrar o monograma. */
  logoUrl?: string;
  /** Texto abaixo do nome do time — normalmente o nome do módulo atual. */
  subtitle: string;
  /** Link do bloco de marca. Sempre "/app" nos templates reais. */
  href?: string;
}

/**
 * Marca compartilhada do cabeçalho — espelha templates/partials/_brand.html,
 * o único componente Jinja2 reutilizado por 7 páginas autenticadas (ver
 * docs/design-system/ARCHITECTURE.md). Usa `.platform-brand`, que responde a
 * `[data-team]` via os tokens `--color-brand-primary`/`--color-text`: o
 * mesmo componente muda de cor sozinho quando o time ativo muda, sem prop
 * de cor explícita.
 */
export function Brand({ displayName, monogram, logoUrl, subtitle, href = "/app" }: BrandProps) {
  const style: CSSProperties | undefined = logoUrl
    ? ({ "--brand-logo-url": `url(${logoUrl})` } as CSSProperties)
    : undefined;
  return (
    <a className="identity" href={href} aria-label="Voltar ao Hub Handebol">
      <div
        className={"platform-brand" + (logoUrl ? " has-image" : "")}
        style={style}
        aria-hidden="true"
      >
        {monogram}
      </div>
      <div>
        <strong>{displayName}</strong>
        <span>{subtitle}</span>
      </div>
    </a>
  );
}
