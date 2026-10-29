import test from 'node:test';
import assert from 'node:assert/strict';
import { funnelTotal } from './ozonFunnelMetrics.js';
import { metrics, percentMetrics } from './ozonFunnelDefinitions.js';

const id = {account_id:'a', sku:'123'};
const traffic = [{...id, day:'2026-10-26', impressions:100, search_impressions:50, clicks:10, carts:2, position:5}];
const related = [
  {...id, day:'2026-10-27', kind:'orders', qty:3, amount:300},
  {...id, day:'2026-10-27', kind:'ads', amount:10},
  {...id, day:'2026-10-26', kind:'history', qty:8, amount:2},
  {...id, day:'2026-10-26', kind:'cost', amount:20},
];
const finance = {periodStart:'2026-10-26', external:0, tax_rate:.08, stocks:[], daily:[
  {...id, day:'2026-10-20', sold:10, returned:0, revenue:1000, buyer:800, mp_cost:100},
  {...id, day:'2026-10-27', sold:7, returned:1},
]};

test('missing Excel day does not remove orders or event-day buyouts', () => {
  const r=funnelTotal(traffic,related,finance,'2026-10-27','2026-10-27');
  assert.equal(r.orders,3); assert.equal(r.delivered,7); assert.equal(r.returned,1);
  assert.equal(r.ads,10); assert.equal(r.impressions,null);
});

test('SKU history drives forecast and money equations independently of event-day sales', () => {
  const r=funnelTotal(traffic,related,finance,'2026-10-26','2026-10-27');
  assert.equal(r.forecastRevenue,240); assert.ok(Math.abs(r.forecastQty-2.4)<1e-10);
  assert.equal(r.forecastCost,48); assert.equal(r.mpCost,24); assert.equal(r.forecastOperating,158);
  assert.ok(Math.abs(r.tax-15.36)<1e-10); assert.ok(Math.abs(r.forecastProfit-142.64)<1e-10);
  assert.equal(r.stock,null);
});

test('stock uses daily means, not the last day, and requires complete coverage', () => {
  const stocks=[{...id,day:'2026-10-26',stock:10,stockFbs:0,transit:2,reverse:0},
    {...id,day:'2026-10-27',stock:20,stockFbs:0,transit:4,reverse:0}];
  const r=funnelTotal(traffic,related,{...finance,stocks},'2026-10-26','2026-10-27');
  assert.equal(r.stock,15); assert.equal(r.transit,3); assert.equal(r.stockCost,360);
  assert.equal(funnelTotal(traffic,related,{...finance,stocks:stocks.slice(1)},'2026-10-26','2026-10-27').stock,null);
});

test('unclassified campaigns do not produce partial ad breakdowns', () => {
  const advertising=[{...id,day:'2026-10-27',kind:'auto',amount:4},{...id,day:'2026-10-27',kind:null,amount:6}];
  assert.equal(funnelTotal(traffic,related,{...finance,advertising},'2026-10-26','2026-10-27').adsAuto,null);
  advertising[1].kind='cpc';
  const r=funnelTotal(traffic,related,{...finance,advertising},'2026-10-26','2026-10-27');
  assert.equal(r.adsAuto,4); assert.equal(r.adsCpc,6);
  assert.equal(metrics.length,55); assert.ok(percentMetrics.has(4));
});
