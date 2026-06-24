import { motion } from "motion/react";

export default function MetricCard({ label, value, subvalue, accent }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-[var(--color-border)] card-gradient p-4 flex flex-col"
    >
      <span className="text-xs font-bold text-[var(--color-text-muted)] tracking-wide uppercase">
        {label}
      </span>
      <span
        className={`mt-2 text-2xl font-extrabold leading-none ${
          accent === "success"
            ? "text-[var(--color-success)]"
            : accent === "warning"
              ? "text-[var(--color-warning)]"
              : accent === "error"
                ? "text-[var(--color-error)]"
                : accent === "blue"
                  ? "text-[var(--color-accent-blue)]"
                  : "text-[var(--color-text-primary)]"
        }`}
      >
        {value}
      </span>
      {subvalue && (
        <span className="mt-2 text-xs text-[var(--color-text-muted)]">{subvalue}</span>
      )}
    </motion.article>
  );
}
