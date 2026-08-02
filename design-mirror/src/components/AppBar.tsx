import type { ReactNode } from "react";
import { Brand, type BrandProps } from "./Brand";

export interface AppBarProps {
  brand: BrandProps;
  /** Ações à direita: menu do usuário, indicador de conexão, sair. */
  actions?: ReactNode;
}

/**
 * Cabeçalho fixo da plataforma — espelha `.platform-appbar` de
 * templates/hub.html, hoje o único app bar totalmente tematizado pela
 * sessão. Os demais módulos ainda usam `.topbar` legado por trás do mesmo
 * bloco de marca (ver docs/design-system/ARCHITECTURE.md, "Ainda
 * pendente").
 */
export function AppBar({ brand, actions }: AppBarProps) {
  return (
    <header className="platform-appbar">
      <div className="topbar-inner">
        <Brand {...brand} />
        <div className="top-actions">{actions}</div>
      </div>
    </header>
  );
}
