import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request } from "../utils/api.js";
import { numberFmt } from "../utils/formats.js";
import DataTable from "../components/DataTable.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

const PAGE_SIZE = 500;

/** "2026-09-30T15:00" typed as Moscow time -> UTC ISO string for the API. */
function moscowToUtc(local) {
  if (!local) return "";
  return new Date(`${local}:00+03:00`).toISOString();
}

function moscowNow() {
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }).format(new Date());
  return parts.replace(" ", "T");
}

/** One table row per entity: the document's top-level fields, nested values as JSON. */
function flatten(item) {
  const row = { entity_key: item.entity_key, marketplace: item.marketplace, recorded_at: item.committed_at };
  const doc = item.document;
  if (doc && typeof doc === "object" && !Array.isArray(doc)) {
    for (const [key, value] of Object.entries(doc)) {
      if (key === "payload") continue;
      row[key] = value !== null && typeof value === "object" ? JSON.stringify(value) : value;
    }
  } else {
    row.document = JSON.stringify(doc);
  }
  return row;
}

export default function History() {
  const { t } = useI18n();
  const [repos, setRepos] = useState(null);
  const [repo, setRepo] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [at, setAt] = useState(moscowNow);
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    request("/api/v1/history/repos")
      .then((res) => {
        const items = res.items || [];
        setRepos(items);
        if (items.length) setRepo(items[0].repo);
      })
      .catch((err) => setError(err.message));
  }, []);

  const load = (nextOffset = 0) => {
    setLoading(true);
    setError("");
    request("/api/v1/history/state", {
      query: { repo, marketplace, at: moscowToUtc(at), limit: PAGE_SIZE, offset: nextOffset },
    })
      .then((res) => { setResult(res); setOffset(nextOffset); setLoading(false); })
      .catch((err) => { setError(err.message); setLoading(false); });
  };

  if (repos === null && !error) return <Spinner />;
  const repoNames = [...new Set((repos || []).map((r) => r.repo))];
  const rows = (result?.items || []).map(flatten);
  const inputClass = "px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm";

  return (
    <div className="space-y-4">
      <section className="md3-card-elevated p-4 space-y-3">
        <p className="text-sm text-[var(--color-on-surface-variant)]">{t("history.intro")}</p>
        <div className="flex flex-wrap gap-3 items-end">
          <label className="flex flex-col gap-1 text-xs">
            {t("history.dataset")}
            <select className={inputClass} value={repo} onChange={(e) => setRepo(e.target.value)}>
              {repoNames.map((name) => (
                <option key={name} value={name}>{t(`history.repos.${name}`) === `history.repos.${name}` ? name : t(`history.repos.${name}`)}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            {t("history.marketplace")}
            <select className={inputClass} value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
              <option value="">{t("common.all")}</option>
              <option value="ozon">Ozon</option>
              <option value="wb">WB</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            {t("history.at")}
            <input type="datetime-local" className={inputClass} value={at} onChange={(e) => setAt(e.target.value)} />
          </label>
          <button type="button" className="px-4 py-2 rounded-lg bg-[var(--color-primary)] text-[var(--color-on-primary)] text-sm font-semibold" disabled={!repo || loading} onClick={() => load(0)}>
            {t("history.show")}
          </button>
        </div>
        {repos && repos.length > 0 && (
          <p className="text-xs text-[var(--color-on-surface-variant)]">
            {repos.filter((r) => r.repo === repo).map((r) => `${r.marketplace || "—"}: ${numberFmt(r.entities)} ${t("history.entities")}, ${numberFmt(r.commits)} ${t("history.versions")}, ${t("history.since")} ${String(r.first_seen_at).slice(0, 10)}`).join(" · ")}
          </p>
        )}
      </section>

      {error && <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>}
      {loading && <Spinner />}
      {!loading && result && !rows.length && <EmptyState message={t("history.empty")} />}
      {!loading && rows.length > 0 && (
        <section className="md3-card-elevated p-4 space-y-3">
          <div className="flex justify-between items-center text-sm">
            <span>{t("history.shown")} {numberFmt(offset + 1)}–{numberFmt(offset + rows.length)}</span>
            <span className="flex gap-2">
              <button type="button" className={inputClass} disabled={offset === 0} onClick={() => load(Math.max(0, offset - PAGE_SIZE))}>←</button>
              <button type="button" className={inputClass} disabled={!result.pagination?.has_more} onClick={() => load(offset + PAGE_SIZE)}>→</button>
            </span>
          </div>
          <DataTable rows={rows} />
        </section>
      )}
    </div>
  );
}
