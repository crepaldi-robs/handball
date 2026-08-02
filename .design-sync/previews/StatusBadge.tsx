import type { ReactNode } from "react";
import { StatusBadge } from "@handball/design-mirror";

function DarkStage({ children }: { children: ReactNode }) {
  return <div style={{ background: "var(--color-text)", padding: 16 }}>{children}</div>;
}

export function Connecting() {
  return (
    <DarkStage>
      <StatusBadge>Conectando…</StatusBadge>
    </DarkStage>
  );
}

export function Online() {
  return (
    <DarkStage>
      <StatusBadge variant="online">Online</StatusBadge>
    </DarkStage>
  );
}

export function Offline() {
  return (
    <DarkStage>
      <StatusBadge variant="offline">Offline</StatusBadge>
    </DarkStage>
  );
}

export function Pending() {
  return (
    <DarkStage>
      <StatusBadge variant="pending">2 alterações pendentes</StatusBadge>
    </DarkStage>
  );
}
