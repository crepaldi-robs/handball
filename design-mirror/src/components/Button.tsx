import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "secondary" | "primary" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Variante visual. "secondary" (padrão) é o botão neutro para ações de baixa ênfase. */
  variant?: ButtonVariant;
  /** Altura maior e largura total — usado na ação principal de um formulário (ex.: login). */
  large?: boolean;
  children: ReactNode;
}

/**
 * Botão compartilhado da plataforma — espelha `.button`/`.button-primary`/
 * `.button-danger`/`.button-large` de static/styles.css, as mesmas classes
 * usadas pelos templates Jinja2 reais. A cor da variante "primary" vem do
 * token `--color-brand-primary`, que muda conforme o time ativo.
 */
export function Button({ variant = "secondary", large = false, className, children, ...rest }: ButtonProps) {
  const classes = ["button"];
  if (variant === "primary") classes.push("button-primary");
  if (variant === "danger") classes.push("button-danger");
  if (large) classes.push("button-large");
  if (className) classes.push(className);
  return (
    <button className={classes.join(" ")} {...rest}>
      {children}
    </button>
  );
}
