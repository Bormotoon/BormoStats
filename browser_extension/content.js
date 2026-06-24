(function () {
  const overlay = document.createElement("div");
  overlay.id = "bormostats-overlay";
  overlay.style.cssText =
    "position:fixed;bottom:16px;right:16px;z-index:999999;background:#1e1e2e;" +
    "color:#cdd6f4;border-radius:12px;padding:16px;font-family:monospace;" +
    "font-size:13px;max-width:320px;box-shadow:0 4px 24px rgba(0,0,0,0.3);" +
    "display:none;";
  overlay.innerHTML =
    '<div style="display:flex;justify-content:space-between;margin-bottom:8px">' +
    '<strong style="color:#89b4fa">BormoStats</strong>' +
    '<button id="bormostats-close" style="background:none;border:none;color:#6c7086;cursor:pointer;font-size:16px">×</button>' +
    "</div>" +
    '<div id="bormostats-content">Loading...</div>';
  document.body.appendChild(overlay);

  document.getElementById("bormostats-close").onclick = () => {
    overlay.style.display = "none";
  };

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
    const data = await chrome.storage.sync.get(["apiUrl", "apiKey"]);
    if (!data.apiUrl) return;
    try {
      const resp = await fetch(`${data.apiUrl}/${info.marketplace}/${info.product_id}`, {
        headers: data.apiKey ? { "X-API-Key": data.apiKey } : {},
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const product = await resp.json();
      render(product);
    } catch (e) {
      document.getElementById("bormostats-content").innerHTML = `<span style="color:#f38ba8">Error: ${e.message}</span>`;
    }
  }

  function render(product) {
    const priceRow = product.price_history && product.price_history[0]
      ? `<div>Price: ${product.price_history[0].price_rub} ₽` +
        (product.price_history[0].sale_percent ? ` <span style="color:#a6e3a1">-${product.price_history[0].sale_percent}%</span>` : "") +
        ` | Stock: ${product.price_history[0].in_stock}</div>`
      : "";
    const posHtml = product.search_positions && product.search_positions.length
      ? "<div style='margin-top:6px'>" +
        product.search_positions.slice(0, 5).map((p) => `<div>#${p.position} for "${p.query}"</div>`).join("") +
        "</div>"
      : "";
    document.getElementById("bormostats-content").innerHTML =
      `<div style="color:#89b4fa;font-weight:bold">${product.name}</div>` +
      `<div style="color:#a6adc8;font-size:12px">${product.brand} · ${product.supplier_name}</div>` +
      `<div>⭐ ${product.rating} (${product.review_count} reviews)</div>` +
      priceRow + posHtml;
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
      account_id: "default",
      marketplace: window.location.hostname.includes("wildberries") ? "wb" : "ozon",
      keyword,
      product_id: r.product_id,
      position: r.position,
      search_ts: new Date().toISOString(),
    }));
    chrome.runtime.sendMessage({ type: "serp_positions", data: positions });
  }

  const compPrice = extractCompetitorPrice();
  if (compPrice && compPrice.price_rub) {
    chrome.runtime.sendMessage({ type: "competitor_price", data: compPrice });
  }
})();
