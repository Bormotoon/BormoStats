import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

function CustomTooltip({ active, payload, label, currency }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-elevated)] shadow-lg px-3 py-2 text-sm">
      <p className="text-[var(--color-text-muted)] text-xs mb-1">{label}</p>
      {payload.map((entry, i) => (
        <p key={i} style={{ color: entry.color }} className="font-semibold font-mono">
          {entry.name}: {currency ? `${Number(entry.value).toLocaleString("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 })}` : Number(entry.value).toLocaleString("ru-RU")}
        </p>
      ))}
    </div>
  );
}

export function AreaChartCard({ title, data, dataKey = "value", name = "Value", color = "var(--color-brand)", height = 220 }) {
  if (!data?.length) return <ChartEmpty title={title} />;

  return (
    <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
      <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-3">{title}</h3>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: -8 }}>
          <defs>
            <linearGradient id={`gradient-${title.replace(/\s+/g, "-")}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" strokeOpacity={0.3} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--color-text-muted)" }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 11, fill: "var(--color-text-muted)" }} axisLine={false} tickLine={false} width={60} />
          <Tooltip content={<CustomTooltip currency={dataKey.includes("revenue") || dataKey.includes("cost")} />} />
          <Area type="monotone" dataKey={dataKey} name={name} stroke={color} strokeWidth={2} fill={`url(#gradient-${title.replace(/\s+/g, "-")})`} />
        </AreaChart>
      </ResponsiveContainer>
    </section>
  );
}

export function BarChartCard({ title, data, dataKey = "value", name = "Value", color = "var(--color-brand)", height = 220 }) {
  if (!data?.length) return <ChartEmpty title={title} />;

  return (
    <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
      <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-3">{title}</h3>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" strokeOpacity={0.3} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--color-text-muted)" }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 11, fill: "var(--color-text-muted)" }} axisLine={false} tickLine={false} width={60} />
          <Tooltip content={<CustomTooltip currency={dataKey.includes("revenue") || dataKey.includes("cost")} />} />
          <Bar dataKey={dataKey} name={name} fill={color} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </section>
  );
}

function ChartEmpty({ title }) {
  return (
    <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
      <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-3">{title}</h3>
      <div className="flex items-center justify-center h-[220px] text-[var(--color-text-muted)] text-sm">
        No data for chart
      </div>
    </section>
  );
}
