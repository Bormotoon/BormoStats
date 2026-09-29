(function () {
  /* global BORMOSTATS_PROTOCOL */
  const overlay = document.createElement("div");
  overlay.id = "bormostats-overlay";
  overlay.style.cssText =
    "position:fixed;bottom:16px;right:16px;z-index:999999;background:#1e1e2e;" +
    "color:#cdd6f4;border-radius:12px;padding:16px;font-family:monospace;" +
    "font-size:13px;max-width:320px;box-shadow:0 4px 24px rgba(0,0,0,0.3);" +
    "display:none;";
  const header = document.createElement("div");
  header.style.cssText = "display:flex;justify-content:space-between;margin-bottom:8px";
  const heading = document.createElement("strong");
  heading.style.color = "#89b4fa";
  heading.textContent = "BormoStats";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.style.cssText = "background:none;border:none;color:#6c7086;cursor:pointer;font-size:16px";
  closeBtn.textContent = "×";
  header.append(heading, closeBtn);
  const content = document.createElement("div");
  content.textContent = "Loading...";
  overlay.append(header, content);
  document.body.appendChild(overlay);

  closeBtn.onclick = () => {
    overlay.style.display = "none";
  };

  function send(type, data) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ v: BORMOSTATS_PROTOCOL.version, type, data }, (response) => {
        resolve(response || { ok: false, error: chrome.runtime.lastError?.message || "no response" });
      });
    });
  }

  function line(text, color) {
    const el = document.createElement("div");
    if (color) el.style.color = color;
    el.textContent = text;
    return el;
  }

  function extractProductId() {
    const match = window.location.pathname.match(/\/catalog\/(\d+)\/detail\.aspx/);
    if (match) return { marketplace: "wb", product_id: parseInt(match[1], 10) };
    const ozonMatch = window.location.pathname.match(/\/product\/([\w-]+)/);
    if (ozonMatch) {
      const id = ozonMatch[1].split("-").pop();
      return { marketplace: "ozon", product_id: parseInt(id, 10) };
    }
    return null;
  }

  function extractSearchResults() {
    const isWb = window.location.hostname.includes("wildberries");
    const isOzon = window.location.hostname.includes("ozon");
    if (!isWb && !isOzon) return [];
    const results = [];
    if (isWb) {
      const items = document.querySelectorAll('[class*="product-card"]');
      items.forEach((el, i) => {
        const link = el.querySelector("a");
        const nmMatch = link?.href?.match(/\/catalog\/(\d+)\/detail\.aspx/);
        if (nmMatch) {
          results.push({ product_id: parseInt(nmMatch[1], 10), position: i + 1 });
        }
      });
    }
    if (isOzon) {
      const items = document.querySelectorAll('[data-widget="searchResults"] a[href*="/product/"]');
      items.forEach((el, i) => {
        const match = el.href.match(/\/product\/([\w-]+)/);
        if (match) {
          const id = match[1].split("-").pop();
          results.push({ product_id: parseInt(id, 10), position: i + 1 });
        }
      });
    }
    return results;
  }

  function extractCompetitorPrice() {
    const info = extractProductId();
    if (!info) return null;
    let price = null;
    let priceWithDiscount = null;
    let name = "";
    if (info.marketplace === "wb") {
      const priceEl = document.querySelector("[class*='price-block']");
      if (priceEl) {
        const texts = priceEl.textContent.match(/[\d\s]+/g);
        if (texts) {
          const prices = texts.map((t) => parseInt(t.replace(/\s/g, ""), 10)).filter((n) => n > 0);
          if (prices.length > 0) price = prices[0];
          if (prices.length > 1) priceWithDiscount = prices[1];
        }
      }
      const titleEl = document.querySelector("h1");
      if (titleEl) name = titleEl.textContent.trim();
    } else {
      const priceEl = document.querySelector("[data-widget='webPrice'], [class*='price']");
      if (priceEl) {
        const match = priceEl.textContent.match(/[\d\s]+/);
        if (match) price = parseInt(match[0].replace(/\s/g, ""), 10);
      }
      const titleEl = document.querySelector("h1");
      if (titleEl) name = titleEl.textContent.trim();
    }
    return { ...info, competitor_name: name, price_rub: price, price_with_discount_rub: priceWithDiscount, in_stock: true, snapshot_ts: new Date().toISOString() };
  }

  async function loadData() {
    const info = extractProductId();
    if (!info) return;
    const response = await send(BORMOSTATS_PROTOCOL.types.productOverlay, info);
    if (!response.ok) {
      content.replaceChildren(line(`Error: ${response.error}`, "#f38ba8"));
      return;
    }
    render(response.result);
  }

  // All API values are rendered with textContent: scraped/competitor data must
  // never be interpreted as HTML inside the marketplace page.
  function render(product) {
    const rows = [
      line(String(product.name ?? ""), "#89b4fa"),
      line(`${product.brand ?? ""} · ${product.supplier_name ?? ""}`, "#a6adc8"),
      line(`⭐ ${product.rating ?? 0} (${product.review_count ?? 0} reviews)`),
    ];
    const latest = product.price_history && product.price_history[0];
    if (latest) {
      const sale = latest.sale_percent ? ` -${latest.sale_percent}%` : "";
      rows.push(line(`Price: ${latest.price_rub} ₽${sale} | Stock: ${latest.in_stock}`));
    }
    (product.search_positions || []).slice(0, 5).forEach((p) => {
      rows.push(line(`#${p.position} for "${p.query}"`));
    });
    content.replaceChildren(...rows);
    overlay.style.display = "block";
  }

  const showBtn = document.createElement("button");
  showBtn.textContent = "📊 BormoStats";
  showBtn.style.cssText =
    "position:fixed;bottom:16px;right:16px;z-index:999998;" +
    "background:#4f46e5;color:#fff;border:none;border-radius:8px;" +
    "padding:8px 16px;cursor:pointer;font-size:13px;";
  showBtn.onclick = () => {
    overlay.style.display = overlay.style.display === "none" ? "block" : "none";
    if (overlay.style.display === "block") loadData();
  };
  document.body.appendChild(showBtn);

  const keyword = new URLSearchParams(window.location.search).get("search") || new URLSearchParams(window.location.search).get("text") || "";
  const searchResults = extractSearchResults();
  if (keyword && searchResults.length > 0) {
    const positions = searchResults.map((r) => ({
      marketplace: window.location.hostname.includes("wildberries") ? "wb" : "ozon",
      keyword,
      product_id: r.product_id,
      position: r.position,
      search_ts: new Date().toISOString(),
    }));
    send(BORMOSTATS_PROTOCOL.types.serpPositions, positions);
  }

  const compPrice = extractCompetitorPrice();
  if (compPrice && compPrice.price_rub) {
    send(BORMOSTATS_PROTOCOL.types.competitorPrice, compPrice);
  }
})();
