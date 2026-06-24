import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { request } from "../utils/api.js";
import { moneyFmt, numberFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";
import { FloppyDisk, MagicWand, PencilSimple, Plus, Check } from "@phosphor-icons/react";

export default function Pim() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState("products");
  const [products, setProducts] = useState([]);
  const [brands, setBrands] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({});

  useEffect(() => {
    setLoading(true);
    const accountId = searchParams.get("accountId") || "";
    const q = searchQuery || undefined;

    Promise.all([
      request("/api/v1/pim/products", { query: { account_id: accountId, q } }).then(r => r || []).catch(() => []),
      request("/api/v1/pim/brands").then(r => r || []).catch(() => []),
      request("/api/v1/pim/categories").then(r => r || []).catch(() => []),
    ]).then(([p, b, c]) => {
      setProducts(p);
      setBrands(b);
      setCategories(c);
      setLoading(false);
    });
  }, [searchParams, searchQuery]);

  const handleEdit = (product) => {
    setEditingId(product.product_id);
    setDraft({ ...product });
  };

  const handleDraftChange = (field, value) => {
    setDraft((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async (product) => {
    const body = {};
    for (const key of ["title", "description", "seo_keywords", "brand_id", "category_id"]) {
      if (draft[key] !== product[key]) {
        body[key] = draft[key];
      }
    }
    if (Object.keys(body).length === 0) {
      setEditingId(null);
      return;
    }
    const updated = await request(`/api/v1/pim/products/${product.marketplace}/${product.account_id}/${product.product_id}`, {
      method: "PATCH",
      body,
    }).catch(() => null);
    if (updated) {
      setProducts((prev) => prev.map((p) => (p.product_id === product.product_id ? updated : p)));
    }
    setEditingId(null);
  };

  const handleGenerateDescription = async (product) => {
    const desc = await request("/api/v1/pim/products/generate-description", {
      method: "POST",
      body: { title: product.title || "", brand_id: product.brand_id, category_id: product.category_id },
      admin: true,
    }).catch(() => null);
    if (desc) {
      setDraft((prev) => ({ ...prev, description: desc.description }));
    }
  };

  const brandMap = Object.fromEntries(brands.map((b) => [b.brand_id, b.name]));
  const categoryMap = Object.fromEntries(categories.map((c) => [c.category_id, c.name]));

  const columns = [
    { key: "marketplace", label: "MP" },
    { key: "account_id", label: "Account" },
    { key: "product_id", label: "Product ID" },
    { key: "title", label: t("pim.title") },
    { key: "brand_id", label: t("pim.brands"), render: (v) => brandMap[v] || v || "—" },
    { key: "category_id", label: t("pim.categories"), render: (v) => categoryMap[v] || v || "—" },
    { key: "updated_at", label: "Updated" },
  ];

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b border-[var(--color-outline-variant)] pb-2">
        {["products", "brands", "categories"].map((tKey) => (
          <button
            key={tKey}
            onClick={() => setTab(tKey)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              tab === tKey
                ? "bg-[var(--color-primary)] text-white"
                : "text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)]"
            }`}
          >
            {t(`pim.${tKey}`)}
          </button>
        ))}
      </div>

      {tab === "products" && (
        <>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder={t("pim.search")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 px-3 py-1.5 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
            />
          </div>

          {products.length === 0 ? (
            <p className="text-sm text-[var(--color-on-surface-variant)] py-8 text-center">{t("pim.noProducts")}</p>
          ) : (
            <div className="space-y-2">
              {products.map((product) => {
                const isEditing = editingId === product.product_id;
                return (
                  <div key={product.product_id} className="md3-card-elevated p-4">
                    {isEditing ? (
                      <div className="space-y-3">
                        <div className="flex items-center gap-2 text-xs text-[var(--color-on-surface-variant)]">
                          <span className="font-mono">{product.marketplace}/{product.account_id}/{product.product_id}</span>
                        </div>
                        <input
                          className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                          value={draft.title || ""}
                          onChange={(e) => handleDraftChange("title", e.target.value)}
                          placeholder={t("pim.title")}
                        />
                        <textarea
                          className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm min-h-[60px]"
                          value={draft.description || ""}
                          onChange={(e) => handleDraftChange("description", e.target.value)}
                          placeholder="Description"
                        />
                        <div className="flex gap-2">
                          <input
                            className="flex-1 px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                            value={draft.seo_keywords || ""}
                            onChange={(e) => handleDraftChange("seo_keywords", e.target.value)}
                            placeholder="SEO Keywords"
                          />
                          <select
                            className="px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                            value={draft.brand_id || ""}
                            onChange={(e) => handleDraftChange("brand_id", e.target.value)}
                          >
                            <option value="">{t("pim.brands")}...</option>
                            {brands.map((b) => (
                              <option key={b.brand_id} value={b.brand_id}>{b.name}</option>
                            ))}
                          </select>
                          <select
                            className="px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                            value={draft.category_id || ""}
                            onChange={(e) => handleDraftChange("category_id", e.target.value)}
                          >
                            <option value="">{t("pim.categories")}...</option>
                            {categories.map((c) => (
                              <option key={c.category_id} value={c.category_id}>{c.name}</option>
                            ))}
                          </select>
                        </div>
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleGenerateDescription(product)}
                            className="flex items-center gap-1 px-3 py-1 rounded-full bg-[var(--color-surface-container)] text-sm font-medium hover:bg-[var(--color-surface-container-hover)]"
                          >
                            <MagicWand size={14} /> {t("pim.generateDesc")}
                          </button>
                          <button
                            onClick={() => handleSave(product)}
                            className="flex items-center gap-1 px-3 py-1 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium"
                          >
                            <FloppyDisk size={14} /> {t("pim.save")}
                          </button>
                          <button
                            onClick={() => setEditingId(null)}
                            className="px-3 py-1 rounded-full text-sm text-[var(--color-on-surface-variant)]"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-[var(--color-on-surface)]">{product.title || product.product_id}</span>
                            {product.brand_id && <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)]">{brandMap[product.brand_id] || product.brand_id}</span>}
                            {product.category_id && <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)]">{categoryMap[product.category_id] || product.category_id}</span>}
                          </div>
                          {product.description && (
                            <p className="text-xs text-[var(--color-on-surface-variant)] mt-1 line-clamp-2">{product.description}</p>
                          )}
                          <div className="flex items-center gap-2 mt-1 text-xs text-[var(--color-on-surface-variant)]">
                            <span className="font-mono">{product.marketplace}/{product.account_id}/{product.product_id}</span>
                          </div>
                        </div>
                        <button
                          onClick={() => handleEdit(product)}
                          className="shrink-0 p-1.5 rounded-full hover:bg-[var(--color-surface-container)]"
                        >
                          <PencilSimple size={16} />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {tab === "brands" && (
        <BrandSection brands={brands} setBrands={setBrands} />
      )}

      {tab === "categories" && (
        <CategorySection categories={categories} setCategories={setCategories} />
      )}
    </div>
  );
}

function BrandSection({ brands, setBrands }) {
  const { t } = useI18n();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const handleAdd = async () => {
    if (!name.trim()) return;
    const brand = await request("/api/v1/pim/brands", {
      method: "POST",
      body: { name, description },
    }).catch(() => null);
    if (brand) {
      setBrands((prev) => [...prev, brand]);
      setName("");
      setDescription("");
      setShowForm(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <span className="text-sm font-semibold text-[var(--color-on-surface)]">{t("pim.brands")}</span>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1 px-3 py-1 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium"
        >
          <Plus size={14} /> {t("pim.addBrand")}
        </button>
      </div>
      {showForm && (
        <div className="md3-card-elevated p-3 space-y-2">
          <input
            className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Brand name"
          />
          <input
            className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
          />
          <button onClick={handleAdd} className="px-3 py-1 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium">
            <Check size={14} className="inline mr-1" /> {t("pim.save")}
          </button>
        </div>
      )}
      {brands.length === 0 ? (
        <p className="text-sm text-[var(--color-on-surface-variant)] py-4 text-center">{t("pim.noBrands")}</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {brands.map((b) => (
            <div key={b.brand_id} className="md3-card-elevated p-3">
              <p className="text-sm font-medium text-[var(--color-on-surface)]">{b.name}</p>
              {b.description && <p className="text-xs text-[var(--color-on-surface-variant)] mt-1 line-clamp-2">{b.description}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CategorySection({ categories, setCategories }) {
  const { t } = useI18n();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");

  const handleAdd = async () => {
    if (!name.trim()) return;
    const cat = await request("/api/v1/pim/categories", {
      method: "POST",
      body: { name, parent_id: parentId || null },
    }).catch(() => null);
    if (cat) {
      setCategories((prev) => [...prev, cat]);
      setName("");
      setParentId("");
      setShowForm(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <span className="text-sm font-semibold text-[var(--color-on-surface)]">{t("pim.categories")}</span>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1 px-3 py-1 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium"
        >
          <Plus size={14} /> {t("pim.addCategory")}
        </button>
      </div>
      {showForm && (
        <div className="md3-card-elevated p-3 space-y-2">
          <input
            className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Category name"
          />
          <select
            className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
          >
            <option value="">{t("pim.categories")} (root)...</option>
            {categories.map((c) => (
              <option key={c.category_id} value={c.category_id}>{c.name}</option>
            ))}
          </select>
          <button onClick={handleAdd} className="px-3 py-1 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium">
            <Check size={14} className="inline mr-1" /> {t("pim.save")}
          </button>
        </div>
      )}
      {categories.length === 0 ? (
        <p className="text-sm text-[var(--color-on-surface-variant)] py-4 text-center">{t("pim.noCategories")}</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {categories.map((c) => (
            <div key={c.category_id} className="md3-card-elevated p-3">
              <p className="text-sm font-medium text-[var(--color-on-surface)]">{c.name}</p>
              {c.path && <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">{c.path}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
