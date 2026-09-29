import { useEffect, useRef, useState } from "react";
import { DownloadSimple } from "@phosphor-icons/react";
import { downloadFile, request } from "../utils/api.js";

const POLL_MS = 2000;
const MAX_POLLS = 150;

/** Queue a server-side CSV export, wait for it and download the file. */
export default function ExportButton({ dataset, filters, includeDates = true, lang = "ru" }) {
  const [state, setState] = useState({ phase: "idle", message: "" });
  const cancelled = useRef(false);
  useEffect(() => () => { cancelled.current = true; }, []);
  const ru = lang !== "en";

  const start = async () => {
    setState({ phase: "running", message: ru ? "Экспорт поставлен в очередь…" : "Export queued…" });
    try {
      const body = {
        dataset,
        marketplace: filters.marketplace || null,
        account_id: filters.accountId || null,
        ...(includeDates ? { date_from: filters.dateFrom || null, date_to: filters.dateTo || null } : {}),
      };
      const job = await request("/api/v1/exports", { method: "POST", body, admin: true });
      for (let i = 0; i < MAX_POLLS && !cancelled.current; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        const current = await request(`/api/v1/exports/${job.export_id}`);
        if (current.status === "done") {
          await downloadFile(`/api/v1/exports/${job.export_id}/download`, `${dataset}.csv`);
          setState({
            phase: "done",
            message: ru ? `Готово: ${current.row_count} строк` : `Done: ${current.row_count} rows`,
          });
          return;
        }
        if (current.status === "failed") throw new Error(current.error || "export failed");
      }
      if (!cancelled.current) {
        setState({ phase: "error", message: ru ? "Экспорт ещё выполняется — проверьте позже" : "Export still running — check back later" });
      }
    } catch (error) {
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  };

  return (
    <div className="flex items-center gap-2">
      {state.message && (
        <span role="status" className={`text-xs ${state.phase === "error" ? "text-[var(--color-error)]" : "text-[var(--color-on-surface-variant)]"}`}>
          {state.message}
        </span>
      )}
      <button
        type="button"
        onClick={start}
        disabled={state.phase === "running"}
        className="flex items-center gap-1 px-3 py-1.5 rounded-full border border-[var(--color-outline-variant)] text-sm font-medium hover:bg-[var(--color-surface-container)] disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
      >
        <DownloadSimple size={16} aria-hidden="true" /> CSV
      </button>
    </div>
  );
}
