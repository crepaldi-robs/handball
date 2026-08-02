export interface MetricTileProps {
  label: string;
  value: string | number;
  /** Ativa o estado selecionado (borda/realce), usado para expandir uma lista de detalhes. */
  active?: boolean;
  onClick?: () => void;
}

/**
 * Cartão de métrica — espelha `.metric` de templates/presencas/index.html,
 * usado no resumo da chamada. Cada métrica pode expandir a lista de atletas
 * naquele status ao ser clicada.
 */
export function MetricTile({ label, value, active = false, onClick }: MetricTileProps) {
  return (
    <button type="button" className={"metric" + (active ? " is-active" : "")} onClick={onClick}>
      <span>{label}</span>
      <strong>{value}</strong>
    </button>
  );
}
