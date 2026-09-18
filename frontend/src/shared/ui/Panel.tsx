import { PropsWithChildren, ReactNode, useId } from "react";

interface PanelProps extends PropsWithChildren {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
}

export function Panel({ title, subtitle, action, children }: PanelProps) {
  const titleId = useId();
  return (
    <section
      className="panel"
      aria-labelledby={title ? titleId : undefined}
    >
      {title ? (
        <header className="panel-heading">
          <div>
            <h3 id={titleId}>{title}</h3>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {action}
        </header>
      ) : null}
      <div className="panel-body">{children}</div>
    </section>
  );
}
