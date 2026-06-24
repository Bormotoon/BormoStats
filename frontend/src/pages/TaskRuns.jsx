import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { request } from "../utils/api.js";
import { numberFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function TaskRuns() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const limit = searchParams.get("taskRunsLimit") || "200";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    request("/api/v1/admin/task-runs", { admin: true, query: { limit: Number(limit) } })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [limit]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error)]/10 p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message="No task runs found" />;

  const failed = rows.filter((r) => String(r.status || "").toLowerCase() === "failed").length;
  const success = rows.filter((r) => String(r.status || "").toLowerCase() === "success").length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <MetricCard label="Total Runs" value={numberFmt(rows.length)} />
        <MetricCard label="Success" value={numberFmt(success)} accent="success" />
        <MetricCard label="Failed" value={numberFmt(failed)} accent="error" />
      </div>
      <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
        <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-3">Task Runs</h3>
        <DataTable rows={rows} preferredColumns={["task_name", "run_id", "started_at", "finished_at", "status", "rows_ingested", "message", "meta_json"]} />
      </section>
    </div>
  );
}
