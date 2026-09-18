import { ButtonHTMLAttributes } from "react";
import { useAuthStore } from "@/shared/state/auth-store";
import { hasPermission } from "@/features/auth/permissions";

type Tone = "primary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: Tone;
  permission?: string;
}

export function Button({ tone = "primary", permission, children, className = "", ...props }: ButtonProps) {
  const profile = useAuthStore((state) => state.profile);
  const denied = permission !== undefined && !hasPermission(profile, permission);

  return (
    <button
      {...props}
      className={`button button--${tone} ${className}`}
      disabled={props.disabled || denied}
      title={denied ? `Requires ${permission} permission` : props.title}
    >
      {children}
    </button>
  );
}
