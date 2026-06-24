import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt, percentFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import { motion } from "motion/react";

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
  const { t } = useI18n();
  const [pnl, setPnl] = useState([]);
  const [expenses, setExpenses] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      safeCall(() => request("/api/v1/pnl", { admin: true })),
      safeCall(() => request("/api/v1/pnl/expenses", { admin: true })),
    ]).then(([pRes, eRes]) => {
      setPnl(pRes.ok ? pRes.data : []);
      setExpenses(eRes.ok ? eRes.data : []);
      setLoading(false);
    });
  }, []);

  if (loading) return <Spinner />;

  const totalRevenue = pnl.reduce((s, r) => s + r.revenue_rub, 0);
  const totalGross = pnl.reduce((s, r) => s + r.gross_profit_rub, 0);
  const totalOperating = pnl.reduce((s, r) => s + r.operating_profit_rub, 0);
  const totalNet = pnl.reduce((s, r) => s + r.net_profit_rub, 0);
  const totalAdCost = pnl.reduce((s, r) => s + r.ad_cost_rub, 0);
  const totalAdditional = pnl.reduce((s, r) => s + r.additional_expenses_rub, 0);
  const avgMargin = pnl.length ? pnl.reduce((s, r) => s + r.margin_pct, 0) / pnl.length : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <PnlCard label="Выручка" value={moneyFmt(totalRevenue)} accent="success" />
        <PnlCard label="Маржинальная прибыль" value={moneyFmt(totalGross)} accent="success" sub={`${percentFmt(avgMargin / 100)} средняя маржа`} />
        <PnlCard label="Операционная прибыль" value={moneyFmt(totalOperating)} accent={totalOperating >= 0 ? "success" : "error"} />
        <PnlCard label="Чистая прибыль" value={moneyFmt(totalNet)} accent={totalNet >= 0 ? "success" : "error"} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold mb-3">P&L по месяцам</h3>
          <div className="space-y-1 max-h-[400px] overflow-y-auto">
            {pnl.map((row, i) => (
              <div key={i} className="flex justify-between items-center py-1.5 border-b border-[var(--color-outline-variant)] last:border-0 text-sm">
                <div>
                  <p className="font-medium">{row.month}</p>
                  <p className="text-xs text-[var(--color-on-surface-variant)]">{row.marketplace} · {row.account_id}</p>
                </div>
                <p className="font-mono font-semibold">{moneyFmt(row.net_profit_rub)}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold mb-3">Структура расходов</h3>
          <div className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-on-surface-variant)]">Реклама</span>
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
            <div className="border-t border-[var(--color-outline-variant)] pt-2 flex justify-between text-sm font-semibold">
              <span>Косвенные расходы</span>
              <span className="font-mono">{moneyFmt(totalAdditional)}</span>
            </div>
          </div>
        </div>

        <div className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold mb-3">Косвенные расходы</h3>
          {expenses.length === 0 && (
            <p className="text-sm text-[var(--color-on-surface-variant)]">Нет данных</p>
          )}
          <div className="space-y-1 max-h-[400px] overflow-y-auto">
            {expenses.map((exp) => (
              <div key={exp.expense_id} className="flex justify-between items-center py-1.5 border-b border-[var(--color-outline-variant)] last:border-0 text-sm">
                <div>
                  <p className="font-medium">{exp.category}</p>
                  <p className="text-xs text-[var(--color-on-surface-variant)]">{exp.month}</p>
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
