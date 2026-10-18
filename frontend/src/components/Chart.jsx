import { useI18n } from "../utils/i18n.jsx";
import { axisNumber, ruDate } from "../utils/formats.js";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";

function CustomTooltip({ active, payload, label, currency, unit, labelText }) {
  if (!active || !payload?.length) return null;
  const caption = labelText ? labelText(label, payload[0]?.payload) : ruDate(label);
  return (
    <div className="md3-card-elevated px-3 py-2 text-sm shadow-lg max-w-xs">
      <p className="text-[var(--color-on-surface-variant)] text-xs mb-1">{caption}</p>
      {payload.map((entry, i) => (
        <p key={i} style={{ color: entry.color }} className="font-semibold font-mono">
          {entry.name}: {currency
            ? Number(entry.value).toLocaleString("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 })
            : `${Number(entry.value).toLocaleString("ru-RU")}${unit ? ` ${unit}` : ""}`}
        </p>
      ))}
    </div>
  );
}

/**
 * Daily figures as areas. One series by `dataKey`/`name`/`color`, or several by
 * `series=[{ dataKey, name, color }]` over rows that carry every key.
 */
export function AreaChartCard({ title, data, dataKey = "value", name = "Value", color = "var(--color-primary)", height = 220, currency = false, series }) {
  if (!data?.length) return <ChartEmpty title={title} />;
  const lines = series || [{ dataKey, name, color }];
  const gradientId = (i) => `gradient-${title.replace(/[^\p{L}\p{N}]+/gu, "-")}-${i}`;

  return (
    <section className="md3-card-elevated p-4">
      <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{title}</h3>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: -8 }}>
          <defs>
            {lines.map((line, i) => (
              <linearGradient key={line.dataKey} id={gradientId(i)} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={line.color} stopOpacity={0.15} />
                <stop offset="100%" stopColor={line.color} stopOpacity={0.01} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-outline-variant)" strokeOpacity={0.5} />
          <XAxis dataKey="label" tickFormatter={ruDate} tick={{ fontSize: 11, fill: "var(--color-on-surface-variant)" }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          <YAxis tickFormatter={(value) => axisNumber(value, currency)} tick={{ fontSize: 11, fill: "var(--color-on-surface-variant)" }} axisLine={false} tickLine={false} width={currency ? 88 : 60} />
          <Tooltip content={<CustomTooltip currency={currency} />} />
          {lines.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {lines.map((line, i) => (
            <Area key={line.dataKey} type="monotone" dataKey={line.dataKey} name={line.name} stroke={line.color} strokeWidth={2} fill={`url(#${gradientId(i)})`} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </section>
  );
}

/**
 * Bars by `label`. Labels are dates unless `categorical`: then they are shown as they are,
 * slanted when long, and `labelText(label, row)` may give the tooltip a fuller caption.
 */
export function BarChartCard({ title, data, dataKey = "value", name = "Value", color = "var(--color-primary)", height = 220, currency = false, categorical = false, unit, labelText, subtitle }) {
  if (!data?.length) return <ChartEmpty title={title} />;

  return (
    <section className="md3-card-elevated p-4">
      <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-1">{title}</h3>
      {subtitle && <p className="text-xs text-[var(--color-on-surface-variant)] mb-3">{subtitle}</p>}
      <ResponsiveContainer width="100%" height={categorical ? height + 50 : height}>
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-outline-variant)" strokeOpacity={0.5} />
          {categorical ? (
            <XAxis dataKey="label" interval={0} angle={-35} textAnchor="end" height={70} tick={{ fontSize: 10, fill: "var(--color-on-surface-variant)" }} axisLine={false} tickLine={false} />
          ) : (
            <XAxis dataKey="label" tickFormatter={ruDate} tick={{ fontSize: 11, fill: "var(--color-on-surface-variant)" }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          )}
          <YAxis tickFormatter={(value) => axisNumber(value, currency)} tick={{ fontSize: 11, fill: "var(--color-on-surface-variant)" }} axisLine={false} tickLine={false} width={currency ? 88 : 60} />
          <Tooltip content={<CustomTooltip currency={currency} unit={unit} labelText={categorical ? (labelText || ((label) => label)) : undefined} />} />
          <Bar dataKey={dataKey} name={name} fill={color} radius={[6, 6, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </section>
  );
}

function ChartEmpty({ title }) {
  const { t } = useI18n();
  return (
    <section className="md3-card-elevated p-4">
      <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{title}</h3>
      <div className="flex items-center justify-center h-[220px] text-[var(--color-on-surface-variant)] text-sm">
        {t("common.noData")}
      </div>
    </section>
  );
}
