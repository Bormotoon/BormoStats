import { motion } from "motion/react";

const accentColors = {
  success: "var(--color-success)",
  warning: "var(--color-warning)",
  error: "var(--color-error)",
  blue: "var(--color-primary)",
};

export default function MetricCard({ label, value, subvalue, accent, className = "" }) {
  const accentColor = accentColors[accent];

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`md3-card-elevated p-4 flex flex-col ${className}`}
    >
      <span className="text-[11px] font-semibold text-[var(--color-on-surface-variant)] tracking-wide uppercase">
        {label}
      </span>
      <span
        className="mt-2 text-2xl font-bold tracking-tight leading-none"
        style={{ color: accentColor || "var(--color-on-surface)" }}
      >
        {value}
      </span>
      {subvalue && (
        <span className="mt-2 text-xs text-[var(--color-on-surface-variant)]">{subvalue}</span>
      )}
    </motion.article>
  );
}
