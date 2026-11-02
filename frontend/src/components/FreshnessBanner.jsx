import { useEffect, useState } from "react";
import { ClockCounterClockwise, Warning } from "@phosphor-icons/react";
import { request, subscribeSettings, getSettings } from "../utils/api.js";

const STALE_AFTER_MS = 2 * 60 * 60 * 1000;

function latest(marts) {
  const stamps = marts.map((m) => (m.updated_at ? new Date(m.updated_at).getTime() : 0)).filter(Boolean);
  return stamps.length ? Math.max(...stamps) : null;
}

export default function FreshnessBanner({ lang }) {
  const [data, setData] = useState(null);
  const [apiKey, setApiKey] = useState(getSettings().apiKey);

  useEffect(() => subscribeSettings((s) => setApiKey(s.apiKey)), []);

  useEffect(() => {
    let cancelled = false;
    if (!apiKey) {
      setData(null);
      return undefined;
    }
    request("/api/v1/freshness")
      .then((payload) => { if (!cancelled) setData(payload); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [apiKey]);

  if (!data) return null;
  const updatedAt = latest(data.marts || []);
  const stale = !updatedAt || Date.now() - updatedAt > STALE_AFTER_MS;
  const errors = (data.source_errors_24h || []).reduce((sum, row) => sum + Number(row.failures || 0), 0);
  const ru = lang !== "en";
  const when = updatedAt ? new Date(updatedAt).toLocaleString(ru ? "ru-RU" : "en-GB") : ru ? "нет данных" : "no data";

  return (
    <div
      role="status"
      className={`flex flex-wrap items-center gap-x-4 gap-y-1 px-4 lg:px-6 py-1.5 text-xs border-b border-[var(--color-outline-variant)] ${
        stale || errors ? "bg-[var(--color-warning-container)] text-[var(--color-on-surface)]" : "text-[var(--color-on-surface-variant)]"
      }`}
    >
      <span className="flex items-center gap-1">
        <ClockCounterClockwise size={14} aria-hidden="true" />
        {ru ? "Данные обновлены: " : "Data updated: "}
        <span className="tabular-nums">{when}</span>
        {stale && (ru ? " — данные устарели" : " — data is stale")}
      </span>
      {errors > 0 && (
        <span className="flex items-center gap-1">
          <Warning size={14} aria-hidden="true" />
          {ru ? `Ошибки источников за 24 ч: ${errors}` : `Source errors in 24h: ${errors}`}
        </span>
      )}
    </div>
  );
}
