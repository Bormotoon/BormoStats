// BormoStats content script — показываем оверлей с данными конкурента
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
    const match = window.location.pathname.match(
      /\/catalog\/(\d+)\/detail\.aspx/
    );
    if (match) return { marketplace: "wb", product_id: parseInt(match[1], 10) };
    const ozonMatch = window.location.pathname.match(/\/product\/([\w-]+)/);
    if (ozonMatch) {
      const id = ozonMatch[1].split("-").pop();
      return { marketplace: "ozon", product_id: parseInt(id, 10) };
    }
    return null;
  }

  async function loadData() {
    const info = extractProductId();
    if (!info) return;

    const data = await chrome.storage.sync.get(["apiUrl", "apiKey"]);
    if (!data.apiUrl) return;

    try {
      const resp = await fetch(
        `${data.apiUrl}/${info.marketplace}/${info.product_id}`,
        { headers: data.apiKey ? { "X-API-Key": data.apiKey } : {} }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const product = await resp.json();
      render(product);
    } catch (e) {
      document.getElementById(
        "bormostats-content"
      ).innerHTML = `<span style="color:#f38ba8">Error: ${e.message}</span>`;
    }
  }

  function render(product) {
    const priceRow =
      product.price_history && product.price_history[0]
        ? `<div>Price: ${product.price_history[0].price_rub} ₽` +
          (product.price_history[0].sale_percent
            ? ` <span style="color:#a6e3a1">-${product.price_history[0].sale_percent}%</span>`
            : "") +
          ` | Stock: ${product.price_history[0].in_stock}</div>`
        : "";

    const posHtml =
      product.search_positions && product.search_positions.length
        ? "<div style='margin-top:6px'>" +
          product.search_positions
            .slice(0, 5)
            .map(
              (p) =>
                `<div>#${p.position} for "${p.query}"</div>`
            )
            .join("") +
          "</div>"
        : "";

    document.getElementById("bormostats-content").innerHTML =
      `<div style="color:#89b4fa;font-weight:bold">${product.name}</div>` +
      `<div style="color:#a6adc8;font-size:12px">${product.brand} · ${product.supplier_name}</div>` +
      `<div>⭐ ${product.rating} (${product.review_count} reviews)</div>` +
      priceRow +
      posHtml;

    overlay.style.display = "block";
  }

  const showBtn = document.createElement("button");
  showBtn.textContent = "📊 BormoStats";
  showBtn.style.cssText =
    "position:fixed;bottom:16px;right:16px;z-index:999998;" +
    "background:#4f46e5;color:#fff;border:none;border-radius:8px;" +
    "padding:8px 16px;cursor:pointer;font-size:13px;";
  showBtn.onclick = () => {
    overlay.style.display =
      overlay.style.display === "none" ? "block" : "none";
    if (overlay.style.display === "block") loadData();
  };
  document.body.appendChild(showBtn);
})();
