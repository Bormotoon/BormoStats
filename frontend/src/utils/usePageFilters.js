import { useSearchParams } from "react-router-dom";
import { DEFAULT_DATE_FROM_OFFSET, isoDay, periodLabel } from "./formats.js";

/** The period and marketplace of the page from the address bar, with the defaults filled in. */
export function usePageFilters() {
  const [searchParams] = useSearchParams();
  const dateFrom = searchParams.get("dateFrom") || isoDay(DEFAULT_DATE_FROM_OFFSET);
  const dateTo = searchParams.get("dateTo") || isoDay(0);
  return {
    searchParams,
    dateFrom,
    dateTo,
    marketplace: searchParams.get("marketplace") || "",
    accountId: searchParams.get("accountId") || "",
    // "за 19.09.2026 – 18.10.2026", for card captions
    period: `за ${periodLabel(dateFrom, dateTo)}`,
    query: {
      date_from: dateFrom,
      date_to: dateTo,
      marketplace: searchParams.get("marketplace") || "",
      account_id: searchParams.get("accountId") || "",
    },
  };
}
