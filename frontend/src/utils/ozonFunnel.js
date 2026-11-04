// Multi-marketplace funnel report parser for Ozon, Wildberries, and Yandex Market.
const normalize = (s) => String(s || "").replace(/\s+/g, " ").trim().toLowerCase();

export function parseDay(raw) {
  if (raw instanceof Date) {
    return raw.toISOString().slice(0, 10);
  }
  const s = String(raw || "").trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const dot = s.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (dot) return `${dot[3]}-${dot[2].padStart(2, "0")}-${dot[1].padStart(2, "0")}`;
  const slash = s.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
  if (slash) return `${slash[1]}-${slash[2].padStart(2, "0")}-${slash[3].padStart(2, "0")}`;
  const iso = s.match(/^(\d{4}-\d{2}-\d{2})/);
  if (iso) return iso[1];
  const num = Number(raw);
  if (Number.isFinite(num) && num > 30000 && num < 60000) {
    const dt = new Date(Math.round((num - 25569) * 86400 * 1000));
    return dt.toISOString().slice(0, 10);
  }
  return "";
}

function cleanSku(val) {
  let s = String(val ?? "").trim();
  if (s.endsWith(".0") && /^\d+\.0$/.test(s)) {
    s = s.slice(0, -2);
  }
  return s;
}

function findCol(arr, candidates) {
  for (const c of candidates) {
    const target = normalize(c);
    const idx = arr.findIndex((v) => {
      const n = normalize(v);
      return n === target || n.includes(target);
    });
    if (idx >= 0) return idx;
  }
  return -1;
}

function findOzonColumn(arr, name) {
  const i = arr.findIndex((v) => normalize(v) === normalize(name));
  if (i < 0) throw new Error(`В отчёте нет столбца «${name}»`);
  return i;
}

function parseOzonReport(rows, head) {
  const h = rows[head], m = rows[head + 1];
  const ix = {
    sku: findOzonColumn(h, "SKU"),
    day: findOzonColumn(h, "День"),
    scheme: findOzonColumn(h, "Схема работы"),
    offer_id: findOzonColumn(h, "Артикул"),
    title: findOzonColumn(h, "Товары"),
    position: findOzonColumn(m, "Позиция в поиске и каталоге"),
    impressions: findOzonColumn(m, "Показы всего"),
    search_impressions: findOzonColumn(m, "Показы в поиске и каталоге"),
    clicks: findOzonColumn(m, "Посещения карточки товара"),
    carts: findOzonColumn(m, "Добавления в корзину всего"),
  };
  const merged = new Map();
  for (const r of rows.slice(head + 2)) {
    const sku = cleanSku(r[ix.sku]);
    const day = parseDay(r[ix.day]);
    if ((!sku && !day) || (sku === "–" && day === "–")) continue;
    if (!/^\d+$/.test(sku) || !/^\d{4}-\d{2}-\d{2}$/.test(day)) {
      throw new Error(`Некорректные SKU или дата: ${sku}, ${day}`);
    }
    const item = {
      sku,
      day,
      scheme: r[ix.scheme] || "",
      offer_id: r[ix.offer_id] || "",
      title: r[ix.title] || "",
    };
    for (const key of ["position", "impressions", "search_impressions", "clicks", "carts"]) {
      const raw = r[ix[key]];
      if (raw === "" || raw == null) throw new Error(`Пустое значение ${key} для SKU ${sku}, ${day}`);
      const value = Number(raw);
      if (!Number.isFinite(value) || value < 0 || (key !== "position" && !Number.isInteger(value))) {
        throw new Error(`Некорректное значение ${key} для SKU ${sku}, ${day}`);
      }
      item[key] = value;
    }
    const k = JSON.stringify([sku, day, item.scheme]);
    const prev = merged.get(k);
    if (prev) {
      const weight = prev.search_impressions + item.search_impressions;
      prev.position = weight
        ? (prev.position * prev.search_impressions + item.position * item.search_impressions) / weight
        : 0;
      for (const field of ["impressions", "search_impressions", "clicks", "carts"]) {
        prev[field] += item[field];
      }
    } else {
      merged.set(k, item);
    }
  }
  if (!merged.size) throw new Error("В отчёте нет строк с данными");
  return [...merged.values()];
}

