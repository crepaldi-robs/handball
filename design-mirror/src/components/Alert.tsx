import type { ReactNode } from "react";

export type AlertVariant = "error" | "success" | "warning";

export interface AlertProps {
  variant: AlertVariant;
  children: ReactNode;
  /** Papel ARIA do bloco; "alert" (padrão) para erro/aviso, "status" para sucesso não urgente. */
  role?: string;
}

/**
 * Alerta inline compartilhado — espelha `.alert`/`.alert-error`/
 * `.alert-success`/`.alert-warning` de static/styles.css. Estados
 * semânticos (`--color-success`/`--color-warning`/`--color-danger`) são
 * fundamentos da plataforma; nenhum time pode redefini-los (ver
 * design-system/schemas/theme.schema.json).
 */
export function Alert({ variant, children, role = "alert" }: AlertProps) {
  return (
    <div className={`alert alert-${variant}`} role={role}>
      {children}
    </div>
  );
}
