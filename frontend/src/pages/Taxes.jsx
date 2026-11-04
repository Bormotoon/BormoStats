import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll, request, safeCall } from "../utils/api.js";
import { usePageFilters } from "../utils/usePageFilters.js";
import { sum, moneyFmt } from "../utils/formats.js";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";

export default function Taxes() {
  const { t } = useI18n();
  const { searchParams, query, period, dateFrom, dateTo, marketplace, accountId } = usePageFilters();
  const [data, setData] = useState(null);
  const [pnlData, setPnlData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      requestAll("/api/v1/finance/daily", { query }),
      safeCall(() => request("/api/v1/pnl", { query, admin: true })),
    ])
      .then(([res, pnlRes]) => {
        if (!cancelled) {
          setData(res);
          const pnlRows = pnlRes?.ok && Array.isArray(pnlRes.data) ? pnlRes.data : [];
          setPnlData(
            pnlRows.filter(
              (r) =>
                r.month?.slice(0, 7) >= dateFrom.slice(0, 7) &&
                r.month?.slice(0, 7) <= dateTo.slice(0, 7) &&
                (!r.marketplace ||
                  ((!marketplace || r.marketplace === marketplace) &&
                    (!accountId || r.account_id === accountId)))
            )
          );
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [searchParams, dateFrom, dateTo, marketplace, accountId]);

  if (loading) return <Spinner />;
  if (error)
    return (
      <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">
        {error}
      </div>
    );

  const rows = data?.items || [];
  const taxEnabled = pnlData.some((r) => r.tax_enabled);
  const taxRows = pnlData.filter((r) => r.tax_enabled && r.marketplace);

  if (!rows.length && !taxRows.length) return <EmptyState message={t("taxes.empty")} />;

  const income = sum(rows, "payout") || sum(rows, "revenue") || 0;
  const usn = income * 0.06;
  const over300k = income > 300000 ? (income - 300000) * 0.01 : 0;
  const fixed = 0;
  const total = usn + over300k + fixed;

  if (taxEnabled && taxRows.length > 0) {
    const isEstimated = taxRows.some((r) => r.tax_status !== "confirmed");
    const totalTaxBase = taxRows.reduce((s, r) => s + (r.tax_base_rub || 0), 0);
    const totalTaxRub = taxRows.reduce((s, r) => s + (r.tax_rub || 0), 0);
    const defaultTaxRate = taxRows[0]?.tax_rate_pct ?? 7;

    const monthlyTable = taxRows.map((r) => ({
      month: r.month,
      marketplace: r.marketplace ? r.marketplace.toUpperCase() : "Все",
      account_id: r.account_id || "Все",
      tax_base_rub: r.tax_base_rub,
      tax_rate_pct: `${r.tax_rate_pct}%`,
      tax_rub: r.tax_rub,
      tax_status: r.tax_status === "confirmed" ? "Подтверждён" : "Оценка (открытый период)",
    }));

    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="md3-card-elevated p-4">
            <div className="text-xs text-[var(--color-on-surface-variant)] uppercase tracking-wider">
              Налогооблагаемая база
            </div>
            <div className="text-xl font-bold font-mono mt-1 text-[var(--color-on-surface)]">
              {moneyFmt(totalTaxBase)}
            </div>
            <div className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
              {isEstimated ? "Предварительно по отчётам" : "По закрытым отчётам реализации"}
            </div>
          </div>

          <div className="md3-card-elevated p-4">
            <div className="text-xs text-[var(--color-on-surface-variant)] uppercase tracking-wider">
              Ставка налога
            </div>
            <div className="text-xl font-bold font-mono mt-1 text-[var(--color-on-surface)]">
              {defaultTaxRate}%
            </div>
            <div className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
              Реализация маркетплейсов
            </div>
          </div>

          <div className="md3-card-elevated p-4">
            <div className="text-xs text-[var(--color-on-surface-variant)] uppercase tracking-wider">
              Расчётный налог
            </div>
            <div className="text-xl font-bold font-mono mt-1 text-[var(--color-primary)]">
              {isEstimated ? "≈ " : ""}
              {moneyFmt(totalTaxRub)}
            </div>
            <div className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
              За выбранный период {period}
            </div>
          </div>

          <div className="md3-card-elevated p-4">
            <div className="text-xs text-[var(--color-on-surface-variant)] uppercase tracking-wider">
              Статус расчёта
            </div>
            <div
              className={`text-base font-bold mt-1.5 ${
                isEstimated ? "text-amber-700" : "text-emerald-700"
              }`}
            >
              {isEstimated ? "Оценка по открытым дням" : "Подтверждён отчётами"}
            </div>
            <div className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
              {isEstimated ? "Уточняется после закрытия" : "Данные сверены с актами"}
            </div>
          </div>
        </div>

        <section className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">
            Налоги по маркетплейсам и периодам (P&L Overlay)
          </h3>
          <DataTable
            rows={monthlyTable}
            columns={[
              { key: "month", label: "Месяц" },
              { key: "marketplace", label: "Площадка" },
              { key: "account_id", label: "Кабинет" },
              { key: "tax_base_rub", label: "База налога", format: "money" },
              { key: "tax_rate_pct", label: "Ставка" },
              { key: "tax_rub", label: "Сумма налога", format: "money" },
              { key: "tax_status", label: "Статус" },
            ]}
            exportName={`Налоги ${period}`}
          />
        </section>
      </div>
    );
  }

  const summary = [{ period, income, usn, over300k, fixed, total }];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="md3-card-elevated p-4">
          <div className="text-xs text-[var(--color-on-surface-variant)]">Налогооблагаемая база</div>
          <div className="text-lg font-semibold">{moneyFmt(income)}</div>
        </div>
        <div className="md3-card-elevated p-4">
          <div className="text-xs text-[var(--color-on-surface-variant)]">УСН 6%</div>
          <div className="text-lg font-semibold">{moneyFmt(usn)}</div>
        </div>
        <div className="md3-card-elevated p-4">
          <div className="text-xs text-[var(--color-on-surface-variant)]">Взносы 1% свыше 300000</div>
          <div className="text-lg font-semibold">{moneyFmt(over300k)}</div>
        </div>
        <div className="md3-card-elevated p-4">
          <div className="text-xs text-[var(--color-on-surface-variant)]">Итого налоги</div>
          <div className="text-lg font-semibold">{moneyFmt(total)}</div>
        </div>
      </div>
      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">Сводная таблица</h3>
        <DataTable
          rows={summary}
          preferredColumns={["period", "income", "usn", "over300k", "fixed", "total"]}
          exportName={`Налоги ${period}`}
        />
      </section>
    </div>
  );
}
