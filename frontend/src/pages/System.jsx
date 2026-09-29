import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { getApiBase, request, safeCall } from "../utils/api.js";
import MetricCard from "../components/MetricCard.jsx";
import StatusChip from "../components/StatusChip.jsx";
import { Spinner } from "../components/StatusChip.jsx";

// /health/dependencies answers 503 with a JSON body when degraded, so read it directly.
async function loadDependencies() {
  const response = await fetch(`${getApiBase()}/health/dependencies`, { credentials: "omit" });
  return response.json();
}

export default function System() {
  const { t } = useI18n();
  const [health, setHealth] = useState(null);
  const [ready, setReady] = useState(null);
  const [deps, setDeps] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [h, r, d] = await Promise.all([
        safeCall(() => request("/health/live")),
        safeCall(() => request("/health/ready")),
        safeCall(loadDependencies),
      ]);
      if (!cancelled) {
        setHealth(h);
        setReady(r);
        setDeps(d);
        setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <Spinner />;

  const dependencyRows = deps?.ok ? Object.entries(deps.data?.dependencies || {}) : [];
  const depsHealthy = deps?.ok && deps.data?.status === "ok";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <MetricCard
          label={t("system.health")}
          value={<StatusChip ok={health?.ok} okText={t("common.healthy")} failText={t("common.unhealthy")} />}
          subvalue={health?.ok ? "GET /health/live" : health?.error}
          accent={health?.ok ? "success" : "error"}
        />
        <MetricCard
          label={t("system.readiness")}
          value={<StatusChip ok={ready?.ok} okText={t("common.readyStatus")} failText={t("common.notReady")} />}
          subvalue={ready?.ok ? "GET /health/ready" : ready?.error}
          accent={ready?.ok ? "success" : "error"}
        />
        <MetricCard
          label="Dependencies"
          value={<StatusChip ok={depsHealthy} okText={t("common.available")} failText={t("common.unavailable")} />}
          subvalue="GET /health/dependencies"
          accent={depsHealthy ? "info" : "error"}
        />
      </div>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-2">Dependencies</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--color-on-surface-variant)]">
              <th className="py-1">Service</th>
              <th className="py-1">Status</th>
              <th className="py-1 text-right">Latency, ms</th>
            </tr>
          </thead>
          <tbody>
            {dependencyRows.map(([name, info]) => (
              <tr key={name} className="border-t border-[var(--color-outline-variant)]">
                <td className="py-1 font-mono">{name}</td>
                <td className="py-1">
                  <StatusChip ok={info.status === "ok"} okText={t("common.available")} failText={t("common.unavailable")} />
                </td>
                <td className="py-1 text-right tabular-nums">{info.latency_ms}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-[var(--color-on-surface-variant)] mt-3">
          Prometheus metrics are scraped from the backend on the private network (/metrics is not exposed through the proxy).
        </p>
      </section>
    </div>
  );
}