function parseFlatReport(rows, headIdx, marketplace) {
  const h = rows[headIdx];
  let ixSku = -1;
  let ixOffer = -1;
  let ixTitle = -1;
  let ixDay = -1;
  let ixClicks = -1;
  let ixImpressions = -1;
  let ixCarts = -1;
  let ixScheme = -1;
  let ixPosition = -1;
  let ixSearchImpressions = -1;

  if (marketplace === "wb") {
    ixSku = findCol(h, ["артикул wb", "номенклатура (код 1с)", "номенклатура", "код wb", "nmid"]);
    ixOffer = findCol(h, ["артикул продавца", "артикул поставщика", "артикул"]);
    ixTitle = findCol(h, ["название", "наименование", "название товара", "предмет"]);
    ixDay = findCol(h, ["день", "дата"]);
    ixClicks = findCol(h, ["переходы в карточку", "переходы в карточку товара", "клики"]);
    ixImpressions = findCol(h, ["показы", "просмотры", "показы всего"]);
    ixCarts = findCol(h, ["положили в корзину", "добавления в корзину", "в корзину"]);
    ixScheme = findCol(h, ["схема работы", "склад", "тип поставки"]);
    ixPosition = findCol(h, ["средняя позиция", "позиция в поиске", "позиция"]);
    ixSearchImpressions = findCol(h, ["показы в поиске", "показы в поиске и каталоге"]);
  } else {
    // ym
    ixSku = findCol(h, ["ваш sku", "sku", "артикул товара", "shop sku"]);
    ixOffer = findCol(h, ["ваш sku", "артикул", "артикул товара"]);
    ixTitle = findCol(h, ["название товара", "название", "наименование товара"]);
    ixDay = findCol(h, ["день", "дата"]);
    ixImpressions = findCol(h, ["показы", "показы на витрине", "показы всего"]);
    ixClicks = findCol(h, ["клики", "просмотры карточки", "переходы в карточку"]);
    ixCarts = findCol(h, ["добавления в корзину", "добавления в корзину всего", "в корзину"]);
    ixScheme = findCol(h, ["модель работы", "схема работы"]);
    ixPosition = findCol(h, ["позиция", "средняя позиция"]);
    ixSearchImpressions = findCol(h, ["показы в поиске"]);
  }

  if (ixSku < 0) {
    throw new Error(
      marketplace === "wb"
        ? "В отчёте Wildberries не найден столбец «Артикул WB» или «Номенклатура»"
        : "В отчёте Яндекс Маркета не найден столбец «Ваш SKU»"
    );
  }
  if (ixDay < 0) {
    throw new Error("В отчёте не найден столбец «День» или «Дата»");
  }

  const merged = new Map();
  for (const r of rows.slice(headIdx + 1)) {
    const sku = cleanSku(r[ixSku]);
    const day = parseDay(r[ixDay]);
    if (!sku || !day || (sku === "–" && day === "–")) continue;
    if (!/^[A-Za-z0-9._:-]+$/.test(sku) || !/^\d{4}-\d{2}-\d{2}$/.test(day)) {
      throw new Error(`Некорректные SKU или дата: ${sku}, ${day}`);
    }

    const offer_id = ixOffer >= 0 ? cleanSku(r[ixOffer]) : sku;
    const title = ixTitle >= 0 ? String(r[ixTitle] || "").trim() : "";
    const scheme = ixScheme >= 0 ? String(r[ixScheme] || "").trim() : (marketplace === "wb" ? "fbo" : "fby");

    const rawClicks = ixClicks >= 0 ? r[ixClicks] : 0;
    const clicks = Number(rawClicks || 0);

    const rawImpressions = ixImpressions >= 0 ? r[ixImpressions] : clicks;
    const impressions = Number(rawImpressions || 0);

    const rawCarts = ixCarts >= 0 ? r[ixCarts] : 0;
    const carts = Number(rawCarts || 0);

    const rawPosition = ixPosition >= 0 ? r[ixPosition] : 0;
    const position = Number(rawPosition || 0);

    const rawSearch = ixSearchImpressions >= 0 ? r[ixSearchImpressions] : 0;
    const search_impressions = Number(rawSearch || 0);

    if (
      !Number.isFinite(clicks) || clicks < 0 ||
      !Number.isFinite(impressions) || impressions < 0 ||
      !Number.isFinite(carts) || carts < 0 ||
      !Number.isFinite(position) || position < 0 ||
      !Number.isFinite(search_impressions) || search_impressions < 0
    ) {
      throw new Error(`Некорректные числовые метрики для SKU ${sku}, ${day}`);
    }

    const item = {
      sku,
      day,
      scheme,
      offer_id: offer_id || sku,
      title,
      position,
      impressions: Math.round(impressions),
      search_impressions: Math.round(search_impressions),
      clicks: Math.round(clicks),
      carts: Math.round(carts),
    };

    const k = JSON.stringify([sku, day, item.scheme]);
    const prev = merged.get(k);
    if (prev) {
      const weight = prev.search_impressions + item.search_impressions;
      prev.position = weight
        ? (prev.position * prev.search_impressions + item.position * item.search_impressions) / weight
        : 0;
      for (const field of ["impressions", "search_impressions", "clicks", "carts"]) {
        prev[field] += item[field];
      }
    } else {
      merged.set(k, item);
    }
  }

  if (!merged.size) throw new Error("В отчёте нет строк с данными");
  return [...merged.values()];
}

