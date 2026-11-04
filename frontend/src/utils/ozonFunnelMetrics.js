// Event metrics and cohort forecasts have independent date axes.
const entity = r => JSON.stringify([r.account_id, r.sku]);
const sum = (rows, field) => rows.reduce((s, r) => s + Number(r[field] || 0), 0);
export function funnelTotal(rows, related, finance, from, to, selected = null) {
  const accepts = r => (!selected || selected.has(entity(r)));
  const inPeriod = r => accepts(r) && r.day >= from && r.day <= to;
  const traffic = rows.filter(inPeriod), events = related.filter(inPeriod);
  const daily = (finance.daily || []).filter(inPeriod);
  const orders = events.filter(r => r.kind === "orders");
  const ads = events.filter(r => r.kind === "ads");
  const x = {impressions:sum(traffic,"impressions"), search_impressions:sum(traffic,"search_impressions"),
    clicks:sum(traffic,"clicks"), carts:sum(traffic,"carts"), position:0, weight:0,
    orders:orders.length ? sum(orders,"qty") : null, orderSum:orders.length ? sum(orders,"amount") : null,
    cancelled:null, pending:null, delivered:daily.length ? sum(daily,"sold") : null,
    returned:daily.length ? sum(daily,"returned") : null, ads:ads.length ? sum(ads,"amount") : null,
    forecastQty:null,forecastRevenue:null,forecastCost:null,stock:null,stockFbs:null,transit:null,reverse:null,
    stockCost:null,buyerPrice:null,mpCost:null,tax:null,external:finance.external ?? null,
    forecastOperating:null,forecastProfit:null,adsAuto:null,adsCpc:null};
  const advertising=(finance.advertising||[]).filter(inPeriod);
  if(advertising.length && advertising.every(r=>r.kind==="auto"||r.kind==="cpc")) {
    x.adsAuto=sum(advertising.filter(r=>r.kind==="auto"),"amount");
    x.adsCpc=sum(advertising.filter(r=>r.kind==="cpc"),"amount");
  }
  for (const kind of ["cancelled","pending"]) {
    const records=events.filter(r=>r.kind===kind);
    x[kind]=records.length ? sum(records,"qty") : orders.length ? 0 : null;
  }
  const completed=events.filter(r=>r.kind==='cohort_delivered');
  const resolved=sum(completed,'amount')+(x.cancelled??0);
  x.buyoutRate=resolved>0?sum(completed,'qty')/resolved:null;
  for (const r of traffic) if (r.position > 0) { x.position+=r.position*r.search_impressions; x.weight+=r.search_impressions; }
  const history = new Map(), costs = new Map(), profiles=new Map();
  for (const r of related) {
    if(r.kind==="history") history.set(entity(r),{sold:Number(r.qty),cancelled:Number(r.amount)});
    if(r.kind==="cost") costs.set(entity(r),Number(r.amount));
  }
  // The same baseline is used for every displayed day and for the period total.
  for (const r of finance.daily || []) if (r.day < finance.periodStart && accepts(r)) {
    const key=entity(r), p=profiles.get(key)||{qty:0,revenue:0,buyer:0,mp:0};
    p.qty+=r.sold-r.returned;p.revenue+=r.revenue;p.buyer+=r.buyer;p.mp+=r.mp_cost;profiles.set(key,p);
  }
  let qty=0,revenue=0,cost=0,mp=0,buyer=0,known=true,costKnown=true,profileKnown=true;
  for (const r of orders) {
    const key=entity(r),h=history.get(key),p=profiles.get(key);
    if(!h||h.sold+h.cancelled<=0){known=false;continue;}
    const q=r.qty*h.sold/(h.sold+h.cancelled), rev=r.amount*h.sold/(h.sold+h.cancelled);
    qty+=q;revenue+=rev;
    if(costs.has(key))cost+=q*costs.get(key);else costKnown=false;
    if(p&&p.qty>0&&p.revenue>0){mp+=rev*p.mp/p.revenue;buyer+=rev*p.buyer/p.revenue;}else profileKnown=false;
  }
  if(orders.length&&known){
    x.forecastQty=qty;x.forecastRevenue=revenue;x.forecastCost=costKnown?cost:null;
    if(profileKnown){x.mpCost=mp;x.buyerPrice=qty>0?buyer/qty:null;x.tax=finance.tax_rate!=null?buyer*finance.tax_rate:null;}
    if(costKnown&&profileKnown&&x.ads!=null)x.forecastOperating=revenue-cost-mp-x.ads;
    if(x.forecastOperating!=null&&x.tax!=null&&x.external!=null)x.forecastProfit=x.forecastOperating-x.tax-x.external;
  }
  // Period stock is the mean of daily totals, matching the reference's convention.
  const stocks=(finance.stocks||[]).filter(inPeriod), stockDays=new Map();
  for(const r of stocks){const d=stockDays.get(r.day)||[];d.push(r);stockDays.set(r.day,d);}
  const expectedDays=Math.round((Date.parse(to)-Date.parse(from))/86400000)+1;
  const entities=new Set([...traffic,...events.filter(r=>["orders","ads","pending","cancelled"].includes(r.kind)),...daily].map(entity));
  const complete=stockDays.size===expectedDays&&[...stockDays.values()].every(rs=>[...entities].every(k=>rs.some(r=>entity(r)===k)));
  if(stocks.length&&complete){
    for(const f of ["stock","stockFbs","transit","reverse"])x[f]=stocks.every(r=>r[f]!=null)?sum(stocks,f)/expectedDays:null;
    if(stocks.every(r=>costs.has(entity(r)) && [r.stock,r.stockFbs,r.transit,r.reverse].every(v=>v!=null)))x.stockCost=stocks.reduce((s,r)=>s+(r.stock+r.stockFbs+(r.transit??0)+(r.reverse??0))*costs.get(entity(r)),0)/expectedDays;
  }
  if (!traffic.length) for (const field of ["impressions","search_impressions","clicks","carts"]) x[field]=null;
  const observedEntities=new Set([...traffic,...events.filter(r=>["orders","ads","pending","cancelled"].includes(r.kind)),...daily].map(entity));
  x.trafficPairs=new Set(traffic.map(r=>JSON.stringify([r.day,entity(r)]))).size;
  x.expectedPairs=observedEntities.size*expectedDays;
  x.trafficComplete=x.trafficPairs===x.expectedPairs;
  x.stockComplete=complete;x.trafficDays=new Set(traffic.map(r=>r.day)).size;x.expectedDays=expectedDays;
  return x;
}
export const safeRatio=(a,b)=>a!=null&&b>0?a/b:null;
export const entityKey=entity;
