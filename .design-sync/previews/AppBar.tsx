import { AppBar, Button, StatusBadge } from "@handball/design-mirror";

export function HmIme() {
  return (
    <div data-theme="team" data-team="hm-ime">
      <AppBar
        brand={{ displayName: "HM-IME", monogram: "HM", subtitle: "Calendário" }}
        actions={
          <>
            <StatusBadge variant="online">Online</StatusBadge>
            <Button className="text-button">Sair</Button>
          </>
        }
      />
    </div>
  );
}

export function NeutralTheme() {
  return (
    <div data-theme="neutral" data-team="neutral">
      <AppBar
        brand={{ displayName: "Handball", monogram: "H", subtitle: "Administração de usuários" }}
        actions={<Button className="text-button">Sair</Button>}
      />
    </div>
  );
}
