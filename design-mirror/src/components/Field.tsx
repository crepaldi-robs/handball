import type { ReactNode } from "react";

export interface FieldProps {
  label: string;
  /** O controle real: <input>, <select> ou <textarea>. */
  children: ReactNode;
}

/**
 * Campo rotulado compartilhado por todos os formulários da plataforma —
 * espelha o padrão `label span` + `input/select/textarea` de
 * static/styles.css. O rótulo fica sempre visível acima do controle, nunca
 * só como placeholder (ver docs/HM-IME-IDENTIDADE-VISUAL.md §8.5).
 */
export function Field({ label, children }: FieldProps) {
  return (
    <label>
      <span>{label}</span>
      {children}
    </label>
  );
}
