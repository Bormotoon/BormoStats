// Column contract of the user's two Excel exports: 16 compact / 66 expanded columns.
const c = (key, label, type = 'money') => ({ key, label, type });
const triplet = (key, label) => [c(key+'_unit',label+' на единицу'),c(key,label+', сумма'),c(key+'_pct',label+', процент','percent')];
export const ECONOMICS_GROUPS = [
  {id:'photo',label:'',columns:[c('image_url','Фото','image')]},
  {id:'article',label:'',columns:[c('offer_id','Артикул Продавца','text')]},
  {id:'period',label:'',columns:[c('period','Период','text')]},
  {id:'sales',label:'Продажи',columns:[c('qty','Всего','number'),c('sales_qty','Продажи','number'),c('returns_qty','Возвраты','number'),c('sales_cis','Продажи (СНГ)','number'),c('self_purchases','Самовыкупы','number')]},
  {id:'price',label:'Цена',columns:[c('revenue_unit','На единицу'),c('revenue','Сумма выручки'),c('revenue_rf','РФ'),c('revenue_cis','СНГ')]},
  {id:'buyer',label:'Цена для покупателя',columns:[c('buyer_revenue_unit','На единицу'),c('buyer_revenue','Сумма дохода'),c('buyer_rf','РФ'),c('buyer_cis','СНГ')]},
  {id:'commission',label:'Комиссия',columns:[c('commission_unit','На единицу'),c('commission','Сумма'),c('commission_pct','Процент','percent'),c('commission_rf','РФ'),c('commission_cis','СНГ')]},
  {id:'cogs',label:'Себестоимость',columns:[c('cogs_unit','На единицу'),c('cogs','Сумма'),c('cogs_pct','Процент','percent')]},
  {id:'costs',label:'Расходы внутри МП',columns:[c('mp_cost_unit','На единицу'),c('mp_cost','Сумма'),c('mp_cost_pct','Процент','percent'),
    ...triplet('delivery','Услуги доставки'),...triplet('partners','Услуги партнёров'),...triplet('promotion','Продвижение и реклама'),
    ...triplet('fbo','Услуги FBO'),...triplet('other_services','Другие услуги и штрафы'),
    ...triplet('compensation','Компенсации и декомпенсации'),...triplet('other_accruals','Прочие начисления')]},
  {id:'marketing',label:'Маркетинг',columns:[c('marketing_unit','На единицу'),c('marketing','Сумма'),c('marketing_pct','Процент','percent')]},
  {id:'operating',label:'Операционная прибыль',columns:[c('operating_unit','На единицу'),c('operating','Сумма'),c('operating_pct','Операционная маржа','percent')]},
  {id:'external',label:'Расходы вне МП',columns:[c('external_unit','На единицу'),c('external','Сумма'),c('external_pct','Процент','percent')]},
  {id:'tax',label:'Налог',columns:[c('tax_unit','На единицу'),c('tax','Сумма'),c('tax_main','Сумма основного налога'),c('vat','Сумма НДС')]},
  {id:'profit',label:'Чистая Прибыль',columns:[c('profit_unit','На единицу'),c('profit','Сумма'),c('profit_pct','Рентабельность','percent')]},
  {id:'roi',label:'',columns:[c('roi','ROI','percent')]},
  {id:'abc',label:'ABC',columns:[c('abc','ABC','text')]},
];
export const ALL_ECONOMICS_COLUMNS = ECONOMICS_GROUPS.flatMap(g=>g.columns.map(col=>({...col,group:g.id,groupLabel:g.label})));
export const COMPACT_ECONOMICS_KEYS = ECONOMICS_GROUPS.map(g=>g.columns[0].key);
export function loadEconomicsColumns(storage) {
  try {
    const saved = JSON.parse(storage.getItem('economics:columns:v1'));
    if (Array.isArray(saved)) {
      const valid = saved.filter(k=>ALL_ECONOMICS_COLUMNS.some(c=>c.key===k));
      if (valid.length) return [...new Set(['offer_id',...valid])];
    }
  } catch { /* unavailable local storage: use the compact view */ }
  return COMPACT_ECONOMICS_KEYS;
}
