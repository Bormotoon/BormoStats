import { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "motion/react";
import { request } from "../utils/api.js";
import { marketplaceName } from "../utils/formats.js";
import { Storefront, CaretDown, Check } from "@phosphor-icons/react";

const ALL_ACCOUNTS_VALUE = "";
const ALL_LABEL = "Все площадки";

export default function AccountSwitcher() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [accounts, setAccounts] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const currentAccountId = searchParams.get("accountId") || ALL_ACCOUNTS_VALUE;
  const currentMarketplace = searchParams.get("marketplace") || "";
  // account ids repeat across marketplaces (both seeded cabinets are "default"), so an
  // account is the pair, and picking one sets the marketplace filter too
  const isCurrent = (acct) => acct.account_id === currentAccountId && acct.marketplace === currentMarketplace;

  useEffect(() => {
    request("/api/v1/accounts", { admin: true })
      .then((data) => setAccounts(Array.isArray(data) ? data : []))
      .catch(() => setAccounts([]));
  }, []);

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const selectAccount = (acct) => {
    const next = new URLSearchParams(searchParams);
    if (acct) {
      next.set("accountId", acct.account_id);
      next.set("marketplace", acct.marketplace);
    } else {
      next.delete("accountId");
      next.delete("marketplace");
    }
    setSearchParams(next);
    setOpen(false);
  };

  // an account is the shop on one marketplace, so the switcher picks a marketplace
  const selectedLabel = currentMarketplace ? marketplaceName(currentMarketplace) : ALL_LABEL;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)] hover:bg-[var(--color-surface-container)] text-sm text-[var(--color-on-surface)] transition-colors whitespace-nowrap"
      >
        <Storefront size={16} weight="regular" />
        <span className="max-w-[160px] truncate">{selectedLabel}</span>
        <CaretDown size={12} weight="bold" className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.96 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute right-0 mt-1 w-64 z-50 bg-white border border-[var(--color-outline-variant)] rounded-xl shadow-lg overflow-hidden"
          >
            <button
              onClick={() => selectAccount(null)}
              className={`flex items-center gap-3 w-full px-4 py-2.5 text-sm text-left hover:bg-[var(--color-surface-container)] transition-colors ${
                currentAccountId === ALL_ACCOUNTS_VALUE ? "bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)]" : "text-[var(--color-on-surface)]"
              }`}
            >
              <span className="w-5 flex justify-center">
                {currentAccountId === ALL_ACCOUNTS_VALUE && <Check size={16} weight="bold" />}
              </span>
              <span className="font-medium">{ALL_LABEL}</span>
            </button>
            <div className="border-t border-[var(--color-outline-variant)]" />

            {accounts.map((acct) => {
              const mpName = marketplaceName(acct.marketplace);
              return (
                <button
                  key={`${acct.marketplace}-${acct.account_id}`}
                  onClick={() => selectAccount(acct)}
                  className={`flex items-center gap-3 w-full px-4 py-2.5 text-sm text-left hover:bg-[var(--color-surface-container)] transition-colors ${
                    isCurrent(acct) ? "bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)]" : "text-[var(--color-on-surface)]"
                  }`}
                >
                  <span className="w-5 flex justify-center">
                    {isCurrent(acct) && <Check size={16} weight="bold" />}
                  </span>
                  <div className="flex flex-col">
                    <span className="font-medium">{mpName}</span>
                    {acct.title && acct.title !== mpName && acct.title !== "default" && (
                      <span className="text-xs text-[var(--color-on-surface-variant)]">{acct.title}</span>
                    )}
                  </div>
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
