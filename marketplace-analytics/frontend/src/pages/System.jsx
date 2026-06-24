import { useState, useEffect } from "react";
import { request, safeCall } from "../utils/api.js";
import { numberFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import StatusChip from "../components/StatusChip.jsx";
import { Spinner } from "../components/StatusChip.jsx";

export default function System() {
  const [health, setHealth] = useState(null);
  const [ready, setReady] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [h, r, m] = await Promise.all([
        safeCall(() => request("/health")),
        safeCall(() => request("/ready")),
        safeCall(() => request("/metrics", { expectText: true })),
      ]);
      if (!cancelled) {
        setHealth(h);
        setReady(r);
        setMetrics(m);
        setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <Spinner />;

  const metricsLines = metrics?.ok
    ? metrics.data.split("\n").filter((l) => l && !l.startsWith("#")).slice(0, 120)
    : [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <MetricCard
          label="Health"
          value={<StatusChip ok={health?.ok} okText="OK" failText="FAIL" />}
          subvalue={health?.ok ? "GET /health" : health?.error}
          accent={health?.ok ? "success" : "error"}
        />
        <MetricCard
          label="Readiness"
          value={<StatusChip ok={ready?.ok} okText="Ready" failText="Not Ready" />}
          subvalue={ready?.ok ? "GET /ready" : ready?.error}
          accent={ready?.ok ? "success" : "error"}
        />
        <MetricCard
          label="Metrics"
          value={<StatusChip ok={metrics?.ok} okText="Available" failText="Unavailable" />}
          subvalue={metrics?.ok ? `${numberFmt(metricsLines.length)} metric lines` : metrics?.error}
          accent={metrics?.ok ? "blue" : "error"}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
          <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-2">Raw /health</h3>
          <pre className="font-mono text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap">
            {JSON.stringify(health?.data || { error: health?.error }, null, 2)}
          </pre>
        </section>
        <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
          <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-2">Raw /ready</h3>
          <pre className="font-mono text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap">
            {JSON.stringify(ready?.data || { error: ready?.error }, null, 2)}
          </pre>
        </section>
      </div>

      {metrics?.ok && (
        <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
          <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-2">Prometheus Metrics (sample)</h3>
          <pre className="font-mono text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap overflow-auto max-h-96">
            {metricsLines.join("\n")}
          </pre>
        </section>
      )}
    </div>
  );
}
