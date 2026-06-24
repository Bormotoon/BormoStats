import { useRef, useEffect } from "react";

export default function StatusChip({ ok, okText = "OK", failText = "FAIL" }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold ${
        ok
          ? "bg-[var(--color-success)]/15 text-[var(--color-success)]"
          : "bg-[var(--color-error)]/15 text-[var(--color-error)]"
      }`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-[var(--color-success)]" : "bg-[var(--color-error)]"}`}
      />
      {ok ? okText : failText}
    </span>
  );
}

export function Badge({ children, variant = "default" }) {
  const colors = {
    default: "bg-[var(--color-surface-highest)] text-[var(--color-text-secondary)]",
    success: "bg-[var(--color-success)]/15 text-[var(--color-success)]",
    warning: "bg-[var(--color-warning)]/15 text-[var(--color-warning)]",
    error: "bg-[var(--color-error)]/15 text-[var(--color-error)]",
    info: "bg-[var(--color-accent-blue)]/15 text-[var(--color-accent-blue)]",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold ${colors[variant] || colors.default}`}
    >
      {children}
    </span>
  );
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-6 h-6 border-2 border-[var(--color-border)] border-t-[var(--color-brand)] rounded-full animate-spin" />
    </div>
  );
}

export function EmptyState({ message = "No data yet" }) {
  return (
    <div className="rounded-xl border border-dashed border-[var(--color-border)] text-[var(--color-text-muted)] text-center py-12 px-4">
      <p className="text-sm">{message}</p>
    </div>
  );
}
