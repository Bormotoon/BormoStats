import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, safeCall } from "../utils/api.js";
import { numberFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import StatusChip from "../components/StatusChip.jsx";
import { Spinner } from "../components/StatusChip.jsx";

export default function System() {
  const { t } = useI18n();
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
          label={t("system.health")}
          value={<StatusChip ok={health?.ok} okText={t("common.healthy")} failText={t("common.unhealthy")} />}
          subvalue={health?.ok ? "GET /health" : health?.error}
          accent={health?.ok ? "success" : "error"}
        />
        <MetricCard
          label={t("system.readiness")}
          value={<StatusChip ok={ready?.ok} okText={t("common.readyStatus")} failText={t("common.notReady")} />}
          subvalue={ready?.ok ? "GET /ready" : ready?.error}
          accent={ready?.ok ? "success" : "error"}
        />
        <MetricCard
          label={t("system.metrics")}
          value={<StatusChip ok={metrics?.ok} okText={t("common.available")} failText={t("common.unavailable")} />}
          subvalue={metrics?.ok ? `${numberFmt(metricsLines.length)} ${t("system.metricLines")}` : metrics?.error}
          accent={metrics?.ok ? "info" : "error"}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-2">{t("system.rawHealth")}</h3>
          <pre className="font-mono text-xs text-[var(--color-on-surface-variant)] whitespace-pre-wrap">
            {JSON.stringify(health?.data || { error: health?.error }, null, 2)}
          </pre>
        </section>
        <section className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-2">{t("system.rawReady")}</h3>
          <pre className="font-mono text-xs text-[var(--color-on-surface-variant)] whitespace-pre-wrap">
            {JSON.stringify(ready?.data || { error: ready?.error }, null, 2)}
          </pre>
        </section>
      </div>

      {metrics?.ok && (
        <section className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-2">{t("system.promMetrics")}</h3>
          <pre className="font-mono text-xs text-[var(--color-on-surface-variant)] whitespace-pre-wrap overflow-auto max-h-96">
            {metricsLines.join("\n")}
          </pre>
        </section>
      )}
    </div>
  );
}
