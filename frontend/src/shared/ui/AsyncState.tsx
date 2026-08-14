import { ReactNode } from "react";
import { motion } from "framer-motion";

interface AsyncStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function AsyncState({ title, description, action }: AsyncStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
      style={{
        border: "1px solid var(--line-soft)",
        borderRadius: "var(--radius-m)",
        background: "var(--surface-card)",
        padding: "1rem",
        boxShadow: "var(--shadow-low)",
      }}
      role="status"
      aria-live="polite"
    >
      <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>{title}</div>
      {description ? <div style={{ color: "var(--ink-3)", marginBottom: action ? "0.75rem" : 0 }}>{description}</div> : null}
      {action}
    </motion.div>
  );
}
