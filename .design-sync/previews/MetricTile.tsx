import type { ReactNode } from "react";
import { MetricTile } from "@handball/design-mirror";

function Stage({ children }: { children: ReactNode }) {
  return <div style={{ display: "flex", gap: 12 }}>{children}</div>;
}

export function Default() {
  return (
    <Stage>
      <MetricTile label="Confirmados" value={14} />
    </Stage>
  );
}

export function Active() {
  return (
    <Stage>
      <MetricTile label="Pendentes" value={3} active />
    </Stage>
  );
}

export function ZeroState() {
  return (
    <Stage>
      <MetricTile label="Ausências" value={0} />
    </Stage>
  );
}
