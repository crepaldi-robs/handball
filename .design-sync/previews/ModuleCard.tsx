import type { ReactNode } from "react";
import { ModuleCard } from "@handball/design-mirror";

function Stage({ children }: { children: ReactNode }) {
  return (
    <div data-theme="team" data-team="hm-ime" style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
      {children}
    </div>
  );
}

export function Available() {
  return (
    <Stage>
      <ModuleCard
        icon="✓"
        status="Disponível"
        available
        title="Presenças"
        description="Confirmações, chamada, histórico, elenco e auditoria."
        href="/app/presencas"
        actionLabel="Abrir módulo"
      />
    </Stage>
  );
}

export function InPreparation() {
  return (
    <Stage>
      <ModuleCard
        icon="↗"
        status="Em preparação"
        title="Estatísticas"
        description="Indicadores esportivos e leitura de desempenho da equipe."
        href="/app/estatisticas"
        actionLabel="Ver módulo"
      />
    </Stage>
  );
}

export function Internal() {
  return (
    <Stage>
      <ModuleCard
        icon="⌕"
        status="Interno"
        available
        title="Consultas SQL"
        description="Catálogo, consultas de leitura, plano e exportação."
        href="/app/consultas"
        actionLabel="Abrir módulo"
      />
    </Stage>
  );
}
