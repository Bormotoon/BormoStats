import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { usePageFilters } from "../utils/usePageFilters.js";
import { sum, groupSeries, moneyFmt, formatAsOf, ruDate, periodLabel, marketplaceName } from "../utils/formats.js";
import { downloadXlsx } from "../utils/xlsx.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";
import { FileXls } from "@phosphor-icons/react";

// the order of common/finance.py: the categories add up to net_accrued
const CATEGORIES = [
  "sales", "returns", "commission", "acquiring", "logistics", "reverse_logistics",
  "storage", "acceptance", "penalties", "other",
];
const MARKETPLACES = ["ozon", "wb"];

/** The caption of a balance card: when it was taken and what period it has accrued over. */
export function balanceCaption(b, t) {
  const parts = [`${t("finance.asOf")} ${formatAsOf(b.as_of)}`];
  if (b.last_payout_day) parts.push(`${t("finance.sincePayout")} ${ruDate(b.last_payout_day)}`);
  else if (b.marketplace === "wb") parts.push(t("finance.wbBalanceHint"));
  if (b.for_withdraw !== null && b.for_withdraw !== undefined) parts.push(`${t("finance.forWithdraw")}: ${moneyFmt(b.for_withdraw)}`);
  return parts.join(" · ");
}

export default function Finance() {
  const { t } = useI18n();
  const { searchParams, query, period, dateFrom, dateTo, marketplace, accountId } = usePageFilters();
  const [state, setState] = useState({ loading: true, daily: [], balance: [], error: "" });

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: "" }));
    Promise.all([
      requestAll("/api/v1/finance/daily", { query }),
      requestAll("/api/v1/finance/balance", { query: { marketplace, account_id: accountId } }),
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
  const payoutsKnown = (rows) => rows.some((r) => r.payouts !== null && r.payouts !== undefined);

  const exportBreakdown = () => {
    const header = [{ label: t("finance.item"), type: "text", width: 44 }, ...columns.map((mp) => ({ label: marketplaceName(mp), type: "money", width: 16 })), { label: t("finance.total"), type: "money", width: 16 }];
    const line = (label, key) => [label, ...columns.map((mp) => sum(byMarketplace(mp), key)), sum(daily, key)];
    const rows = [
      ...CATEGORIES.map((c) => line(t(`finance.categories.${c}`), c)),
      line(t("finance.netAccrued"), "net_accrued"),
      [t("finance.payouts"), ...columns.map((mp) => (payoutsKnown(byMarketplace(mp)) ? -sum(byMarketplace(mp), "payouts") : null)), -payouts],
    ];
    downloadXlsx(`Начисления ${periodLabel(dateFrom, dateTo)}`, "Начисления", header, rows);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {balance.map((b) => (
          <MetricCard
            key={`${b.marketplace}|${b.account_id}`}
            label={`${t("finance.balance")} ${marketplaceName(b.marketplace)}`}
            value={moneyFmt(b.balance)}
            subvalue={balanceCaption(b, t)}
            accent="success"
          />
        ))}
        <MetricCard label={t("finance.netAccrued")} value={moneyFmt(sum(daily, "net_accrued"))} subvalue={`${t("finance.netAccruedHint")}; ${period}`} accent="success" />
        <MetricCard label={t("finance.payouts")} value={moneyFmt(-payouts)} subvalue={`${t("finance.payoutsHint")}; ${period}`} />
      </div>

      <section className="md3-card-elevated p-4 overflow-x-auto">
        <div className="flex flex-wrap items-start justify-between gap-2 mb-3">
          <div>
            <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-1">{t("finance.breakdown")} {period}</h3>
            <p className="text-xs text-[var(--color-on-surface-variant)]">{t("finance.breakdownHint")}</p>
          </div>
          <button
            type="button"
            onClick={exportBreakdown}
            className="flex items-center gap-1 px-3 py-1.5 rounded-full border border-[var(--color-outline-variant)] text-sm font-medium hover:bg-[var(--color-surface-container)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
          >
            <FileXls size={16} aria-hidden="true" /> {t("table.excel")}
          </button>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[var(--color-on-surface-variant)] border-b border-[var(--color-outline-variant)]">
              <th className="text-left py-2 pr-4 font-medium" />
              {columns.map((mp) => <th key={mp} className="text-right py-2 px-3 font-medium">{marketplaceName(mp)}</th>)}
              <th className="text-right py-2 pl-3 font-medium">{t("finance.total")}</th>
            </tr>
          </thead>
          <tbody>
            {CATEGORIES.map((category) => (
              <tr key={category} className="border-b border-[var(--color-outline-variant)]/50">
                <td className="py-1.5 pr-4">{t(`finance.categories.${category}`)}</td>
                {columns.map((mp) => <td key={mp} className="text-right py-1.5 px-3 font-mono whitespace-nowrap">{moneyFmt(sum(byMarketplace(mp), category))}</td>)}
                <td className="text-right py-1.5 pl-3 font-mono whitespace-nowrap">{moneyFmt(sum(daily, category))}</td>
              </tr>
            ))}
            <tr className="font-semibold">
              <td className="py-2 pr-4">{t("finance.netAccrued")}</td>
              {columns.map((mp) => <td key={mp} className="text-right py-2 px-3 font-mono whitespace-nowrap">{moneyFmt(sum(byMarketplace(mp), "net_accrued"))}</td>)}
              <td className="text-right py-2 pl-3 font-mono whitespace-nowrap">{moneyFmt(sum(daily, "net_accrued"))}</td>
            </tr>
            <tr className="text-[var(--color-on-surface-variant)]">
              <td className="py-1.5 pr-4">{t("finance.payouts")}</td>
              {columns.map((mp) => {
                const rows = byMarketplace(mp);
                return <td key={mp} className="text-right py-1.5 px-3 font-mono whitespace-nowrap">{payoutsKnown(rows) ? moneyFmt(-sum(rows, "payouts")) : "—"}</td>;
              })}
              <td className="text-right py-1.5 pl-3 font-mono whitespace-nowrap">{moneyFmt(-payouts)}</td>
            </tr>
          </tbody>
        </table>
        <p className="text-xs text-[var(--color-on-surface-variant)] mt-3">{t("finance.wbNote")}</p>
      </section>

      <AreaChartCard title={`${t("finance.netByDay")} ${period}`} data={groupSeries(daily, "day", "net_accrued")} dataKey="value" name={t("finance.netAccrued")} color="var(--color-success)" currency />

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("finance.daily")} {period}</h3>
        <DataTable
          rows={daily}
          exportName={`Финансы по дням ${periodLabel(dateFrom, dateTo)}`}
          minWidth={1100}
          columns={[
            "day", "marketplace", "sales", "returns", "commission", "acquiring", "logistics", "reverse_logistics", "storage",
            "acceptance", "penalties", "other", "net_accrued",
            // stored as a withdrawal (negative); shown as the amount paid out, as in the cards
            { key: "payouts", type: "money", value: (r) => (r.payouts === null || r.payouts === undefined ? null : -r.payouts) },
            "closing_balance", "for_withdraw",
          ]}
        />
      </section>
    </div>
  );
}