export function parseOzonFunnel(rows, marketplace = "ozon") {
  if (!Array.isArray(rows) || !rows.length) {
    throw new Error("Файл пуст или не содержит строк");
  }

  const isWbExplicit = marketplace === "wb";
  const isYmExplicit = marketplace === "ym";

  // Check for Ozon 2-tier header
  const ozonHead = rows.findIndex(
    (r) =>
      Array.isArray(r) &&
      r.some((v) => normalize(v) === "sku") &&
      r.some((v) => normalize(v) === "день")
  );

  // Check for WB header
  const wbHead = rows.findIndex(
    (r) =>
      Array.isArray(r) &&
      r.some((v) => {
        const n = normalize(v);
        return (
          n === "артикул wb" ||
          n === "номенклатура (код 1с)" ||
          n === "номенклатура" ||
          n === "переходы в карточку"
        );
      })
  );

  // Check for YM header
  const ymHead = rows.findIndex(
    (r) =>
      Array.isArray(r) &&
      r.some((v) => {
        const n = normalize(v);
        return (
          n === "ваш sku" ||
          (n.includes("название товара") && r.some((c) => normalize(c).includes("показы")))
        );
      })
  );

  if (isWbExplicit || (wbHead >= 0 && ozonHead < 0 && ymHead < 0)) {
    const headIdx = wbHead >= 0 ? wbHead : ozonHead;
    if (headIdx < 0) {
      throw new Error("Не найдены заголовки отчёта Wildberries («Артикул WB», «Переходы в карточку»)");
    }
    return parseFlatReport(rows, headIdx, "wb");
  }

  if (isYmExplicit || (ymHead >= 0 && ozonHead < 0 && wbHead < 0)) {
    const headIdx = ymHead >= 0 ? ymHead : ozonHead;
    if (headIdx < 0) {
      throw new Error("Не найдены заголовки отчёта Яндекс Маркета («Ваш SKU», «Показы»)");
    }
    return parseFlatReport(rows, headIdx, "ym");
  }

  if (ozonHead >= 0 && rows[ozonHead + 1]) {
    return parseOzonReport(rows, ozonHead);
  }

  throw new Error("Не найдены заголовки отчёта воронки (поддерживаются отчёты Ozon, WB и Яндекс Маркет)");
}
