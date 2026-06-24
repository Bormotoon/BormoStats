import { useState, useEffect } from "react";
import { request } from "../utils/api.js";
import { numberFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function Watermarks() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    request("/api/v1/admin/watermarks", { admin: true })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message="No watermarks found (admin endpoint)" />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <MetricCard label="Rows" value={numberFmt(rows.length)} />
        <MetricCard label="Distinct Sources" value={numberFmt(new Set(rows.map((r) => r.source)).size)} />
        <MetricCard label="Distinct Accounts" value={numberFmt(new Set(rows.map((r) => r.account_id)).size)} />
      </div>
      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">Watermarks</h3>
        <DataTable rows={rows} preferredColumns={["source", "account_id", "watermark_ts", "updated_at"]} />
      </section>
    </div>
  );
}
