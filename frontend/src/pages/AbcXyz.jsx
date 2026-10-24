import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt, numberFmt, percentFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";
import BuyerCardLink from "../components/BuyerCardLink.jsx";
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

      <DataTable
        rows={data}
        exportName="ABC-XYZ"
        stateKey="abc-xyz"
        rowKey={(row) => `${row.marketplace}:${row.account_id}:${row.product_id}`}
        minWidth={1100}
        columns={[
          { key: "image_url", type: "image" },
          {
            key: "offer_id",
            label: "Артикул продавца",
            type: "text",
            width: 24,
            render: (row) => (
              <div className="min-w-0">
                <BuyerCardLink marketplace={row.marketplace} productId={row.product_id}>
                  {row.offer_id || row.product_id}
                </BuyerCardLink>
                {row.title && <div className="text-xs text-[var(--color-on-surface-variant)] truncate max-w-[240px]">{row.title}</div>}
              </div>
            ),
          },
          { key: "product_id", label: "Артикул площадки", type: "text", render: (row) => <span className="font-mono text-xs">{row.product_id}</span> },
          { key: "marketplace", label: "МП", type: "text" },
          { key: "revenue_60d", label: "Выручка 60д", type: "money", render: (row) => <span className="font-mono">{moneyFmt(row.revenue_60d)}</span> },
          { key: "share_pct", label: "Доля", type: "percent", render: (row) => <span className="font-mono">{percentFmt(row.share_pct)}</span> },
          { key: "abc_class", label: "ABC", type: "text", align: "center", render: (row) => <Badge label={row.abc_class} color={ABC_LABELS[row.abc_class].color} /> },
          { key: "xyz_class", label: "XYZ", type: "text", align: "center", render: (row) => <Badge label={row.xyz_class} color={XYZ_LABELS[row.xyz_class].color} /> },
          {
            key: "combined",
            label: "Тип",
            type: "text",
            value: (row) => COMBINED_LABELS[`${row.abc_class}${row.xyz_class}`] || `${row.abc_class}${row.xyz_class}`,
            render: (row) => <span className="font-semibold text-xs">{COMBINED_LABELS[`${row.abc_class}${row.xyz_class}`] || `${row.abc_class}${row.xyz_class}`}</span>,
          },
          { key: "cv_pct", label: "CV", type: "percent", value: (row) => row.cv_pct / 100, render: (row) => <span className="font-mono">{percentFmt(row.cv_pct / 100)}</span> },
          { key: "daily_mean_qty", label: "Ср. дн. продажи", type: "number", render: (row) => <span className="font-mono">{numberFmt(row.daily_mean_qty, 1)}</span> },
        ]}
      />
    </div>
  );
}
