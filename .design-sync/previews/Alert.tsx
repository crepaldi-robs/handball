import { Alert } from "@handball/design-mirror";

export function Error() {
  return <Alert variant="error">Usuário ou senha inválidos.</Alert>;
}

export function Success() {
  return (
    <Alert variant="success" role="status">
      Alterações salvas com sucesso.
    </Alert>
  );
}

export function Warning() {
  return (
    <Alert variant="warning">
      Limite de 5 tentativas atingido. A política atual bloqueia novas tentativas por até 15 minutos.
    </Alert>
  );
}
