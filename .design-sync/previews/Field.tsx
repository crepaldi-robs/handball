import { Field } from "@handball/design-mirror";

export function TextInput() {
  return (
    <Field label="Usuário">
      <input name="username" autoComplete="username" defaultValue="" placeholder="" />
    </Field>
  );
}

export function Select() {
  return (
    <Field label="Meu nome no elenco">
      <select defaultValue="">
        <option value="">Selecione seu nome</option>
        <option value="1">Ana Souza · GOL</option>
        <option value="2">Bruna Lima · PD/PE</option>
      </select>
    </Field>
  );
}

export function Textarea() {
  return (
    <Field label="Justificativa ou observação para a CT (opcional)">
      <textarea rows={4} placeholder="Ex.: vou chegar atrasado, consulta médica…" />
    </Field>
  );
}
