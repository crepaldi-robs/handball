import type { ReactNode } from "react";
import { Button } from "@handball/design-mirror";

/** Aplica o tema do time ativo (mesma convenção de handball/templates/hub.html). */
function Stage({ team = "hm-ime", children }: { team?: string; children: ReactNode }) {
  return (
    <div data-theme={team === "neutral" ? "neutral" : "team"} data-team={team} style={{ padding: 8 }}>
      {children}
    </div>
  );
}

export function Default() {
  return (
    <Stage>
      <Button>Salvar observações</Button>
    </Stage>
  );
}

export function Primary() {
  return (
    <Stage>
      <Button variant="primary">Entrar</Button>
    </Stage>
  );
}

export function Danger() {
  return (
    <Stage>
      <Button variant="danger">Excluir</Button>
    </Stage>
  );
}

export function LargePrimary() {
  return (
    <Stage>
      <Button variant="primary" large>
        Salvar minha resposta
      </Button>
    </Stage>
  );
}

export function Disabled() {
  return (
    <Stage>
      <Button variant="primary" disabled>
        Salvando…
      </Button>
    </Stage>
  );
}

export function PrimaryNeutralTheme() {
  return (
    <Stage team="neutral">
      <Button variant="primary">Entrar</Button>
    </Stage>
  );
}
