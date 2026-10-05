import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { sum, groupSeries, moneyFmt, isoDay, formatAsOf, DEFAULT_DATE_FROM_OFFSET } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

// the order of common/finance.py: the categories add up to net_accrued
const CATEGORIES = [
  "sales", "returns", "commission", "acquiring", "logistics", "reverse_logistics",
  "storage", "acceptance", "penalties", "other",
];
const MARKETPLACES = ["ozon", "wb"];

export default function Finance() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [state, setState] = useState({ loading: true, daily: [], balance: [], error: "" });

  const dateFrom = searchParams.get("dateFrom") || isoDay(DEFAULT_DATE_FROM_OFFSET);
  const dateTo = searchParams.get("dateTo") || isoDay(0);
  const marketplace = searchParams.get("marketplace") || "";
  const accountId = searchParams.get("accountId") || "";

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: "" }));
    const scope = { marketplace, account_id: accountId };
    Promise.all([
      requestAll("/api/v1/finance/daily", { query: { ...scope, date_from: dateFrom, date_to: dateTo } }),
      requestAll("/api/v1/finance/balance", { query: scope }),
    ])
      .then(([daily, balance]) => {
        if (!cancelled) setState({ loading: false, daily: daily.items || [], balance: balance.items || [], error: "" });
      })
      .catch((err) => { if (!cancelled) setState({ loading: false, daily: [], balance: [], error: err.message }); });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (state.loading) return <Spinner />;
  if (state.error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{state.error}</div>;

  const { daily, balance } = state;
  if (!daily.length && !balance.length) return <EmptyState message={t("finance.empty")} />;

  const byMarketplace = (mp) => daily.filter((r) => r.marketplace === mp);
  const columns = MARKETPLACES.filter((mp) => byMarketplace(mp).length);
  const payouts = sum(daily, "payouts");

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {balance.map((b) => (
          <MetricCard
            key={`${b.marketplace}|${b.account_id}`}
            label={`${t("finance.balance")} ${b.marketplace.toUpperCase()}`}
            value={moneyFmt(b.balance)}
            subvalue={[
              b.for_withdraw !== null && b.for_withdraw !== undefined ? `${t("finance.forWithdraw")}: ${moneyFmt(b.for_withdraw)}` : "",
              `${t("finance.asOf")} ${formatAsOf(b.as_of)}`,
            ].filter(Boolean).join(" · ")}
            accent="success"
          />
        ))}
        <MetricCard label={t("finance.netAccrued")} value={moneyFmt(sum(daily, "net_accrued"))} subvalue={t("finance.netAccruedHint")} accent="success" />
        <MetricCard label={t("finance.payouts")} value={moneyFmt(-payouts)} subvalue={t("finance.payoutsHint")} />
      </div>

      <section className="md3-card-elevated p-4 overflow-x-auto">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-1">{t("finance.breakdown")}</h3>
        <p className="text-xs text-[var(--color-on-surface-variant)] mb-3">{t("finance.breakdownHint")}</p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[var(--color-on-surface-variant)] border-b border-[var(--color-outline-variant)]">
              <th className="text-left py-2 pr-4 font-medium" />
              {columns.map((mp) => <th key={mp} className="text-right py-2 px-3 font-medium">{mp.toUpperCase()}</th>)}
              <th className="text-right py-2 pl-3 font-medium">{t("finance.total")}</th>
            </tr>
          </thead>
          <tbody>
            {CATEGORIES.map((category) => (
              <tr key={category} className="border-b border-[var(--color-outline-variant)]/50">
                <td className="py-1.5 pr-4">{t(`finance.categories.${category}`)}</td>
                {columns.map((mp) => <td key={mp} className="text-right py-1.5 px-3 font-mono">{moneyFmt(sum(byMarketplace(mp), category))}</td>)}
                <td className="text-right py-1.5 pl-3 font-mono">{moneyFmt(sum(daily, category))}</td>
              </tr>
            ))}
            <tr className="font-semibold">
              <td className="py-2 pr-4">{t("finance.netAccrued")}</td>
              {columns.map((mp) => <td key={mp} className="text-right py-2 px-3 font-mono">{moneyFmt(sum(byMarketplace(mp), "net_accrued"))}</td>)}
              <td className="text-right py-2 pl-3 font-mono">{moneyFmt(sum(daily, "net_accrued"))}</td>
            </tr>
            <tr className="text-[var(--color-on-surface-variant)]">
              <td className="py-1.5 pr-4">{t("finance.payouts")}</td>
              {columns.map((mp) => {
                const rows = byMarketplace(mp);
                const known = rows.some((r) => r.payouts !== null && r.payouts !== undefined);
                return <td key={mp} className="text-right py-1.5 px-3 font-mono">{known ? moneyFmt(-sum(rows, "payouts")) : "—"}</td>;
              })}
              <td className="text-right py-1.5 pl-3 font-mono">{moneyFmt(-payouts)}</td>
            </tr>
          </tbody>
        </table>
        <p className="text-xs text-[var(--color-on-surface-variant)] mt-3">{t("finance.wbNote")}</p>
      </section>

      <AreaChartCard title={t("finance.netByDay")} data={groupSeries(daily, "day", "net_accrued")} dataKey="value" name={t("finance.netAccrued")} color="var(--color-success)" currency />

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("finance.daily")}</h3>
        <DataTable rows={daily} preferredColumns={["day", "marketplace", "account_id", "sales", "returns", "commission", "logistics", "storage", "other", "net_accrued", "payouts", "closing_balance", "for_withdraw"]} />
      </section>
    </div>
  );
}
