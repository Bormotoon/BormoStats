import { useI18n } from "../utils/i18n.jsx";

export default function StatusChip({ ok, okText, failText }) {
  const { t } = useI18n();
  const showOk = okText || t("common.readyStatus");
  const showFail = failText || t("common.notReady");
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
        ok
          ? "border-[var(--color-success)]/30 bg-[var(--color-success-container)] text-[var(--color-success)]"
          : "border-[var(--color-error)]/30 bg-[var(--color-error-container)] text-[var(--color-error)]"
      }`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-[var(--color-success)]" : "bg-[var(--color-error)]"}`}
      />
      {ok ? showOk : showFail}
    </span>
  );
}

export function Badge({ children, variant = "default" }) {
  const colors = {
    default: "bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)] border border-[var(--color-outline-variant)]",
    success: "bg-[var(--color-success-container)] text-[var(--color-success)] border border-[var(--color-success)]/30",
    warning: "bg-[var(--color-warning-container)] text-[var(--color-warning)] border border-[var(--color-warning)]/30",
    error: "bg-[var(--color-error-container)] text-[var(--color-error)] border border-[var(--color-error)]/30",
    info: "bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)] border border-[var(--color-primary)]/30",
  };
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-semibold ${colors[variant] || colors.default}`}
    >
      {children}
    </span>
  );
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-6 h-6 border-2 border-[var(--color-outline-variant)] border-t-[var(--color-primary)] rounded-full animate-spin" />
    </div>
  );
}

export function EmptyState({ message }) {
  const { t } = useI18n();
  return (
    <div className="rounded-xl border border-dashed border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] text-center py-12 px-4">
      <p className="text-sm">{message || t("common.noData")}</p>
    </div>
  );
}
