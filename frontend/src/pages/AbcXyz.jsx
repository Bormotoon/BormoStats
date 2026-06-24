import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt, numberFmt, percentFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import { useSearchParams } from "react-router-dom";

const ABC_LABELS = {
  A: { label: "A — Топ", color: "bg-green-100 text-green-700" },
  B: { label: "B — Средний", color: "bg-yellow-100 text-yellow-700" },
  C: { label: "C — Низкий", color: "bg-red-100 text-red-700" },
};

const XYZ_LABELS = {
  X: { label: "X — Стабильный", color: "bg-green-100 text-green-700" },
  Y: { label: "Y — Средний", color: "bg-yellow-100 text-yellow-700" },
  Z: { label: "Z — Нестабильный", color: "bg-red-100 text-red-700" },
};

const COMBINED_LABELS = {
  AX: "Лидер",
  AY: "Звезда",
  AZ: "Нестабильный лидер",
  BX: "Перспективный",
  BY: "Средний",
  BZ: "Рисковый",
  CX: "Спящий",
  CY: "Второстепенный",
  CZ: "Неликвид",
};

function Badge({ label, color }) {
  return <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${color}`}>{label}</span>;
}

export default function AbcXyz() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = {};
    const mp = searchParams.get("marketplace");
    const aid = searchParams.get("accountId");
    if (mp) params.marketplace = mp;
    if (aid) params.account_id = aid;

    safeCall(() => request("/api/v1/abc-xyz", { query: params, admin: true })).then((res) => {
      setData(res.ok ? res.data : []);
      setLoading(false);
    });
  }, [searchParams]);

  if (loading) return <Spinner />;

  if (data.length === 0) {
    return (
      <div className="text-center py-16 text-[var(--color-on-surface-variant)]">
        <p className="font-semibold">Нет данных ABC/XYZ анализа</p>
        <p className="text-sm mt-1">Данные появятся после сборки витрины mrt_abc_xyz_analysis</p>
      </div>
    );
  }

  const groups = {};
  for (const row of data) {
    const key = `${row.abc_class}${row.xyz_class}`;
    if (!groups[key]) groups[key] = [];
    groups[key].push(row);
  }

  const counts = { A: 0, B: 0, C: 0, X: 0, Y: 0, Z: 0 };
  for (const row of data) {
    counts[row.abc_class]++;
    counts[row.xyz_class]++;
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-6 gap-3">
        {Object.entries({ A: "A — 80%", B: "B — 15%", C: "C — 5%" }).map(([k, v]) => (
          <div key={k} className="md3-card-elevated p-3 text-center">
            <Badge label={v} color={ABC_LABELS[k].color} />
            <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">{counts[k]} товаров</p>
          </div>
        ))}
        {Object.entries({ X: "X — CV<10%", Y: "Y — 10-25%", Z: "Z — >25%" }).map(([k, v]) => (
          <div key={k} className="md3-card-elevated p-3 text-center">
            <Badge label={v} color={XYZ_LABELS[k].color} />
            <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">{counts[k]} товаров</p>
          </div>
        ))}
      </div>

      <div className="md3-card-elevated p-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-outline-variant)] text-xs text-[var(--color-on-surface-variant)]">
              <th className="text-left py-2 pr-4">Товар</th>
              <th className="text-left py-2 pr-4">МП</th>
              <th className="text-right py-2 pr-4">Выручка 60д</th>
              <th className="text-right py-2 pr-4">Доля</th>
              <th className="text-center py-2 pr-4">ABC</th>
              <th className="text-center py-2 pr-4">XYZ</th>
              <th className="text-left py-2 pr-4">Тип</th>
              <th className="text-right py-2 pr-4">CV</th>
              <th className="text-right py-2 pr-4">Ср. дн. продажи</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => {
              const comboKey = `${row.abc_class}${row.xyz_class}`;
              return (
                <tr key={i} className="border-b border-[var(--color-outline-variant)] last:border-0 hover:bg-[var(--color-surface-container)]">
                  <td className="py-2 pr-4 font-medium truncate max-w-[200px]">{row.product_id}</td>
                  <td className="py-2 pr-4">{row.marketplace === "wb" ? "WB" : "Ozon"}</td>
                  <td className="py-2 pr-4 text-right font-mono">{moneyFmt(row.revenue_60d)}</td>
                  <td className="py-2 pr-4 text-right font-mono">{percentFmt(row.share_pct)}</td>
                  <td className="py-2 pr-4 text-center">
                    <Badge label={row.abc_class} color={ABC_LABELS[row.abc_class].color} />
                  </td>
                  <td className="py-2 pr-4 text-center">
                    <Badge label={row.xyz_class} color={XYZ_LABELS[row.xyz_class].color} />
                  </td>
                  <td className="py-2 pr-4">
                    <span className="font-semibold text-xs">{COMBINED_LABELS[comboKey] || comboKey}</span>
                  </td>
                  <td className="py-2 pr-4 text-right font-mono">{percentFmt(row.cv_pct / 100)}</td>
                  <td className="py-2 pr-4 text-right font-mono">{numberFmt(row.daily_mean_qty, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
