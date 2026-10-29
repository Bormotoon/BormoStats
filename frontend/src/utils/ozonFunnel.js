// Ozon daily report: two header rows, then a description and a total row.
const normalize = s => String(s || "").replace(/\s+/g, " ").trim().toLowerCase();
export function parseOzonFunnel(rows) {
  const head = rows.findIndex(r => r.some(v => normalize(v) === "sku") && r.some(v => normalize(v) === "день"));
  if (head < 0 || !rows[head + 1]) throw new Error("Не найдены заголовки отчёта Ozon по дням");
  const h = rows[head], m = rows[head + 1];
  const find = (arr, name) => { const i = arr.findIndex(v => normalize(v) === normalize(name)); if (i < 0) throw new Error(`В отчёте нет столбца «${name}»`); return i; };
  const ix = {sku:find(h,"SKU"), day:find(h,"День"), scheme:find(h,"Схема работы"), offer_id:find(h,"Артикул"), title:find(h,"Товары"), position:find(m,"Позиция в поиске и каталоге"), impressions:find(m,"Показы всего"), search_impressions:find(m,"Показы в поиске и каталоге"), clicks:find(m,"Посещения карточки товара"), carts:find(m,"Добавления в корзину всего")};
  const merged = new Map();
  for (const r of rows.slice(head + 2)) {
    const sku = r[ix.sku] || "", day = r[ix.day] || "";
    if ((!sku && !day) || (sku === "–" && day === "–")) continue;
    if (!/^\d+$/.test(sku) || !/^\d{4}-\d{2}-\d{2}$/.test(day)) throw new Error(`Некорректные SKU или дата: ${sku}, ${day}`);
    const item = {sku, day, scheme:r[ix.scheme] || "", offer_id:r[ix.offer_id] || "", title:r[ix.title] || ""};
    for (const key of ["position","impressions","search_impressions","clicks","carts"]) {
      const raw = r[ix[key]];
      if (raw === "" || raw == null) throw new Error(`Пустое значение ${key} для SKU ${sku}, ${day}`);
      const value = Number(raw);
      if (!Number.isFinite(value) || value < 0 || (key !== "position" && !Number.isInteger(value))) throw new Error(`Некорректное значение ${key} для SKU ${sku}, ${day}`);
      item[key] = value;
    }
    const k = JSON.stringify([sku, day, item.scheme]);
    const prev = merged.get(k);
    if (prev) {
      const weight = prev.search_impressions + item.search_impressions;
      prev.position = weight ? (prev.position * prev.search_impressions + item.position * item.search_impressions) / weight : 0;
      for (const field of ["impressions","search_impressions","clicks","carts"]) prev[field] += item[field];
    } else merged.set(k, item);
  }
  if (!merged.size) throw new Error("В отчёте нет строк с данными");
  return [...merged.values()];
}
