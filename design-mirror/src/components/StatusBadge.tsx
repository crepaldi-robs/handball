export type StatusBadgeVariant = "online" | "offline" | "pending" | "neutral";

export interface StatusBadgeProps {
  variant?: StatusBadgeVariant;
  children: string;
}

/**
 * Indicador de estado de conexão/sincronização — espelha `.status-badge` de
 * static/styles.css. Usado no cabeçalho de Presenças para mostrar
 * "Conectando…"/"Online"/"Offline". Pensado para conviver sobre um fundo
 * escuro (dentro de um AppBar).
 */
export function StatusBadge({ variant = "neutral", children }: StatusBadgeProps) {
  const classes = ["status-badge"];
  if (variant !== "neutral") classes.push(variant);
  return <span className={classes.join(" ")}>{children}</span>;
}
