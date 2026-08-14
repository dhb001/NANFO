import { ButtonHTMLAttributes, CSSProperties } from "react";

type Tone = "primary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: Tone;
}

export function Button({ tone = "primary", children, style, ...props }: ButtonProps) {
  const toneStyles: Record<Tone, CSSProperties> = {
    primary: {
      background: "linear-gradient(135deg, var(--brand), var(--brand-2))",
      color: "#f3fff7",
      border: "1px solid transparent",
    },
    ghost: {
      background: "transparent",
      color: "var(--ink-2)",
      border: "1px solid var(--line-soft)",
    },
    danger: {
      background: "color-mix(in srgb, var(--danger) 16%, white)",
      color: "var(--danger)",
      border: "1px solid color-mix(in srgb, var(--danger) 30%, white)",
    },
  };

  return (
    <button
      {...props}
      style={{
        borderRadius: "10px",
        padding: "0.5rem 0.8rem",
        fontWeight: 600,
        cursor: "pointer",
        transition: "transform 120ms var(--ease-out)",
        ...toneStyles[tone],
        ...style,
      }}
    >
      {children}
    </button>
  );
}
