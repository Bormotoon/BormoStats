import { useState, useEffect } from "react";
import { getCurrentPrincipal, request, safeCall } from "../utils/api.js";
import { moneyFmt, percentFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import { usePageFilters } from "../utils/usePageFilters.js";
import ExpenseForm from "../components/ExpenseForm.jsx";

function PnlCard({ label, value, accent, sub }) {
  return (
    <div className="md3-card-elevated p-4">
      <p className="text-xs font-semibold text-[var(--color-on-surface-variant)] uppercase tracking-wider">{label}</p>
      <p className={`text-xl font-bold font-mono mt-1 ${accent ? `text-[var(--color-${accent})]` : "text-[var(--color-on-surface)]"}`}>{value}</p>
      {sub && <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">{sub}</p>}
    </div>
  );
}

export default function PnL() {
  const { query, dateFrom, dateTo, marketplace, accountId } = usePageFilters();
  const [daily, setDaily] = useState([]);
  const [pnl, setPnl] = useState([]);
  const [expenses, setExpenses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [canCreate, setCanCreate] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      safeCall(() => request("/api/v1/pnl", { query, admin: true })),
      safeCall(() => request("/api/v1/pnl/expenses", { admin: true })),
      safeCall(getCurrentPrincipal),
      safeCall(() => request("/api/v1/pnl/daily", { query, admin: true })),
    ]).then(([pRes, eRes, meRes, dRes]) => {
      setDaily(dRes.ok ? dRes.data.items : []);
      setPnl(pRes.ok ? pRes.data.filter(r => r.month.slice(0,7)>=dateFrom.slice(0,7) && r.month.slice(0,7)<=dateTo.slice(0,7) && (!r.marketplace || ((!marketplace || r.marketplace===marketplace) && (!accountId || r.account_id===accountId)))) : []);
      setExpenses(eRes.ok ? eRes.data : []);
      setCanCreate(meRes.ok && (meRes.data.auth_method === "admin_key" || ["owner", "admin"].includes(meRes.data.role)));
      setLoadError([!dRes.ok && `Дневной P&L: ${dRes.error}`, !pRes.ok && `P&L: ${pRes.error}`, !eRes.ok && `Расходы: ${eRes.error}`, !meRes.ok && `Не удалось проверить права: ${meRes.error}`].filter(Boolean).join(". "));
      setLoading(false);
    });
  }, [dateFrom, dateTo, marketplace, accountId]);

  if (loading) return <Spinner />;

  const totalRevenue = daily.reduce((s, r) => s + (r.revenue), 0);
  const totalGross = daily.reduce((s, r) => s + (r.net_accrued-r.cogs+r.ads), 0);
  const totalOperating = daily.reduce((s, r) => s + (r.net_accrued-r.cogs), 0);
  const totalNet = daily.reduce((s, r) => s + r.profit, 0);
  const totalAdCost = daily.reduce((s, r) => s + (r.ads), 0);
  const totalAdditional = daily.reduce((s, r) => s + (r.external), 0);
  const taxEnabled = pnl.some((r) => r.tax_enabled);
  const incompleteTax = pnl.some((r) => r.tax_enabled && r.tax_status !== "confirmed");
  const taxRate = pnl.find((r) => r.tax_enabled)?.tax_rate_pct;
  const totalTax = daily.reduce((s, r) => s + (r.tax), 0);
  const total = (key) => pnl.reduce((s, r) => s + (r[key] || 0), 0);
  const netRevenue = totalRevenue;
  // gross margin of the whole period: an average of monthly percentages would weigh a
  // month with little revenue as much as the best month
  const avgMargin = netRevenue ? (totalGross / netRevenue) * 100 : 0;
  const noCosts = pnl.length > 0 && total("cogs_rub") === 0;

  return (
    <div className="space-y-4">
      {loadError && <p role="alert" className="rounded-xl p-3 text-sm text-[var(--color-error)]">{loadError}</p>}
      {canCreate ? <ExpenseForm onSaved={(expense) => setExpenses((rows) => [expense, ...rows].sort((a, b) => (b.expense_date || b.month).localeCompare(a.expense_date || a.month) || a.category.localeCompare(b.category, "ru")))} /> : <p className="text-sm text-[var(--color-on-surface-variant)]">Внешние расходы может добавлять администратор организации.</p>}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <PnlCard label="Выручка за вычетом возвратов" value={moneyFmt(totalRevenue)} accent="success" />
        <PnlCard label="Маржинальная прибыль" value={moneyFmt(totalGross)} accent="success" sub={`${percentFmt(avgMargin / 100)} от выручки за вычетом возвратов`} />
        <PnlCard label="Операционная прибыль" value={moneyFmt(totalOperating)} accent={totalOperating >= 0 ? "success" : "error"} />
        <PnlCard label="Чистая прибыль" value={`${incompleteTax ? "≈ " : ""}${moneyFmt(totalNet)}`} accent={totalNet >= 0 ? "success" : "error"}
          sub={loadError ? "Ошибка загрузки" : `За ${dateFrom} — ${dateTo}. ` + (incompleteTax ? "Предварительно: часть налога рассчитана по ценам покупателя за вычетом возвратов" : taxEnabled ? "После налога по отчётам о реализации" : "До налога")} />
      </div>

      {noCosts && (
        <div className="rounded-xl border border-[var(--color-warning,orange)]/40 p-3 text-sm">
          Себестоимость товаров не заведена, поэтому прибыль посчитана без неё: это то, что остаётся
          после всех удержаний маркетплейсов и рекламы. Задайте себестоимость (API <code>/api/v1/costs</code>),
          и она вычтется автоматически.
        </div>
      )}

      {taxEnabled && (
        <div className="md3-card-elevated p-4 text-sm">
          Налог {taxRate}% = (реализовано на сумму − возвраты) по месячному отчёту Ozon.
          {" "}Суммы начислений и выплат не заменяют эту базу. Налог — расчёт по заданной ставке.
          {incompleteTax && <p className="mt-1">Пока нет полного отчёта, налог предварительно считается по ценам покупателя за вычетом возвратов.
            После загрузки отчёта расчёт автоматически уточняется.</p>}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold mb-3">P&L по месяцам · полные месяцы</h3>
          <div className="space-y-1 max-h-[400px] overflow-y-auto">
            {pnl.map((row, i) => (
              <div key={i} className="flex flex-col gap-1 py-2 border-b border-[var(--color-outline-variant)] last:border-0 text-sm">
                <div>
                  <p className="font-medium">{row.month}</p>
                  <p className="text-xs text-[var(--color-on-surface-variant)]">{row.marketplace ? `${row.marketplace} · ${row.account_id}` : "косвенные расходы"}</p>
                </div>
                <div className="text-right">
                  {row.tax_enabled && <>
                    <p className="text-xs">До налога: {moneyFmt(row.profit_before_tax_rub)}</p>
                    <p className="text-xs">{row.tax_status === "estimated" ? "Предварительная база" : "База по реализации"}: {row.tax_base_rub == null ? "нет отчёта" : moneyFmt(row.tax_base_rub)}</p>
                    <p className="text-xs">Налог {row.tax_rate_pct}%: {row.tax_rub == null ? "нет отчёта" : moneyFmt(row.tax_rub)}</p>
                    {row.tax_status === "estimated" && <p className="text-xs">Предварительно, до полного отчёта</p>}
                  </>}
                  <p className="font-mono font-semibold">{row.net_profit_rub == null ? "После налога: —" : moneyFmt(row.net_profit_rub)}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold mb-3">Структура расходов · полные месяцы</h3>
          <div className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Реклама · удержано Ozon</span>
              <span className="font-mono font-semibold">{moneyFmt(totalAdCost)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Комиссии</span>
              <span className="font-mono font-semibold">{moneyFmt(pnl.reduce((s, r) => s + r.commission_rub, 0))}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Логистика</span>
              <span className="font-mono font-semibold">{moneyFmt(pnl.reduce((s, r) => s + r.logistics_rub, 0))}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Возвраты</span>
              <span className="font-mono font-semibold">{moneyFmt(pnl.reduce((s, r) => s + r.returns_cost_rub, 0))}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Хранение</span>
              <span className="font-mono font-semibold">{moneyFmt(total("storage_rub"))}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Прочие удержания</span>
              <span className="font-mono font-semibold">{moneyFmt(total("other_costs_rub"))}</span>
            </div>
            <div className="flex justify-between text-sm font-semibold">
              <span>Начислено маркетплейсами</span>
              <span className="font-mono">{moneyFmt(total("net_accrued_rub"))}</span>
            </div>
            {total("financing_adjustment_rub") !== 0 && <div className="flex justify-between text-sm">
              <span>Возврат долга · исключен из расходов</span>
              <span className="font-mono">{total("financing_adjustment_rub") > 0 ? "+" : ""}{moneyFmt(total("financing_adjustment_rub"))}</span>
            </div>}
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Себестоимость</span>
              <span className="font-mono font-semibold">{moneyFmt(total("cogs_rub"))}</span>
            </div>
            <div className="border-t border-[var(--color-outline-variant)] pt-2 flex justify-between text-sm font-semibold">
              <span>Косвенные расходы</span>
              <span className="font-mono">{moneyFmt(totalAdditional)}</span>
            </div>
            {taxEnabled && <div className="border-t border-[var(--color-outline-variant)] pt-2 flex justify-between text-sm font-semibold">
              <span>Налог {taxRate}%{incompleteTax ? " · частично предварительно" : " · закрытые отчёты"}</span>
              <span className="font-mono">{moneyFmt(totalTax)}</span>
            </div>}
          </div>
        </div>

        <div className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold mb-3">Внешние (косвенные) расходы</h3>
          {expenses.length === 0 && (
            <p className="text-sm text-[var(--color-on-surface-variant)]">Нет данных</p>
          )}
          <div className="space-y-1 max-h-[400px] overflow-y-auto">
            {expenses.map((exp) => (
              <div key={exp.expense_id} className="flex justify-between items-center py-1.5 border-b border-[var(--color-outline-variant)] last:border-0 text-sm">
                <div>
                  <p className="font-medium">{exp.category}</p>
                  <p className="text-xs text-[var(--color-on-surface-variant)]">{exp.expense_date ? new Date(`${exp.expense_date}T00:00:00`).toLocaleDateString("ru-RU") : `${exp.month} (за месяц)`}</p>
                  {exp.description && <p className="text-xs text-[var(--color-on-surface-variant)] break-words">{exp.description}</p>}
                </div>
                <p className="font-mono">{moneyFmt(exp.amount_rub)}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
