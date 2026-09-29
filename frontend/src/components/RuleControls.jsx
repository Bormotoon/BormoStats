import { useEffect, useState } from "react";
import { request, safeCall } from "../utils/api.js";

const STATUS_STYLES = {
  applied: "bg-green-100 text-green-700",
  simulated: "bg-blue-100 text-blue-700",
  blocked_kill_switch: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  unsupported: "bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)]",
};

/** Range input that keeps a local draft and commits once the user lets go. */
export function CommitRange({ value, onCommit, ...props }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (Number(draft) !== Number(value)) onCommit(Number(draft));
  };
  return (
    <input
      type="range"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onPointerUp={commit}
      onKeyUp={commit}
      onBlur={commit}
      {...props}
    />
  );
}

export function DryRunToggle({ rule, onChange, disabled }) {
  if (!rule) return null;
  return (
    <label className="flex items-center gap-2 text-xs">
      <input
        type="checkbox"
        checked={rule.dry_run !== false}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className={rule.dry_run !== false ? "text-blue-700 font-semibold" : "text-red-700 font-semibold"}>
        {rule.dry_run !== false ? "Только симуляция (dry-run)" : "Боевой режим: изменения отправляются на маркетплейс"}
      </span>
    </label>
  );
}

export function ActionLog({ source }) {
  const [actions, setActions] = useState([]);
  useEffect(() => {
    safeCall(() => request(`/api/v1/${source}/actions`, { query: { limit: 20 } })).then((res) => {
      setActions(res.ok ? res.data : []);
    });
  }, [source]);
  if (actions.length === 0) return null;
  return (
    <section className="md3-card-elevated p-4" aria-label="Журнал изменений">
      <h3 className="text-sm font-semibold mb-2">Журнал изменений</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[var(--color-on-surface-variant)]">
              <th className="py-1 pr-2">Время</th>
              <th className="py-1 pr-2">Цель</th>
              <th className="py-1 pr-2 text-right">Было</th>
              <th className="py-1 pr-2 text-right">Стало</th>
              <th className="py-1">Статус</th>
            </tr>
          </thead>
          <tbody>
            {actions.map((a) => (
              <tr key={a.action_id} className="border-t border-[var(--color-outline-variant)]">
                <td className="py-1 pr-2 whitespace-nowrap">{a.created_at ? new Date(a.created_at).toLocaleString() : ""}</td>
                <td className="py-1 pr-2 font-mono">{a.marketplace}/{a.target_id}</td>
                <td className="py-1 pr-2 text-right tabular-nums">{a.before_value ?? "—"}</td>
                <td className="py-1 pr-2 text-right tabular-nums">{a.after_value}</td>
                <td className="py-1">
                  <span className={`px-1.5 py-0.5 rounded ${STATUS_STYLES[a.status] || ""}`} title={a.response_body || ""}>
                    {a.status}{a.response_status ? ` · ${a.response_status}` : ""}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
