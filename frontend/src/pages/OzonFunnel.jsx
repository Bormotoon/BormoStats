import { useEffect, useMemo, useState } from "react";
import { request, requestAll } from "../utils/api.js";
import { readXlsxRows, downloadXlsx } from "../utils/xlsx.js";
import { funnelTotal, entityKey } from "../utils/ozonFunnelMetrics.js";
import { parseOzonFunnel } from "../utils/ozonFunnel.js";

import { metrics, percentMetrics, formatMetric } from "../utils/ozonFunnelDefinitions.js";
const button = "rounded-lg px-3 py-2 text-sm font-medium border border-[var(--color-outline-variant)] hover:bg-[var(--color-surface-container)] disabled:opacity-50";
export default function OzonFunnel({ query, accountId, period }) {
  const [rows, setRows] = useState([]), [related, setRelated] = useState([]), [finance, setFinance] = useState({}), [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0), [search, setSearch] = useState("");
  useEffect(() => {
    let active = true; setBusy(true); setError(""); setRows([]); setRelated([]); setFinance({});
    Promise.all([requestAll("/api/v1/funnel/ozon", {query}), requestAll("/api/v1/funnel/ozon/related", {query}), request("/api/v1/funnel/ozon/finance", {query})]).then(([r, extra, f]) => { if (active) { setRows(r.items || []); setRelated(extra.items || []); setFinance({...f, periodStart:query.date_from}); } }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [query.date_from, query.date_to, query.account_id, revision]);
  const filtered = useMemo(() => { const q = search.trim().toLowerCase(); return q ? rows.filter(r => [r.sku, r.offer_id, r.title].some(v => String(v || "").toLowerCase().includes(q))) : rows; }, [rows, search]);
  const selected = search.trim() ? new Set([...filtered.map(entityKey), ...[...related,...(finance.daily||[]),...(finance.stocks||[])].filter(r=>String(r.sku).includes(search.trim().toLowerCase())).map(entityKey)]) : null;
  const days = [];
  for (let day=query.date_from; day && day<=query.date_to; day=new Date(Date.parse(day)+86400000).toISOString().slice(0,10)) days.push(day);
  days.reverse();
  const groups = [funnelTotal(filtered, related, finance, query.date_from, query.date_to, selected), ...days.map(day => funnelTotal(filtered, related, finance, day, day, selected))];
  const rawTable = metrics.map(([name, get]) => [name, ...groups.map(get)]);
  const table = rawTable.map((row,i) => [row[0], ...row.slice(1).map(v=>formatMetric(v,i))]);
  const exportRows = rawTable.map((row,i) => [row[0], ...row.slice(1).map(v => v==null?null:{value:v,type:percentMetrics.has(i)?"percent":"number"})]);
  const columns = [{label:"Метрика", type:"text"}, {label:"Весь период", type:"text"}, ...days.map(d => ({label:d, type:"text"}))];
  async function upload(event) {
    const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
    setError(""); setNotice(""); setBusy(true);
    try {
      const parsed = parseOzonFunnel(await readXlsxRows(file));
      const result = await request("/api/v1/funnel/ozon/import", {method:"POST", body:{account_id:accountId, rows:parsed}});
      setNotice(`Загружено строк: ${result.imported}. Повторная загрузка обновляет совпадающие строки.`); setRevision(x => x + 1);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <div className="space-y-4">
    <section className="md3-card-elevated p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className={`${button} ${!accountId || busy ? "opacity-50" : "cursor-pointer"}`}>Загрузить отчёт Ozon <input type="file" accept=".xlsx" className="sr-only" disabled={!accountId || busy} onChange={upload} /></label>
        <input className="rounded-lg border border-[var(--color-outline-variant)] bg-transparent px-3 py-2 text-sm" placeholder="SKU, артикул или название" value={search} onChange={e => setSearch(e.target.value)} />
        <button className={button} disabled={busy || !!error || (!filtered.length && !related.length)} onClick={() => downloadXlsx(`Воронка Ozon ${period}`, "Воронка", columns, exportRows)}>Скачать Excel</button>
      </div>
      {!accountId && <p className="text-sm">Для загрузки выберите конкретный кабинет Ozon в верхнем меню.</p>}
      <p className="text-xs text-[var(--color-on-surface-variant)]">Заказы — количество товаров в отправлениях по дате заказа; сумма — цена из отправления. Выкупы и возвраты относятся к дню финансового события, независимо от дня заказа; отмены и ожидание — текущие статусы заказов выбранного дня. Данные о возвратах могут запаздывать. Выкупаемость считается отдельно по завершённым заказам даты оформления, с учётом возвратов. Реклама учитывает только расходы, привязанные к SKU; Авто/CPC определяется стратегией кампании из Performance API. Остаток за период — среднее дневных снимков; при неполном покрытии показан прочерк. Прогноз: заказы × выкупаемость SKU за 90 дней до начала периода; себестоимость берётся из текущих настроек. Цена покупателя, расходы МП и налог в прогнозе оцениваются по финансовой истории SKU; это оценка и она может отличаться от образца. Данные могут быть неполными. «—» означает, что показатель нельзя достоверно рассчитать по имеющимся данным.</p>
      <p className="text-xs text-[var(--color-on-surface-variant)]">Позиция за несколько строк — средняя с весом показов в поиске; значение может отличаться от итоговой позиции Ozon. Данные сохраняются по SKU, дню и схеме работы.</p>
      {!groups[0].trafficComplete && <p role="status" className="text-sm">Покрытие отчёта: {groups[0].trafficPairs} из {groups[0].expectedPairs} сочетаний «товар — день». Заказы, выкупы и реклама рассчитаны независимо от покрытия Excel.</p>}
      <details className="text-xs text-[var(--color-on-surface-variant)]"><summary className="cursor-pointer">Источники и недостающие данные</summary><p className="mt-2">Начало истории остатков: {finance.stock_start || "нет снимков"}. Для доступности по кластерам и размерам, остатков вне Ozon и суммы заказов всей категории требуется отдельный источник. Неизвестный тип кампании не включается в частичную разбивку Авто/CPC. Общие расходы без SKU не распределяются.</p></details>
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {error && <p role="alert" className="text-sm text-[var(--color-error)]">{error}</p>}
    </section>
    {busy && <p>Загрузка…</p>}
    {!busy && !filtered.length && !related.length && <p>Нет данных Ozon за выбранный период.</p>}
    {!busy && !error && (filtered.length > 0 || related.length > 0) && <section className="md3-card-elevated p-4 overflow-auto"><table className="text-sm w-full tabular-nums"><thead><tr>{columns.map(c => <th key={c.label} className="text-left whitespace-nowrap p-2 border-b border-[var(--color-outline-variant)]">{c.label}</th>)}</tr></thead><tbody>{table.map(row => <tr key={row[0]}>{row.map((v,i) => <td key={i} className="p-2 whitespace-nowrap border-b border-[var(--color-outline-variant)]">{v}</td>)}</tr>)}</tbody></table></section>}
  </div>;
}
