import { useEffect, useMemo, useState } from 'react';
import { request } from '../utils/api.js';
import { usePageFilters } from '../utils/usePageFilters.js';
import { downloadXlsx } from '../utils/xlsx.js';
import { Spinner } from '../components/StatusChip.jsx';
import { makeMatcher } from '../components/DataTable.jsx';
import { ECONOMICS_GROUPS, ALL_ECONOMICS_COLUMNS, COMPACT_ECONOMICS_KEYS, loadEconomicsColumns } from '../utils/economicsColumns.js';

const button = 'rounded-lg border border-[var(--color-outline-variant)] px-3 py-2 text-sm hover:bg-[var(--color-surface-container)]';
function format(value,col) {
  if (value==null) return '—';
  if (col.type==='text') return String(value);
  if (col.type==='percent') return (value*100).toLocaleString('ru-RU',{maximumFractionDigits:2})+'%';
  return Number(value).toLocaleString('ru-RU',{maximumFractionDigits:col.key.endsWith('_unit')?0:2});
}
export default function Economics() {
  const {query,dateFrom,dateTo,searchParams}=usePageFilters();
  const [data,setData]=useState(null), [error,setError]=useState(''),[loading,setLoading]=useState(true);
  const [keys,setKeys]=useState(()=>loadEconomicsColumns(localStorage));
  const [picker,setPicker]=useState(false),[filtersOpen,setFiltersOpen]=useState(false),[filters,setFilters]=useState({});
  const [search,setSearch]=useState(''),[sort,setSort]=useState({key:'revenue',dir:-1});
  useEffect(()=>{try{localStorage.setItem('economics:columns:v1',JSON.stringify(keys));}catch{}},[keys]);
  useEffect(()=>{let active=true;setLoading(true);setError('');
    request('/api/v1/economics',{query}).then(r=>{if(active)setData(r);}).catch(e=>{if(active)setError(String(e.message||e));})
      .finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[searchParams]);
  const visibleCols=ALL_ECONOMICS_COLUMNS.filter(c=>keys.includes(c.key));
  const groups=ECONOMICS_GROUPS.map(g=>({...g,visible:g.columns.filter(c=>keys.includes(c.key))})).filter(g=>g.visible.length);
  const filtered=useMemo(()=>{
    const matches=ALL_ECONOMICS_COLUMNS.map(c=>[c,makeMatcher(c,filters[c.key]||'')]).filter(([,m])=>m);
    const out=(data?.items||[]).filter(r=>(!search||`${r.offer_id} ${r.title} ${r.sku}`.toLowerCase().includes(search.toLowerCase()))&&matches.every(([c,m])=>m(r[c.key])));
    return [...out].sort((a,b)=>{const x=a[sort.key],y=b[sort.key];if(x==null||y==null)return x==null?(y==null?0:1):-1;
      return (typeof x==='number'?x-y:String(x).localeCompare(String(y),'ru',{numeric:true}))*sort.dir;});
  },[data,search,sort,filters]);
  const toggle=(key)=>{if(key==='offer_id')return;setKeys(old=>old.includes(key)?old.filter(k=>k!==key):[...old,key]);};
  const toggleGroup=(g)=>setKeys(old=>{
    const expanded=g.columns.slice(1).some(c=>old.includes(c.key));
    const remove=new Set(g.columns.map(c=>c.key));
    return [...old.filter(k=>!remove.has(k)),...(expanded?[g.columns[0].key]:g.columns.map(c=>c.key))];});
  const shownValue=(row,col)=>row.sku==='unallocated'&&col.key.endsWith('_unit')?row[col.key.slice(0,-5)]
    :row.sku==='unallocated'&&col.key==='period'?'Суммы за период':row[col.key];
  const exportView=()=>{
    const cols=visibleCols;
    downloadXlsx(`Экономика ${dateFrom}–${dateTo}`,'Экономика',cols.map(c=>({label:c.groupLabel?`${c.groupLabel} · ${c.label}`:c.label,type:c.type==='image'?'text':c.type,width:c.type==='text'?24:18})),
      [data.total,...filtered].filter(Boolean).map(r=>cols.map(c=>shownValue(r,c))));
  };
  const sticky=(c)=>c.key==='image_url'?{position:'sticky',left:0,zIndex:2,minWidth:56,width:56}:c.key==='offer_id'?{position:'sticky',left:keys.includes('image_url')?56:0,zIndex:2,minWidth:200,maxWidth:200}:{};
  const cell=(row,col)=>{
    if(col.type==='image')return row.image_url?<img src={row.image_url} alt="" className="h-12 w-10 object-contain mx-auto" loading="lazy" referrerPolicy="no-referrer"/>:null;
    if(row.sku==='unallocated'&&col.key.endsWith('_unit'))return format(row[col.key.slice(0,-5)],{...col,key:col.key.slice(0,-5)});
    if(row.sku==='unallocated'&&col.key==='period')return 'Суммы за период';
    return format(row[col.key],col);
  };
  if(loading)return <Spinner/>;
  if(error)return <p role="alert" className="p-4 text-red-700">Не удалось загрузить экономику: {error}</p>;
  return <div className="space-y-3 min-w-0">
    <div className="flex flex-wrap gap-2 items-center">
      <button className={button} onClick={()=>setKeys(COMPACT_ECONOMICS_KEYS)}>Кратко · 16 столбцов</button>
      <button className={button} onClick={()=>setKeys(ALL_ECONOMICS_COLUMNS.map(c=>c.key))}>Полностью · 66 столбцов</button>
      <button className={button} onClick={()=>setPicker(!picker)} aria-expanded={picker}>Столбцы · {visibleCols.length}/66</button>
      <button className={button} onClick={()=>setFiltersOpen(!filtersOpen)} aria-pressed={filtersOpen}>Фильтры</button>
      <button className={button} onClick={exportView} disabled={!data?.items?.length}>Скачать текущий вид в Excel</button>
      <input aria-label="Поиск по артикулу" className="rounded-lg border px-3 py-2 text-sm" placeholder="Артикул или название" value={search} onChange={e=>setSearch(e.target.value)}/>
    </div>
    {picker&&<div className="md3-card-elevated p-4 max-h-[45vh] overflow-auto grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4" aria-label="Выбор столбцов">
      {ECONOMICS_GROUPS.map(g=><fieldset key={g.id}><legend className="font-semibold text-sm mb-2">{g.label||g.columns[0].label}</legend>
        {g.columns.map(c=><label key={c.key} className="flex gap-2 items-start text-xs py-1"><input type="checkbox" checked={keys.includes(c.key)} disabled={c.key==='offer_id'} onChange={()=>toggle(c.key)}/>{c.label}</label>)}
      </fieldset>)}
    </div>}
    <div className="text-xs text-[var(--color-on-surface-variant)] flex flex-wrap gap-x-4 gap-y-1">
      <span>Артикулов: {filtered.length} · Период: {dateFrom}–{dateTo}</span>
      <span>{data.tax_enabled?`Налог ${data.tax_rate_pct}% · ${data.tax_estimate?'оценка по дням / открытым месяцам':'по закрытым отчётам реализации'}`:'Налог отключён'}</span>
      <span>Нажмите + / − в заголовке группы, чтобы раскрыть детали</span>
      <span>Без распределения между артикулами · реклама по SKU: {(data.ads_sku_linked||0).toLocaleString('ru-RU',{maximumFractionDigits:2})} ₽</span>
      <span>СНГ: {data.cis_coverage_complete?`${data.total?.sales_cis??0} шт. · отчёты за весь период`:'период загружен не полностью'}</span>
    </div>
    {data.missing_costs?.length>0&&<p className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm">Не задана себестоимость: {data.missing_costs.join(', ')}. Прибыль этих артикулов и общий итог прибыли не определены.</p>}
    {data.external_period_incomplete&&<p className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm">Есть внешние расходы за целый месяц. Их сумма за выбранные дни не определена; прибыль без этих данных не рассчитывается.</p>}
    {!data.cis_coverage_complete&&data.cis_missing_days?.length>0&&<p className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm">Не загружены отчёты СНГ за {data.cis_missing_days.length} дн. выбранного периода. Итоги учитывают только имеющиеся данные. Сейчас обновлена последняя неделя; выберите её для полного расчёта.</p>}
    {Object.values(filters).some(Boolean)&&<button className={button} onClick={()=>setFilters({})}>Сбросить фильтры</button>}
    <div className="overflow-auto rounded-xl border border-[var(--color-outline-variant)] max-w-full" style={{maxHeight:'68vh'}}>
      <table className="text-xs border-separate border-spacing-0" style={{width:'max-content',minWidth:'100%'}}>
        <thead className="sticky top-0 z-20">
          <tr>{groups.map(g=><th key={g.id} colSpan={g.visible.length} className="bg-[#dae8f4] border-b border-r border-slate-300 px-2 py-2 text-center font-semibold" style={g.columns.length===1?sticky(g.columns[0]):{}}>
            {g.columns.length>1?<button className="flex items-center justify-center gap-2 mx-auto" aria-label={`${g.columns.slice(1).some(c=>keys.includes(c.key))?'Свернуть':'Раскрыть'} ${g.label}`} onClick={()=>toggleGroup(g)}>
              <span className="inline-flex items-center justify-center h-4 w-4 rounded border border-slate-500">{g.columns.slice(1).some(c=>keys.includes(c.key))?'−':'+'}</span>{g.label}</button>:g.label}
          </th>)}</tr>
          <tr>{visibleCols.map(c=><th key={c.key} className="bg-[#edf3f9] border-b border-r border-slate-300 px-2 py-2 font-medium text-center" style={{minWidth:c.type==='image'?56:c.type==='text'?150:132,maxWidth:190,...sticky(c)}}>
            <button className="w-full whitespace-normal" onClick={()=>c.type!=='image'&&setSort(s=>({key:c.key,dir:s.key===c.key?-s.dir:-1}))}>{c.label}{sort.key===c.key?(sort.dir===1?' ↑':' ↓'):''}</button>
          </th>)}</tr>
          {filtersOpen&&<tr>{visibleCols.map(c=><th key={c.key} className="bg-slate-50 border-b px-1 py-1" style={sticky(c)}>{c.type!=='image'&&<input aria-label={`Фильтр ${c.groupLabel} ${c.label}`} value={filters[c.key]||''} onChange={e=>setFilters({...filters,[c.key]:e.target.value})} className="border rounded w-full min-w-0 px-1 py-1" placeholder="Фильтр"/>}</th>)}</tr>}
        </thead>
        <tbody>
          {[...(data.total?[data.total]:[]),...filtered].map((row,i)=><tr key={row.sku} className={i===0?'font-semibold':'hover:bg-slate-50'}>
            {visibleCols.map(c=><td key={c.key} title={c.key==='offer_id'?`${row.title||''} · SKU ${row.sku}`:undefined}
              className={`border-b border-r border-slate-200 px-2 py-2 tabular-nums whitespace-nowrap ${i===0?'bg-[#eaf1f7]':row.sku==='unallocated'?'bg-amber-50':c.key==='image_url'||c.key==='offer_id'?'bg-white':''} ${c.type==='text'?'text-left':'text-right'} ${typeof row[c.key]==='number'&&row[c.key]<0?'text-red-700':''}`}
              style={sticky(c)}>{cell(row,c)}</td>)}
          </tr>)}
        </tbody>
      </table>
    </div>
    <p className="text-xs text-[var(--color-on-surface-variant)]">Итого — весь выбранный период; поиск и фильтры меняют список артикулов. Скрытие столбцов не меняет расчёты. Выбранный вид сохраняется в этом браузере.</p>
    <p className="text-xs text-[var(--color-on-surface-variant)]">В строке «Расходы без привязки» показаны общие суммы за период. Они не распределяются между SKU. Разница между начислением рекламы и расходом Performance API остаётся в этой строке.</p>
    <details className="md3-card-elevated p-3 text-xs"><summary className="cursor-pointer font-semibold">Источники и правила расчёта</summary>
      <div className="space-y-1 mt-2">{data.notes?.map(n=><p key={n}>{n}</p>)}
        <p>Обработано операций Ozon: {data.operations?.toLocaleString('ru-RU')}. Начислено по исходным операциям: {data.source_net_accrued?.toLocaleString('ru-RU',{maximumFractionDigits:2})} ₽.</p>
        <p>Расходы без привязки: {Object.entries(data.unattributed_costs||{}).map(([k,v])=>`${k}: ${v.toLocaleString('ru-RU',{maximumFractionDigits:2})} ₽`).join('; ')||'нет'}.</p>
      </div>
    </details>
  </div>;
}
