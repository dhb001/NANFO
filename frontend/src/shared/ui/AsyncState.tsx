import { ReactNode } from "react";

interface AsyncStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function AsyncState({ title, description, action }: AsyncStateProps) {
  return (
    <div
      className="async-state-enter async-state"
      role="status"
      aria-live="polite"
    >
      <div className="async-title">{title}</div>
      {description ? <div className="async-description">{description}</div> : null}
      {action}
    </div>
  );
}
